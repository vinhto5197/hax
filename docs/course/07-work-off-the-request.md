# 07. Work off the request

Threads: B (full-stack engineering)

## The idea

Some work is too slow to do while a person waits. Reading a file, splitting it, and embedding every chunk takes seconds of network calls. If the upload request did all of that before answering, the user would stare at a spinner, and a dropped connection could lose the work.

The usual answer is a task queue. The web server writes a note, "ingest document X," into a queue and answers right away. A separate worker process picks the note up and does the job. A restaurant works the same way: the waiter takes the order and leaves the ticket for the kitchen instead of cooking at your table.

## How hax does it

hax uses Celery (a Python task-queue library) with Redis (an in-memory data store) as the broker, the place the notes wait. An upload saves the file to object storage (a service that keeps whole files), creates a `documents` row at `pending`, and publishes an `ingest_document` task. The worker in [`apps/worker/tasks.py`](../../apps/worker/tasks.py) moves the row to `processing`, then `ready` or `failed`.

Failures are sorted into two kinds. A permanent error, such as a missing file, unreadable text or no chunks, fails the document at once, because trying again cannot help. Anything else, such as a blip at Voyage (the embeddings provider), storage or the database, is transient: the task retries after 5, 10 and 20 seconds, then records `failed`. A soft time limit at 270 seconds fails a document that is simply too slow, before the hard kill at 300.

There are two queues, set in [`apps/worker/celery_app.py`](../../apps/worker/celery_app.py). `ingest` holds only ingestion; the default queue, `celery`, holds email, titles and the daily sweeps. Production runs one worker for each, and neither listens to the other's queue, so a long parse never delays a verification email. A test fails if a new task has no route.

Every publish from the API (the FastAPI web server) goes through [`apps/api/enqueue.py`](../../apps/api/enqueue.py). Publishing is a blocking network call, so it runs on a small dedicated thread pool, never on the event loop (the single thread that serves every request in the async API). `fire_and_forget` is for work that has its own recovery, like titles and email. `publish` is awaited where the caller must know: if an upload's task cannot be queued, the document is marked `failed`, so `pending` means a task really exists.

## What was decided, and why

[ADR 0010](../adr/0010-celery-for-ingestion.md) compared three options: ingest inline, FastAPI's `BackgroundTasks` (run the work after the response, inside the web process), or Celery with a separate worker. `BackgroundTasks` does return fast. The ADR's point is that its isolation and retries can be approximated, but durability cannot: if the web process restarts mid-task, the work is gone. Making it survive a restart needs a durable queue, which is a broker, "at which point you've reinvented Celery." Independent scaling was the other reason. RQ, Dramatiq and arq were rejected as the same architecture with less maturity.

The trade-off is more moving parts and at-least-once delivery, meaning a task can run twice. So tasks must be idempotent (safe to repeat): ingestion deletes a document's old chunks before inserting new ones, in one transaction.

## The episode

Four surprises shaped this code.

**Retries that cannot help.** `70af4e2` split ingest errors into permanent and transient, with one function as the only place that writes `failed`, so only a fault that might pass gets another attempt.

**Bombs, and a flag misread.** A few kilobytes of DOCX (a Word document) or PDF can inflate to hundreds of megabytes. `fa3a487` budgeted the parsers (inflated size, PDF pages, extracted text) and put the worker under a 1 GB memory limit. An out-of-memory kill is not an exception, so the same message could come back and kill the next worker forever. The fix read the broker's "redelivered" mark as proof a worker had died, and failed such documents. A day later, `96176c0` reversed that: the mark means "restored," which also happens after a lost acknowledgment (the worker's "done" signal to the broker) or a deploy (rolling out a new version), so good documents were being failed. Now a killed worker's message is acknowledged instead of requeued, and listing documents fails any row still `pending` or `processing` after ten minutes.

**A failed document came back.** That deadline seemed harmless, because a live attempt would write `ready` over it. That stopped being true once a user could re-upload in the meantime: a slow retry of the original could move it from `failed` back to `ready` beside the copy, and every search would then return two chunk sets for one file. `ab2501a` first narrowed the deadline to `processing` only. `950de70` fixed the cause: every status write is now a conditional `UPDATE` (a database write that applies only if the row is still in a given state): `ready` only over `processing`, `failed` only over a row still in flight, so `failed` and `ready` are terminal. With that guard, a `pending` row could get its own six-hour deadline for a lost message.

**A publish is not free.** `c68735f` came from measuring Celery's `.delay()` against a dead broker: about 19 seconds with Redis refusing connections, and over 40 seconds on an unroutable host. Done on the event loop, that would freeze the API for every user. After the change (dedicated threads, `retry=False`, results ignored, a 2-second connect timeout), the ADR records about 6 seconds per publish against a dead broker, off the request path, and about a millisecond when healthy.

## Look at

- [`apps/worker/tasks.py`](../../apps/worker/tasks.py) — retry classes, backoff, time limits
- [`apps/worker/celery_app.py`](../../apps/worker/celery_app.py) — two queues, late acks, no requeue on a lost worker
- [`apps/api/enqueue.py`](../../apps/api/enqueue.py) — the off-loop publisher
- [`packages/core/rag/ingest.py`](../../packages/core/rag/ingest.py) — conditional status writes
- [`packages/core/rag/extract.py`](../../packages/core/rag/extract.py) — parser budgets
- [`apps/api/routers/documents.py`](../../apps/api/routers/documents.py) — the ten-minute and six-hour deadlines
- [ADR 0010](../adr/0010-celery-for-ingestion.md) — Celery over `BackgroundTasks`, and its addenda
- `70af4e2` — transient versus permanent retry classification
- `fa3a487` — bounded parsers, memory fence, redelivered messages failed
- `96176c0` — the redelivered mark means restored; lost messages acknowledged; read-time deadline
- `ab2501a` — the deadline narrowed to `processing`
- `950de70` — `failed` and `ready` are terminal; a deadline for queued rows
- `c68735f` — one off-loop publisher for every producer
