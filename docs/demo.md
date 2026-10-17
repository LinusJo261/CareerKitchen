# Repeatable fictional HTTP smoke

The HTTP smoke needs a fresh fictional fixture. It performs real persisted
candidate and employer Interested decisions, creates a mutual match, sends a
message, and checks that an unrelated account receives 403. A successful run
consumes this fixture; repeat the reset sequence before the next full smoke.

Stop the demo API and worker first. From the repository root, using the local
development environment:

```powershell
# First use only, when the separate fictional database does not exist:
.\.venv\Scripts\python.exe -m scripts.seed_demo

# For every subsequent smoke, reset only the recognized fictional database:
.\.venv\Scripts\python.exe -m scripts.seed_demo --reset
```

Use one seed command as appropriate. The seed script checks the local database
host, development authentication, database name and fictional marker before a
reset. It targets `career_kitchen_demo`.

Start the demo API in one terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_demo
```

Leave the demo worker stopped during the smoke. In another terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_demo
```

The smoke calls reconciliation itself. Successful JSON output includes the
actual issued-card count, `MUTUAL_MATCH`, message status 200, and unrelated-actor
status 403. It never prints authentication or decision tokens. These are
fictional demonstration outcomes.

After the smoke, the worker can be started for interactive exploration:

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_demo --worker
```

An already-used candidate fixture now produces a clear precondition failure
before reconciliation or human decisions. A full employer inbox can correctly
produce `WAITING_EMPLOYER_SLOT` after the candidate expresses interest; this
does not create mutual interest and does not require an employer decision card
until capacity becomes available. The smoke checks capacity before its first
Interested decision and reports concurrent capacity changes explicitly. It
does not pass other candidates or alter their decisions to free a slot.
