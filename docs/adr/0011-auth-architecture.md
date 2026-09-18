# 0011 — Auth architecture: Auth.js front door, FastAPI identity owner, standard JWT bridge

**Status:** accepted
**Date:** 2026-09-01

## Context

M2.5 needs real auth: email/password + Google sign-in, sessions, and a
`users` table that conversations/documents/chunks can be scoped to (M2 left
those single-tenant). Any non-browser client must be able to verify or
present the same token by calling the API directly — ruling out anything
that only makes sense behind a browser session.

## Decision

Split the auth surface into two pieces with one owner each:

- **Auth.js v5** (`basePath: "/auth"`, in Next) is the **web front door
  only**: login/signup UI, the Google OAuth dance, and minting the session
  JWT. It owns no identity data.
- **FastAPI owns identity**: the `users` table, password hashes, and the
  signup / verify-credentials / reset endpoints. Next **never touches
  Postgres** — every identity operation is an HTTP call to FastAPI. This
  keeps a single DB writer and means any other client hits the exact same
  endpoints Auth.js's `authorize()` calls today.

The two sides are bridged by a **standard HS256 JWT**: Auth.js's custom
`encode`/`decode` (Node `jose`) mints it with the shared `AUTH_SECRET`;
FastAPI's `current_user` dependency verifies it with **PyJWT, pinned
`algorithms=["HS256"]`**, plus `iss="hax"` / `aud="hax-api"` / `exp` checks.
Claims include `auth_time` (the login moment), **carried forward unchanged
across Auth.js's JWT re-issues** — a re-issue must never manufacture a
newer login, because that would let a stolen token launder past a
revocation check that compares `auth_time` against a stamped cutoff (see
Revocation below).

Passwords hash with **argon2id** (argon2-cffi, library defaults).

## Alternatives considered

- **Auth.js's database-adapter mode** (Auth.js owns the `users`/`accounts`
  tables directly): a second writer against the same schema, and it
  couples the data model to Auth.js's shape instead of the app's. Rejected
  to keep FastAPI as the single identity owner any client can talk to
  directly.
- **Decrypting Auth.js's default JWE session token in Python**: works, but
  couples the backend to Auth.js's undocumented internal encryption
  scheme. Swapping to a standard, documented HS256 JWT (still minted by
  Auth.js, just with a custom codec) keeps the token itself
  implementation-agnostic on the verifying side.
- **A BFF proxy** (Next terminates all API calls, backend never sees the
  browser): conflicts with ADR 0005 (SSE bypasses the Next dev proxy
  already) and is hostile to a non-browser client, which has no BFF to
  sit behind.

The JWT **session strategy is forced regardless**: Auth.js's Credentials
provider does not create server-side DB sessions, so `strategy: "jwt"` is
the only option once Credentials is in the provider list.

## Consequences

**Two-tier gating, not one:** Next's middleware only has enough
information to do a **crypto-only** check (valid signature, not expired) —
it has no Redis/DB access. The **API** layer does the full check: crypto
**plus** the revocation lookup. A token that fails middleware never reaches
the API; a token revoked mid-life passes middleware (still
cryptographically valid) but is rejected at the API, which is where it
actually matters.

**Revocation** is `users.sessions_valid_after` (bumped on password reset,
reusable for a future sign-out-everywhere) compared against the token's
`auth_time`, backed by a Redis write-through cache so the check doesn't hit
Postgres on every request. **Fail-open on Redis errors** — a revocation
check that can't reach its cache degrades to "not yet checked" rather than
locking every session out; core JWT verification is unaffected either way.

