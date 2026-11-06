# 14. The demo and its limits

Threads: A (agentic LLM systems) · B (full-stack engineering)

## The idea

The landing page of hax is the demo. A visitor types a question and gets an answer, with no account. Every answer is a paid model call, so a door open to anyone needs a meter on it.

Think of free samples at a store: anyone can take one, a few per person, and nobody asks your name. hax needs three things: an identity cheap enough to hand to strangers, a cap that cannot be gamed, and limits that do not take the site down when the thing counting them breaks.

## How hax does it

**A visitor is a user with no email.** An anonymous visitor is an ordinary row in the `users` table whose `email` is empty (`NULL`), plus a login session whose token (the signed pass the browser presents on each request) carries no email. That is the only marker. Every check is "is the email missing?": in the API (the backend server: `user.email is None` in [demo.py](../../apps/api/demo.py)), in the web app, and in the cleanup job. Apart from the demo caps, a visitor goes through every other boundary exactly as a member does: row-level security (the database itself hides other users' rows), session revocation (signing a session out early), rate limits, and the repository layer (the one code path that queries a user's data). The row is created by an internal endpoint that answers only callers holding a shared secret, here the web app's server, limited per IP address per day (`ANON_PER_IP_PER_DAY`, default 3, in [internal_auth.py](../../apps/api/routers/internal_auth.py)).

**A visitor gets less.** The chat route ([chat.py](../../apps/api/routers/chat.py)) gives a visitor the guest system prompt, the standing instructions the model reads before the conversation ([prompt.md](../../packages/core/demo/prompt.md): instructions plus three short texts about hax), the default model, and no tools (actions the model can choose to take). So there is no document search, and uploads are refused with a 403 (the "forbidden" status). A visitor has `DEMO_TURN_LIMIT` turns in total (default 3). The count is checked before anything is saved. Past the cap, the API answers `403 {"code": "demo_limit"}`, the one signal the web app turns into a sign-up prompt.

**The counter.** `enforce_turn_cap` calls the shared limiter in [rate_limit.py](../../packages/core/auth/rate_limit.py). The limiter is a fixed-window counter in Redis (an in-memory data store): one `INCR` (an atomic add-one) per request on a key like `rl:demo_turns:<user id>`, an expiry on the first hit, and "allowed" while the count is at or under the limit. The demo window is the visitor's retention plus two days. The comment explains why: a key that expired at exactly the retention would hand the same token a second batch of turns before the daily cleanup ran. That cleanup is a scheduled background task that deletes visitor rows older than `ANON_RETENTION_DAYS` (default 3), and with them everything the rows own.

The same limiter guards logins (30 per IP and 5 per email per 15 minutes, in `verify_credentials`) and uploads (5 per hour and 15 per day per user, in [documents.py](../../apps/api/routers/documents.py)).

**Fail-open.** If Redis errors, `hit()` logs a warning and returns "allowed." The module says it in one line: "Redis being down degrades limiting (allow + loud log), never availability."

## What was decided, and why

The [ADR 0011 addendum of 2026-10-01](../adr/0011-auth-architecture.md) records the shape. Anonymity is "the absence of an email, nowhere else." An `is_anonymous` column and token claim were rejected as "a second source of truth for one fact." A seeded corpus per visitor, with retrieval, was built in a fast pass and dropped as more machinery than the demo needs, since the reference texts fit in the prompt. A persistent demo conversation with its own URL was dropped too: the demo is one sitting.

On failure, the repo chose differently for different jobs. The limiters fail open. The [2026-11-04 note in ADR 0011's 2026-10-01 demo addendum](../adr/0011-auth-architecture.md) gives the reason: "blocking every login during a cache outage is worse than briefly not limiting." Session revocation used to fail open as well, which meant a revoked session kept working while Redis was down. That was reversed in `4aee7b8`: a Redis error on that check now falls back to Postgres (the main database), the source of truth, at the cost of one indexed read (a fast lookup by key) per request while Redis is down.

## The episode

**The cap was a count, and counts can shrink (`82c4854`).** The first turn cap counted the visitor's saved messages. That had two holes. Deleting a conversation refunded the turns. And the count and the insert ran in two separate transactions (units of database work), so a burst of concurrent sends all read the same low number and all passed. The fix moved the cap to one atomic increment per send in Redis, windowed to the row's retention. The docstring (the explanatory note at the top) of [demo.py](../../apps/api/demo.py) puts it this way: "The turns are counted by a per-visitor counter that only goes up, never by what is in the database, so deleting a conversation does not refund them." The cap function's own docstring adds that a turn the model then fails is still spent.

**No conversion (`12ef7fb`).** The same day, signing up from the demo was made to start a fresh account rather than claim the visitor's row. The ADR lists what claiming had required: "an optional-caller dependency, a conditional row claim, a signup branch, and a rule about not revoking the claiming session." It was built and dropped "for a result nobody needs in v0." The commit also changed the guest prompt so the sign-up invitation appears in the first answer only, not every turn.

**Fail-open that never fired (`a94776e`).** Earlier, the adversarial review of the first build slice (reviewers told to attack a change, not approve it) found that a stalled Redis, one whose process is frozen but whose network still accepts connections, "answers nothing and raises nothing." Without a socket timeout (a limit on how long to wait for the network), the fail-open branches would never run, and requests would pile up. A 2-second socket timeout made a stall raise an error, which the existing handling already covered.

## Look at

- [apps/api/demo.py](../../apps/api/demo.py): the visitor test, the turn cap, the window
- [packages/core/auth/rate_limit.py](../../packages/core/auth/rate_limit.py): the fixed-window limiter and its fail-open contract
- [apps/api/routers/internal_auth.py](../../apps/api/routers/internal_auth.py): the secret-gated visitor endpoint and its per-IP cap
- [packages/core/demo/prompt.md](../../packages/core/demo/prompt.md): the guest prompt and its reference texts
- [apps/api/routers/chat.py](../../apps/api/routers/chat.py): guest prompt, default model, no tools
- [apps/api/routers/documents.py](../../apps/api/routers/documents.py): the upload caps
- [apps/api/redis_client.py](../../apps/api/redis_client.py): socket timeouts
- [docs/adr/0011-auth-architecture.md](../adr/0011-auth-architecture.md): the 2026-10-01 demo addendum and its 2026-11-04 revocation note
- `82c4854`: the turn cap is a counter that only goes up
- `12ef7fb`: no conversion; the sign-up invitation only in the first answer
- `a94776e`: bound the Redis client's socket waits
- `4aee7b8`: a revoked session stays revoked while Redis is down or full
