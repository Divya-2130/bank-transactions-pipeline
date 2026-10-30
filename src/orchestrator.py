"""Orchestrator: runs tasks in dependency order with retries, timeouts,
run status, failure alerts, and a publish gate.

Rules:
- A task runs only if every task it depends on succeeded.
- 'publish' is gated: it also needs EVERY critical task to have succeeded.
- Transient errors are retried. Deterministic failures (schema, quality gate,
  reconciliation) are NOT retried, because they would fail the same way again.
- A timeout stops the wait and fails the task. It is not retried, because a
  Python thread cannot be force-killed and a retry could race with it.
"""
import json
import logging
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from src import tasks as T
from src.schemas import CRITICAL_TASKS

log = logging.getLogger("pipeline")

NON_RETRYABLE = (T.SchemaValidationError, T.QualityGateError, T.ReconciliationError)


class TaskTimeout(Exception):
    """A task ran longer than its allowed time."""


def now():
    return datetime.now().isoformat(timespec="seconds")


def new_run_id():
    return f"run_{datetime.now():%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"


@dataclass
class TaskSpec:
    name: str
    func: Callable
    depends_on: list = field(default_factory=list)
    critical: bool = False
    gated: bool = False      # needs ALL critical tasks to succeed
    retries: int = 2         # extra attempts after the first one
    timeout: float = 300.0   # seconds


def default_specs(retries=2, timeout=300.0):
    def mk(name, deps, **kw):
        return TaskSpec(name=name, func=getattr(T, name), depends_on=deps,
                        critical=name in CRITICAL_TASKS,
                        retries=retries, timeout=timeout, **kw)

    return [
        mk("ingest", []),
        mk("validate_schema", ["ingest"]),
        mk("validate_rules", ["validate_schema"]),
        mk("quarantine", ["validate_rules"]),
        mk("transform", ["validate_rules"]),
        mk("quality_gate", ["validate_rules"]),
        mk("publish", ["transform", "quarantine", "quality_gate"], gated=True),
        mk("reconcile", ["publish"]),
    ]


