# Behaviour-to-test map

Every user-visible behaviour of the web app, and the test that would go red if it regressed. A behaviour change edits this file in the same PR as its test: a new row, or a row's **Pinned by** column.

Swept through: 0cc67f8 — the weekly journeys sweep (`docs/routines/journeys-prompt.md`) checks only the changes after this commit and moves the line in its PR.

Lanes: **J** a Playwright journey in `apps/web/e2e/` can observe it; **U** only a unit test can stage it (a race, an ordering, a mocked boundary); **L** a person has to look. Journey short names: demo = `demo.guest`, newchat = `new-chat.member`, hist = `history.member`, switch = `switch-mid-stream.member`, guard = `turn-guard.member`, setup = `auth.setup`. `py:` is a pytest module under `tests/`. A gap is a behaviour no test in its lane pins; a row whose gap is `–` is covered.

What the e2e stack can stage today, and what it cannot:

- The fake model (`apps/web/e2e/fake-model/server.mjs`) has one default reply, the `slow:` prefix, and the `fail:` prefix (a model failure mid-reply: three pieces, then the connection is cut). It emits no tool_use (so no sources), no table, and cannot drop the client's connection. Rows marked **J\*** need a new prefix.
- The e2e stack runs no worker and points S3 at an unreachable address, so a document never leaves `pending`. Rows marked **J†** need a worker or a scripted storage.

## Chat (member)

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 1 | Enter sends; the question shows above the reply | demo, every member journey | – |
| 2 | Shift+Enter adds a line; Enter during IME composition is ignored | `chat-basics.member` (Shift+Enter) | – (IME: U) |
| 3 | Send disabled when empty; composer and picker disabled while streaming; focus returns after | `chat-basics.member`, useChat.test (whitespace only) | – |
| 4 | Reply streams piece by piece | switch, guard | – |
| 5 | "Assistant is thinking…" and the tool status line | MessageList.test, useChat.test | – |
| 6 | URL becomes `/chat/<id>`; a sidebar row appears | newchat, hist | – |
| 7 | "Untitled" row replaced by the title once polled | py:test_title_trigger | J |
| 8 | Source chips grouped by file, expand to passages, deduplicated | useChat.test | J\* |
| 9 | "Show in panel" reveals and flashes the document row (desktop) | showInPanel.test | J\* |
| 10 | Table sort (numbers; placeholders last), Copy table, Download CSV | DataTable.test (formula escaping only) | J\* |
| 11 | Copy message; timestamp on hover | `chat-thread.member` | – (the hover look: L) |
| 12 | Remote image src removed; code highlighted | none | J (highlighting: L) |
| 13 | View follows the bottom while streaming; scrolling up stops it | `chat-thread.member`, MessageList.test (re-pin on resize) | – |
| 14 | New chat clears the screen and starts a separate conversation | newchat | – |
| 15 | New chat during a reply keeps that reply out of the new chat | switch | – |
| 16 | Switch via the sidebar; reload, back and forward | hist | – |
| 17 | Delete conversation: confirm or cancel; deleting the open one goes to `/chat`; error line | `chat-basics.member`, py:test_authz_conversations | – (error line: no journey can fail a delete) |
| 18 | Empty sidebar shows "No conversations yet" | `chat-basics.member` | – |
| 19 | "Couldn't load this conversation." | useChat.test | – |
| 20 | 409 "reply in progress": message, refused turn removed, retry works | guard, useChat.test, chatApi.test, py:test_turn_guard | – |
| 21a | Model error mid-reply: "The reply was interrupted.", no partial, nothing stored, conversation free | `failed-reply.member`, useChat.test, chatApi.test, py:test_failed_reply, py:test_turn_guard | – |
| 21b | Connection lost mid-reply: error shown, partial kept | useChat.test | J\* |
| 22 | Stream ends without `[DONE]`: no error shown, partial reply looks complete (undecided behaviour) | chatApi.test (delivery), py:test_turn_guard (partial saved) | J\* |
| 23 | Model picker has 4 options; the choice travels with the first turn | `chat-basics.member`, chatApi.test, py:test_demo_limits | – |
| 24 | A 401 signs out to `/login` (or `/` on the landing page) | chatApi.test | – |
| 25 | 20 000-character cap; composer grows on resize | ChatInput.test | – |
| 26 | Sidebar refresh keeps the latest list | ConversationsProvider.test | – |
| 27 | Error line is `role=alert` | ChatWindow.test | – |

