# 10. Signing in

Threads: B (full-stack engineering)

## The idea

Before hax can answer questions about "your" documents, it has to know who "you" are. Sign-in is the front desk of a building: one desk checks your ID once and hands you a badge, and every door after that only checks the badge.

In hax the badge is a JWT (JSON Web Token: a short text stating who you are, signed with a secret so any change breaks the signature). The hard parts are the edges: two people claiming one email, and taking a badge back before it expires.

## How hax does it

Auth.js (a sign-in library for Next.js, the web framework hax's pages run on) is only the front desk: the login and signup screens, the Google sign-in dance, and minting the badge. FastAPI (the Python server behind the chat) owns identity: the `users` table, password hashes (one-way fingerprints that cannot be turned back into the password), and the signup and reset endpoints. The web side never touches the database; every identity question is an HTTP call (a request in the web's standard protocol) to the API (the server endpoints other programs call).

The bridge is a standard HS256 JWT (HS256: one shared secret both signs and checks the token). The minting half is in [`apps/web/auth.ts`](../../apps/web/auth.ts); the checking half is [`packages/core/auth/tokens.py`](../../packages/core/auth/tokens.py). The checker pins HS256 and never trusts the algorithm named in the token's own header. Every signed-in API request goes through one function, `current_user` in [`apps/api/auth.py`](../../apps/api/auth.py).

Passwords are hashed with argon2id (a hashing method built to be slow and memory-hungry, so guessing is expensive). [`packages/core/auth/passwords.py`](../../packages/core/auth/passwords.py) sets time cost 2, 19 MiB (mebibytes, about a million bytes each) of memory and parallelism 1. Hashing runs off the event loop (the single thread that juggles every request) and behind a semaphore (a counter that caps how many run at once), so the memory concurrent logins can use is capped (`ARGON2_MAX_CONCURRENT` per process, default 4). An unknown email still burns one dummy verification, so timing cannot reveal which emails have accounts.

A badge can be taken back. Each token carries `auth_time`, the moment of login, and each user row carries `sessions_valid_after`. A password reset moves that cutoff forward, and any token older than it is refused. To spare the database a read per request, [`packages/core/auth/revocation.py`](../../packages/core/auth/revocation.py) keeps the cutoff in Redis (an in-memory store hax also uses for rate limits) as a write-through cache: every change writes the database and then the cache.

Verify and reset links are single-use tokens. The API stores only a hash of each one, so a stolen table holds no working links; verification links last 24 hours, reset links 1 hour. Every accepted signup answers the same 202 (the HTTP status code for "accepted", here "check your inbox"), so it does not reveal whether an address is registered. Only a rate-limited request (429) or a malformed one (422) answers differently.

## What was decided, and why

[ADR 0011](../adr/0011-auth-architecture.md) (an architecture decision record: a file recording one decision and why) rejected three alternatives: Auth.js owning the user tables (a second writer against one schema), decrypting Auth.js's default token in Python (an undocumented format), and routing every API call through the web server (clashing with streaming chat from FastAPI, and leaving non-browser clients nothing to call).

The Google addendum's subtle rule is rule 3. Anyone can sign up with someone else's address before the real owner does (pre-hijacking). When the real owner later signs in with Google, proving they control the mailbox, hax claims the row; if it was never verified but has a password, it clears the password and revokes its sessions. Only marking the row verified, as first specified, was rejected because it "would launder a pre-registered password past the verification gate." The same thinking shaped signup: on a still-unverified row, the last person to submit owns the pending password, so a victim's own signup can never end up verifying a stranger's password. The ADR records that this narrows the attack rather than closing it: if the attacker signs up again after the victim within the 24-hour window, or the victim confirms an email they did not ask for, the row is verified with the attacker's password, and a password reset recovers it. The Google claim, too, is complete only with the email-verification gate on, which is the default.

## The episode

Revocation first failed open: if Redis was unreachable, the check let the session through rather than lock everyone out.

First, the day the ADR was written, an adversarial review (a deliberate hunt for ways the code fails) found that "fail open" could never fire on a stalled Redis, one whose process is frozen but whose connection still looks alive. Nothing raises, so every signed-in request waits forever. `a94776e` added a 2-second socket timeout (the longest a read may wait) and a 1-second connect timeout (the same, for opening a connection) to [`apps/api/redis_client.py`](../../apps/api/redis_client.py), so a stall becomes a catchable error.

Second, two months later, the rule was reversed: failing open meant a revoked session kept working while Redis was down, or full and refusing writes. `4aee7b8` changed the read path to fall back to the database cutoff, the source of truth. A cutoff a full Redis refuses to store is deleted from the cache instead, so no stale value is served. The rate limiters still fail open, because blocking every login during a cache outage is worse than briefly not limiting.

## Look at

- [`docs/adr/0011-auth-architecture.md`](../adr/0011-auth-architecture.md) — the decision and its addenda.
- [`packages/core/auth/tokens.py`](../../packages/core/auth/tokens.py) — the verifying half of the JWT bridge.
- [`packages/core/auth/passwords.py`](../../packages/core/auth/passwords.py) — argon2id settings, dummy verification, the semaphore.
- [`packages/core/auth/revocation.py`](../../packages/core/auth/revocation.py) — the cutoff cache and its database fallback.
- [`packages/db/repos/users.py`](../../packages/db/repos/users.py) — `claim_by_verified_email` and `replace_pending_password`.
- `d9c678a` — the Google identity endpoint, with the pre-hijack clause.
- `1a2509b` — the ADR addendum recording the four linking rules.
- `c9feb5c` — signup's placeholder branch re-checks "unverified" at write time.
- `a94776e` — bounded Redis waits, so a stalled Redis raises.
- `4aee7b8` — a revoked session stays revoked while Redis is down or full.