`verify-credentials` is **internal-only** (`X-Internal-Secret`-gated, called
server-to-server from Auth.js's `authorize()`, never exposed publicly) and
returns a **404-shaped disguise** on a wrong password rather than a
distinguishable error — the endpoint is a credential oracle by nature (it
exists to say yes/no to a password), so its blast radius is limited to
"reachable only with the internal secret," not "returns a different status
per failure mode."

**Known slice-1 gap:** login rate limiting is currently a per-account
bucket, which is itself a lockout lever (anyone who knows a victim's email
can trip it). Redesign deferred to M3 (tracked in
`local/DEV_BACKLOG.local.md`, "Login rate limiting is architecturally
blind") — not a blocker pre-deploy, since nothing public depends on it yet.

## Related

- [0012](0012-structural-isolation.md) — per-user data isolation once
  `users` exists.
- `local/specs/2026-07-30-m2.5-auth-titles.md` — full design (session/token
  design, threat model, slice breakdown).

## Addendum (2026-09-14): Google sign-in and account linking

Google is an Auth.js OIDC provider in Next, but **identity resolution still
happens in FastAPI**: Auth.js's `signIn` callback POSTs the provider identity
(`provider`, `provider_account_id`, `email`, `email_verified`, `name`) to
`/internal/auth/oauth-upsert` (secret-gated like verify-credentials), and the
returned hax user id replaces the provider's id before the JWT is minted —
`sub` is always a hax user id, so `current_user` and RLS never see a Google
`sub`. Without a database adapter Auth.js hands the `signIn` callback's user
object unchanged to the `jwt` callback (verified against the pinned
version); if that ever changed, the token would carry a non-UUID `sub` and
FastAPI would reject it — a fail-closed, not fail-open, mismatch.

Linking rules, in order, in one transaction:

1. `(provider, provider_account_id)` already linked → that user, even if
   Google now reports a different email (email is the hax identity key and is
   never rewritten by a provider).
2. Provider says the email is **not** verified → `403 email_unverified`,
   nothing written. An unverified provider email proves nothing about who
   controls the mailbox: linking it would be an account takeover (sign in
   with a Google account claiming the victim's address), and creating a user
   from it would squat the address against the real owner.
3. Verified email matching an existing user (case-insensitive) → the
   provider-verified sign-in **claims and links** the row
   (`users_repo.claim_by_verified_email`): stamp `email_verified_at` if NULL, fill `name` only if NULL, and — if the
   row was never verified but already carries a password — clear
   `password_hash` and bump `sessions_valid_after`. That password was set by
   an unproven party (anyone can sign up with someone else's address before
   the owner does; pre-hijacking), so the proven owner's claim discards it and
   revokes its sessions rather than inheriting it. The new cutoff is written
   through to the Redis revocation cache (`publish_sva`) after commit. This
   defense is complete only with `AUTH_REQUIRE_EMAIL_VERIFICATION=true`:
   with the gate off, an unverified placeholder can log in and seed data
   that the claimant then inherits.
4. Otherwise create a verified user with `password_hash` NULL plus the
   account row. Such a user has no password until the reset flow adds one.

The `accounts` unique constraint on `(provider, provider_account_id)` and the
`lower(email)` unique index are the backstop for concurrent first sign-ins:
the loser's INSERT raises `IntegrityError` — at `create_oauth_user`'s flush
for an email collision, at the route's `commit()` for the account row — and
the route rolls back and re-runs the lookups, which now find the winner.

Alternatives considered: doing the upsert in the `jwt` callback (has
`account`/`profile` too) — rejected because a refusal there surfaces as an
Auth.js error page, whereas `signIn` can return a redirect URL and land the
user on `/login` with a specific message; Auth.js
`allowDangerousEmailAccountLinking` — adapter-only and, as named, links on
unverified emails. Stamping verified without clearing an unverified-era
password was the spec's original rule 3; rejected at implementation because
it would launder a pre-registered password past the verification gate.

## Addendum (2026-09-18): Email flows — verification and password reset

**Transport.** Emails are enqueued on the existing Celery worker
(`send_email(to, template, params)`, `apps/worker/tasks.py`), rendered from
one text source into text + HTML (`packages/core/email/templates.py`;
`params` are URLs the API builds, never user text — HTML-escaped and
rendered as anchors), and sent over stdlib `smtplib`/`EmailMessage`
(`packages/core/email/smtp.py`) to `SMTP_HOST:SMTP_PORT` — Mailpit in dev, a
real relay via the same env at deploy. When `SMTP_USER` is set the
connection is upgraded with STARTTLS over a verified `ssl` context and
authenticated; otherwise plaintext SMTP (Mailpit on localhost).
`EmailMessage` raises on CR/LF in a header value, so header injection is
ruled out by the stdlib `EmailMessage` API, not by input filtering.
Transport errors (`SMTPException`/`OSError`) retry at
5/10/20 s then give up quietly — email loss is non-fatal, every link has a
resend path; render errors (bad template/params) propagate immediately, no
retry. The route enqueues only **after** its `commit()`, never before: a
failed commit must not mail a link whose token doesn't exist. The residual
"commit succeeded, enqueue failed" case (Redis down, worker unreachable)
surfaces as a 500 to the caller, who re-requests. Why a worker and not a
synchronous send: relay latency and failures must not sit on the request
path.

**Tokens.** `packages/core/auth/email_tokens.py` generates a 256-bit
`secrets.token_urlsafe(32)`; `packages/db/repos/email_tokens.py` stores only
`sha256(raw)`, with a TTL (24 h verify, 1 h reset) and a purpose. The raw
token is never logged. It exists in the emailed link and in the broker
message that carries that link to the worker (a Redis compromise exposes
live links until they expire), and the page sends it back only in a POST
body. Invariant: **zero or one live token per user per purpose.** Any
issuing path that can add a second live token voids the user's existing
ones of that purpose first (`tokens_repo.void_unused`) — the placeholder
branch of `signup`, `resend-verification`, and `request-password-reset` all
do; the new-address branch of `signup` does not, because a freshly created
user has no tokens to void. Consumption (`verify-email`, `reset-password`)
goes through `tokens_repo.consume`, which is `void_unused` (one `UPDATE …
RETURNING`) plus a membership check on the returned ids — so a double
click, or two live links for the same purpose, resolve to exactly one
winner through one lock order (no deadlock, no ORM check-then-set race).
Links are `{APP_BASE_URL}/verify-email?token=` and `/reset-password?token=`;
the token rides the URL only as far as the page, which POSTs it in a
request body (URLs get logged by proxies/browsers, bodies don't).

**Signup.** `POST /api/auth/signup` returns one uniform 202
`{"status":"check_inbox"}` for every input, and argon2 runs on every branch
(`hash_password_async` before the `get_by_email` lookup) — this equalizes
the dominant cost, but the new-address branch still does its own inserts
after that point, an accepted residual. New address → an
unverified user + a verify link. Existing, verified → an "you already have
an account" email (login + reset links), nothing written. Existing,
unverified placeholder → the last submitter owns the pending password
(`replace_pending_password`: new hash, `sessions_valid_after` bumped, old
verify links voided, a new one issued). That rule is the pre-hijack defense
that link-only verification needs: since nothing but the click proves
ownership, a victim's own signup can never end up verifying a stranger's
password — the residual is an attacker re-signing-up *after* the victim,
inside the 24 h window (targeted, rare, and the victim's next signup attempt
reclaims it again). It doubles as lazy expiry for squatted placeholders — no
sweep job needed. A per-email cap of 3/h on signup mail (a spec tightening)
bounds mail-bombing one address from many IPs; tracked as a targeted-DoS
lever in the backlog.

**Verification.** The `/verify-email` page is link-only — no password
re-entry — and shows a Confirm button that calls the API only on click,
because corporate mail scanners pre-fetch links in transit and would burn
the single-use token before the user arrives. Consuming the token stamps
`email_verified_at`. The login gate
(`AUTH_REQUIRE_EMAIL_VERIFICATION`, default `true` from this slice) means an
unverified password account gets `email_unverified` (403) from
`verify-credentials`, and the login page shows a resend button — the
spec's one accepted enumeration exception, since the user just created the
account and already knows it exists. Success lands on
`/login?verified=1&email=…` — a client navigation to our own page, not an
API redirect; the query is never posted back.

**Reset.** `request-password-reset` is a uniform 202 and issues a link for
any existing account, including Google-born ones with no password — this is
how they gain one. It has the same accepted residual as signup: an existing
address costs an INSERT, a commit and an enqueue that an unknown one does
not. `reset-password` consumes the token, sets the new hash,
stamps `email_verified_at` if still NULL (the link proves the inbox),
bumps `sessions_valid_after`, commits, then write-throughs the new cutoff to
the revocation cache (`publish_sva`) — every prior session dies. It then
clears the `login_email` rate-limit bucket: the owner just proved control of
the inbox by setting the password, so the guessing limiter must not block
the login that follows (the per-IP bucket is untouched). The page then signs
in immediately; if that sign-in fails anyway (e.g. the limiter's per-IP leg
still tripped) it lands on `/login?reset=1` instead of a silent bounce.

**Rate limits**, as shipped: signup 10/h/IP + 3/h/email; resend-verification
and request-password-reset 3/h/email + 10/h/IP; verify-email and
reset-password 10/15 min/IP. The IP bucket is always checked first and
short-circuits on a miss, so a flooding IP burns its own budget before it
can touch a victim's per-email bucket. Redis errors fail open (existing
contract, `packages/core/auth/rate_limit.py`).

Alternatives considered:

- **Password re-entry on the verify page** — closes the pre-hijack race
  completely, but is a non-standard screen for email verification. Replaced
  by "last submitter owns the pending password", with the residual stated
  above instead of eliminated.
- **Binding the verify link to a signup-browser cookie** — breaks
  open-the-link-on-your-phone, a common real flow.
- **Withholding the reset link for social-only (passwordless) accounts** —
  rejected: the reset link IS how those accounts add a password.
- **Sending synchronously inside the request** — rejected: relay latency
  and failures would sit on the request path.
- **A provider HTTP SDK instead of SMTP** — rejected: SMTP is
  provider-neutral, so the M3 relay swap is env-only, no code change.

**Deploy notes.** `APP_BASE_URL` must be the deployed web origin (it's
embedded in every emailed link). `SMTP_*` env points at a real relay with
SPF + DKIM configured on the sending domain. The worker must restart before
or with any deploy that adds a task — Celery discards a message for a task
it doesn't know rather than retrying it.
`AUTH_REQUIRE_EMAIL_VERIFICATION=true` is a launch precondition.
