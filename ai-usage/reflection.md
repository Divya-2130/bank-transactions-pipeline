# AI usage reflection

## Tool used
Claude (claude.ai chat). No other AI tool was used.

## Where AI accelerated my work
Claude explained the problem statement and the submission rules in simple
language, proposed the plan and the 12 steps, and generated the code for the data
generator, pipeline tasks, orchestrator, tests, benchmark, and the first drafts
of the README, data dictionary and design note.

## Where I relied on AI heavily
I relied on Claude heavily for the design and for writing almost all of the code
and tests. I was new to data pipelines and orchestration, so I asked Claude to
explain concepts in simple terms first, and then to give me the steps and the
commands one step at a time.

## What I personally did, reviewed and validated
- I chose bank transactions as the topic.
- I created the public GitHub repository and ran every command myself on Windows.
- I ran the data generator, the pipeline and the tests, and I reported the outputs
  and errors back so they could be checked.
- I checked that the generator is reproducible by comparing the file hashes of two
  runs with the same seed. They were identical.
- I read the README, the data dictionary and the design note to learn how the
  project works before submitting it.
- I wrote my prompt history by hand and kept my original messages as I sent them,
  including grammar mistakes from voice dictation.

## Problems found and how they were handled
- I first ran a PowerShell command in Command Prompt and got an error. I switched
  to the right shell and ran the commands again.
- I had two copies of the project folder on my laptop. I kept working in the copy
  under Documents, which is the one connected to GitHub.
- While planning the tests, a bug was found in the amount check (a value like 0.004
  passed the check, then rounded to 0). It was fixed and a test was added.

## What I understand well and what I am still learning
I understand the overall flow: the pipeline reads two CSV files, validates them,
saves rejected rows with a reason and a row number, publishes clean data to
SQLite, and checks that the numbers reconcile. I understand that two critical
tasks must pass before publishing, so bad data never reaches the final table, and
that reruns are safe because the load is idempotent.

I am still learning the details of the orchestrator code (retries, timeouts and
threads), the SQL queries in the tasks, and the design trade-offs. I plan to keep
studying them so I can explain them clearly.