class Notifier:
    """Failure notifications: a console line plus a JSON line in alerts.log.
    In a real system this is where email or Slack would be called."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, level, run_id, message):
        record = {"time": now(), "level": level, "run_id": run_id, "message": message}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        print(f"[ALERT:{level}] run={run_id} {message}", file=sys.stderr)


class Orchestrator:
    def __init__(self, specs, notifier, retry_delay=1.0,
                 inject_failures=None, inject_delays=None):
        self.specs = specs
        self.by_name = {s.name: s for s in specs}
        self.notifier = notifier
        self.retry_delay = retry_delay
        # Test helpers: simulate transient failures and slow tasks
        self.inject_failures = dict(inject_failures or {})
        self.inject_delays = dict(inject_delays or {})

    # ---------------------------------------------------------- main entry
    def run(self, ctx):
        with ctx.conn:
            ctx.conn.execute(
                "INSERT INTO pipeline_runs (run_id, started_at, status, "
                "accounts_file, transactions_file) VALUES (?, ?, 'running', ?, ?)",
                (ctx.run_id, now(), str(ctx.accounts_path), str(ctx.transactions_path)))
        log.info("run %s started", ctx.run_id)

        results = {}
        for spec in self.specs:
            results[spec.name] = self._execute(spec, ctx, results)
            self._record_task(ctx, spec.name, results[spec.name])
        return self._finish(ctx, results)

    # --------------------------------------------------------- one task
    def _execute(self, spec, ctx, results):
        started = now()

        blocked = [d for d in spec.depends_on if results[d]["status"] != "success"]
        if spec.gated:
            for other in self.specs:
                if (other.critical and other.name not in blocked
                        and results.get(other.name, {}).get("status") != "success"):
                    blocked.append(other.name)
        if blocked:
            log.warning("task %s SKIPPED (not successful upstream: %s)", spec.name, blocked)
            return {"status": "skipped", "attempts": 0, "started_at": started,
                    "ended_at": now(),
                    "error": f"skipped because upstream tasks did not succeed: {blocked}"}

        max_attempts = 1 + spec.retries
        attempts, error, status = 0, None, "failed"
        while attempts < max_attempts:
            attempts += 1
            try:
                self._call_with_timeout(spec, ctx, attempts)
                status, error = "success", None
                log.info("task %s succeeded (attempt %d)", spec.name, attempts)
                break
            except TaskTimeout as exc:
                error = f"TaskTimeout: {exc}"
                log.error("task %s timed out (no retry)", spec.name)
                break
            except NON_RETRYABLE as exc:
                error = f"{type(exc).__name__}: {exc}"
                log.error("task %s failed, not retryable: %s", spec.name, error)
                break
            except Exception as exc:  # transient error: retry
                error = f"{type(exc).__name__}: {exc}"
                log.warning("task %s failed (attempt %d of %d): %s",
                            spec.name, attempts, max_attempts, error)
                if attempts < max_attempts:
                    time.sleep(self.retry_delay * attempts)

        return {"status": status, "attempts": attempts, "started_at": started,
                "ended_at": now(), "error": error}

    def _call_with_timeout(self, spec, ctx, attempt):
        abandoned = threading.Event()
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._invoke, spec, ctx, attempt, abandoned)
            done, _ = wait([future], timeout=spec.timeout)
            if not done:
                abandoned.set()
                raise TaskTimeout(f"{spec.name} exceeded {spec.timeout}s")
            future.result()  # re-raises any error the task raised
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _invoke(self, spec, ctx, attempt, abandoned):
        delay = self.inject_delays.get(spec.name, 0)
        if delay:
            time.sleep(delay)
            if abandoned.is_set():
                return  # we already gave up on this task: do not touch any data
        if self.inject_failures.get(spec.name, 0) > 0:
            self.inject_failures[spec.name] -= 1
            raise RuntimeError(f"injected transient failure in {spec.name} (attempt {attempt})")
        spec.func(ctx)

    # ------------------------------------------------------ bookkeeping
    def _record_task(self, ctx, name, r):
        with ctx.conn:
            ctx.conn.execute(
                "INSERT INTO task_runs (run_id, task_name, status, attempts, "
                "started_at, ended_at, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ctx.run_id, name, r["status"], r["attempts"],
                 r["started_at"], r["ended_at"], r["error"]))

    def _finish(self, ctx, results):
        failed = [n for n, r in results.items() if r["status"] == "failed"]
        skipped = [n for n, r in results.items() if r["status"] == "skipped"]
        status = "success" if not failed and not skipped else "failed"
        reason = "; ".join(f"{n}: {results[n]['error']}" for n in failed) or None

        ingested = results.get("ingest", {}).get("status") == "success"
        rows_in = len(ctx.txn_rows) if ingested else None
        rows_clean = ctx.metrics.get("rows_clean")
        rows_rejected = ctx.metrics.get("rows_rejected")

        with ctx.conn:
            ctx.conn.execute(
                "UPDATE pipeline_runs SET ended_at = ?, status = ?, rows_in = ?, "
                "rows_clean = ?, rows_rejected = ?, failure_reason = ? WHERE run_id = ?",
                (now(), status, rows_in, rows_clean, rows_rejected, reason, ctx.run_id))

        for name in failed:
            level = "CRITICAL" if self.by_name[name].critical else "ERROR"
            msg = f"task '{name}' failed after {results[name]['attempts']} attempt(s): {results[name]['error']}"
            if "publish" in skipped:
                msg += " | publish was BLOCKED: nothing was published"
            self.notifier.send(level, ctx.run_id, msg)

        log.info("run %s finished: %s", ctx.run_id, status.upper())
        return {"run_id": ctx.run_id, "status": status, "tasks": results,
                "metrics": ctx.metrics, "failure_reason": reason}