## Demo and routing

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 28 | Landing: greeting, blurb, 3 chips, Log in / Sign up, Privacy | `demo-landing.guest` | – |
| 29 | Demo runs in place; URL unchanged | demo, `demo-landing.guest` | – |
| 30 | Clicking a chip sends it | `demo-landing.guest` | – |
| 31 | Guest banner with links; no model picker | `demo-landing.guest` | – |
| 32 | Cap: "End of the demo" modal after 3 turns, turn removed, composer disabled | `demo-landing.guest`, useChat.test, chatApi.test, py:test_demo_limits | – |
| 33 | Demo can't start / rate-limited message | py:test_anonymous_create | J |
| 34 | Redirects: member at `/`, `/login`, `/signup` → `/chat`; guest at `/chat` → `/`; logged out → `/login` | `routing.member`, `routing.guest` | – |

## Documents

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 35 | Upload opens the panel, shows "Uploading…", adds a pending row | chatApi.test | J† |
| 36 | Pending becomes ready via a 2.5 s poll that then stops | none | J† |
| 37 | Failed status; tapping it shows the reason | py:test_ingest_status, py:test_authz_documents | J† |
| 38 | Order: failed, then in progress, then ready | none | J† |
| 39 | Upload refusals (type, 5 MB, 256 KB, hourly and daily caps) shown | `documents-panel.member` (type, 5 MB, 256 KB), chatApi.test, py:test_upload_limits (caps), py:test_authz_documents | – |
| 40 | Delete with confirm; a 404 counts as success | chatApi.test, py:test_authz_documents | J† |
| 41 | Download by clicking the filename; download error message | chatApi.test, py:test_authz_documents | J† |
| 42 | Empty state, count, help text, collapse; closed by default on short screens | `documents-panel.member` | – |

## Sidebar, drawer, phone

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 43 | Phone (<48 rem wide or ≤500 px tall): top bar with menu, logo, +; no fixed sidebar | `drawer.member` (narrow) | – (short landscape: J) |
| 44 | Drawer backdrop out of the Tab order; tapping it closes the drawer | Shell.test | – |
| 45 | Drawer: Escape closes; focus moves in and back; page behind inert and unscrollable; closes on navigation | `drawer.member` | – |
| 46 | Drawer closes when the window becomes desktop width | `drawer.member` | – |
| 47 | "Show in panel" on a phone opens the drawer and reveals the row | none | J\* |
| 48 | Account name and email; Sign out goes to `/` | `routing.member` | – |
| 49 | Active row highlight | none | L |

## Auth

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 50 | Login success goes to `/chat` | setup (not a spec) | – |
| 51 | Wrong-credentials message with Google hint; rate-limit message | `auth-login.guest` (rate limit: py:test_login_gate, API side) | – |
| 52 | Unverified-email message and Resend button | `auth-login.guest`, py:test_login_gate, useResend.test | – |
| 53 | `?error=` messages; `?verified` / `?reset` banners; email prefilled | `auth-login.guest` | – |
| 54 | Signup: check-your-inbox panel, resend, validation, rate limit | `auth-signup.guest` (rate limit: py:test_signup_flow) | – |
| 55 | Verify: no token → invalid view; verifies only on Confirm, then `/login?verified=1`; invalid link → resend form | `auth-signup.guest` (invalid paths), py:test_verify_email | J (the `/login?verified=1` hand-off needs a real token; fixme: tokens never reach a journey) |
| 56 | Forgot password: same panel whatever the email; error messages | `auth-signup.guest`, py:test_password_reset | – |
| 57 | Reset: "Checking your link…", invalid view, validation, success → `/chat` | `auth-signup.guest` (checking, invalid view), py:test_password_reset | J (validation, success; fixme: needs a real reset token) |
| 58 | Reset succeeds but sign-in fails → `/login?reset=1` | none | U |
| 59 | Google button shows "Redirecting…" | none | J (logo: L) |
| 60 | Password Show/Hide | `auth-login.guest` | – |
| 61 | Resend status messages | `auth-login.guest` (sent), useResend.test, authApi.test | – |

## Other

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 62 | Privacy page public; mailto link | `routing.guest` | – |
| 63 | Greeting by time of day and name; weekday; names shown as typed | greeting.test | – |
| 64 | Greeting blank until hydrated | none | U |
| 65 | Wordmark accessible name | Wordmark.test | – |
| 66 | Fonts and dark-mode look | none | L |

## Counts

66 behaviours; 18 covered; 48 gaps: J 44 (J\* 6, J† 6), U 2, L 2.
