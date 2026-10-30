import pytest

from tests import helpers


@pytest.fixture
def pipeline(tmp_path):
    """Call pipeline(transactions=[...]) to run the full pipeline in a fresh temp folder."""
    opened = []

    def _run(**kwargs):
        run = helpers.run_pipeline(tmp_path, **kwargs)
        opened.append(run.conn)
        return run

    yield _run
    for conn in opened:
        conn.close()
