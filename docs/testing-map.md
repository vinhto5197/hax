# Behaviour-to-test map

Every user-visible behaviour of the web app, and the test that would go red if it regressed. A behaviour change edits this file in the same PR as its test: a new row, or a row's **Pinned by** column.

Swept through: 10af3c5 — the weekly journeys sweep (`docs/routines/journeys-prompt.md`) checks only the changes after this commit and moves the line in its PR.

Lanes: **J** a Playwright journey in `apps/web/e2e/` can observe it; **U** only a unit test can stage it (a race, an ordering, a mocked boundary); **L** a person has to look. Journey short names: demo = `demo.guest`, newchat = `new-chat.member`, hist = `history.member`, switch = `switch-mid-stream.member`, guard = `turn-guard.member`, setup = `auth.setup`; the newer journeys go by file stem: `auth-login.guest`, `auth-signup.guest`, `demo-landing.guest`, `routing.guest` and `routing.member`, `chat-basics.member`, `chat-thread.member`, `drawer.member`, `documents-panel.member`, `failed-reply.member`, `still-answering.member`, `about-you.member`, `sources.member`, `rich-replies.member`, `documents-lifecycle.member`, `model-hint.member`, `shell-short.member`, `google-button.guest`, `auth-email.guest`. `py:` is a pytest module under `tests/`. A gap is a behaviour no test in its lane pins; a row whose gap is `–` is covered. **Gap** holds only the lane(s) of the gap, or `–`; a note on partial coverage goes in **Pinned by**, in parentheses.

What the e2e stack can stage today, and what it cannot:

- The fake model (`apps/web/e2e/fake-model/server.mjs`) has one default reply and the prefixes `slow:`, `long:` (twenty pieces over about ten seconds, long enough to reload, switch away or go offline mid-reply), `fail:` (a model failure mid-reply: three pieces, then the connection is cut), `search:` (a `search_documents` tool call, then a fixed reply, so sources), `table:` and `code:`; it titles a conversation only when its first message starts with `title:` (every other conversation stays "Untitled"), and it serves Voyage's embeddings (one identical vector for every text, so a search returns the member's chunks in no defined order; an input containing `slow-embed` waits 8 s). It cannot drop the client's connection. Rows marked **J\*** need a new prefix.
- Two Celery workers (one per queue, solo pool, no beat) and the dev S3 stand-in (bucket `hax-e2e`; a RustFS service container in CI) run with the stack, so documents are ingested end to end; the fast worker's `send_email` sends reach the journeys' own Mailpit (`mailpit-e2e` on :8026 locally, a service container in CI), which `prepare.py` empties at the start of a run, and journeys read the verification and reset links from it (`apps/web/e2e/mail.ts`, by recipient). Uploads are capped at 5 accepted an hour for the one member: `documents-lifecycle.member` makes 3 and `sources.member` 2, each deletes its documents afterwards, and no other journey may make an accepted upload (a sixth is a 429).

## Chat (member)

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 1 | Enter sends; the question shows above the reply | demo, every member journey | – |
| 2 | Shift+Enter adds a line; Enter during IME composition is ignored | `chat-basics.member` (Shift+Enter; IME: U) | – |
| 3 | Send disabled when empty; composer and picker disabled while streaming; focus returns after | `chat-basics.member`, useChat.test (whitespace only) | – |
| 4 | Reply streams piece by piece | switch, guard | – |
| 5 | "Assistant is thinking…" and the tool status line | MessageList.test, useChat.test | – |
| 6 | URL becomes `/chat/<id>`; a sidebar row appears | newchat, hist | – |
| 7 | "Untitled" row replaced by the title once polled | newchat, py:test_title_trigger | – |
| 8 | Source chips grouped by file, expand to passages, deduplicated | `sources.member`, useChat.test | – |
| 9 | "Show in panel" reveals and flashes the document row (desktop) | `sources.member`, showInPanel.test | – |
| 10 | Table sort (numbers; placeholders last), Copy table, Download CSV | `rich-replies.member`, DataTable.test (formula escaping only) | – |
| 11 | Copy message; timestamp on hover | `chat-thread.member` (the hover look: L) | – |
| 12 | Remote image src removed; code highlighted | `rich-replies.member` (the highlighting look: L) | – |
| 13 | View follows the bottom while streaming; scrolling up stops it | `chat-thread.member`, MessageList.test (re-pin on resize) | – |
| 14 | New chat clears the screen and starts a separate conversation | newchat | – |
| 15 | New chat during a reply keeps that reply out of the new chat | switch | – |
| 16 | Switch via the sidebar; reload, back and forward | hist | – |
| 17 | Delete conversation: confirm or cancel; deleting the open one goes to `/chat`; error line | `chat-basics.member`, py:test_authz_conversations (error line: no journey can fail a delete) | – |
| 18 | Empty sidebar shows "No conversations yet", only once the list has loaded (never while it loads) | `chat-basics.member` | – |
| 19 | "Couldn't load this conversation." | useChat.test | – |
| 20 | 409 "reply in progress": message, refused turn removed, retry works | guard, useChat.test, chatApi.test, py:test_turn_guard | – |
| 21a | Model error mid-reply: "The reply was interrupted.", no partial, nothing stored, conversation free | `failed-reply.member`, useChat.test, chatApi.test, py:test_failed_reply, py:test_turn_guard | – |
| 21b | Connection lost mid-reply (or silent for 45 s): no error, the partial replaced by "Still answering…", then the whole reply; a message that never arrived: "Your message wasn't sent…" and the text back in the composer | useChat.test, chatApi.test, py:test_server_turn (`still-answering.member`'s offline journey is skipped: Chromium cannot cut a body already streaming) | J\* |
| 22 | Stream ends without `[DONE]`: a lost connection (row 21b); the reply finishes on the server and is stored whole, never partial | chatApi.test, useChat.test, py:test_server_turn, py:test_turn_guard (no journey: the fake model cannot drop the client's connection) | J\* |
| 22a | Coming back mid-reply (reload, switching back): the question, "Still answering…" and a disabled composer, then the whole reply; a conversation left free with the user's message last shows "The reply was interrupted." | `still-answering.member` (reload, switch), useChat.test, py:test_server_turn | – |
| 23 | Model picker has 4 options; the choice travels with the first turn | `chat-basics.member`, chatApi.test, py:test_demo_limits | – |
| 24 | A 401 signs out to `/login` (or `/` on the landing page) | chatApi.test | – |
| 25 | 20 000-character cap; composer grows on resize | ChatInput.test | – |
| 26 | Sidebar refresh keeps the latest list | ConversationsProvider.test | – |
| 27 | Error line is `role=alert` | ChatWindow.test | – |
| 67 | Each model option carries a one-line hint; the chosen option's hint shows beside the picker (a caption below it on a phone) | `model-hint.member`, ModelSelect.test | – |
| 68 | Empty composer reads "What's up?" for a member and "Ask what Hax is…" for a visitor | `new-chat.member`, `demo-landing.guest`, ChatInput.test | – |

## Demo and routing

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 28 | Landing: no greeting; blurb, 3 chips, Log in / Sign up, Privacy | `demo-landing.guest` | – |
| 79 | "Hax is evolving. More specific capabilities coming soon." below the landing's top bar, and above the guest line in the demo chat | `demo-landing.guest` | – |
| 80 | The product is named "Hax" in all copy (the drawn wordmark aside): pages, emails, both system prompts | `demo-landing.guest`, `routing.guest`, `auth-signup.guest`, `drawer.member`, `about-you.member`, Wordmark.test, py:test_email_templates, py:test_demo_prompt | – |
| 81 | The guest prompt leads a "can it do X" answer with what needs an account | py:test_demo_prompt (the instruction is present; the model's compliance is an eval case) | – |
| 29 | Demo runs in place; URL unchanged | demo, `demo-landing.guest` | – |
| 30 | Clicking a chip sends it | `demo-landing.guest` | – |
| 31 | Guest banner with links; no model picker | `demo-landing.guest` | – |
| 32 | Cap: "End of the demo" modal after 3 turns, turn removed, composer disabled | `demo-landing.guest`, useChat.test, chatApi.test, py:test_demo_limits | – |
| 33 | Demo can't start / rate-limited message | py:test_anonymous_create | J |
| 34 | Redirects: member at `/`, `/login`, `/signup` → `/chat`; guest at `/chat` → `/`; logged out → `/login` | `routing.member`, `routing.guest` | – |

## Documents

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 35 | Upload opens the panel, shows "Uploading…", adds a pending row | `documents-lifecycle.member`, chatApi.test | – |
| 36 | Pending becomes ready via a 2.5 s poll that then stops | `documents-lifecycle.member` | – |
| 37 | Failed status; tapping it shows the reason | `documents-lifecycle.member`, py:test_ingest_status, py:test_authz_documents | – |
| 38 | Order: failed, then in progress, then ready | `documents-lifecycle.member` | – |
| 39 | Upload refusals (type, 5 MB, 256 KB, hourly and daily caps) shown | `documents-panel.member` (type, 5 MB, 256 KB), chatApi.test, py:test_upload_limits (caps), py:test_authz_documents | – |
| 40 | Delete with confirm; a 404 counts as success | `documents-lifecycle.member`, chatApi.test, py:test_authz_documents | – |
| 41 | Download by clicking the filename (labelled "Download <filename>", ↓ after the name); download error message | `documents-lifecycle.member`, DocumentsPanel.test, chatApi.test, py:test_authz_documents | – |
| 42 | Empty state, count, help text, collapse; closed by default on short screens | `documents-panel.member` | – |
| 69 | An in-flight document reads "Processing…" with a spinner, a hint and aria-busy | `documents-lifecycle.member`, DocumentsPanel.test | – |

## Sidebar, drawer, phone

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 43 | Phone (<48 rem wide or ≤500 px tall): top bar with menu, logo, +; no fixed sidebar | `drawer.member` (narrow), `shell-short.member` (short landscape) | – |
| 44 | Drawer backdrop out of the Tab order; tapping it closes the drawer | Shell.test | – |
| 45 | Drawer: Escape closes; focus moves in and back; page behind inert and unscrollable; closes on navigation | `drawer.member` | – |
| 46 | Drawer closes when the window becomes desktop width | `drawer.member` | – |
| 47 | "Show in panel" on a phone opens the drawer and reveals the row | `sources.member` | – |
| 48 | Account name and email; Sign out goes to `/` | `routing.member` | – |
| 49 | Active row highlight | none | L |
| 78 | Sending a message moves its conversation to the top of the sidebar at once, while the reply streams; a refused (duplicate) send leaves the order alone | `chat-thread.member`, py:test_turn_guard | – |
| 70 | The account row is a button "Account menu" that opens About you, Privacy, Sign out (in that order); Escape or a click outside closes it; Privacy goes to `/privacy`, which names the note | `about-you.member`, AccountMenu.test | – |
| 71 | About you dialog: help line, "N / 1000" counting code points of the trimmed text; Save disabled while unchanged or over 1000; saving closes it; clearing and saving removes the note | `about-you.member`, AboutYouDialog.test, py:test_profile | – |
| 72 | Dialog errors: textarea and Save disabled until the note loads; the load-failure line; a failed save (a 422 included) keeps the dialog open with "Couldn't save. Try again."; a save in flight leaves Cancel and Escape inert | AboutYouDialog.test, py:test_profile (422) | – |
| 73 | The saved note is in the dialog after a reload | `about-you.member`, py:test_profile | – |
| 74 | Phone: the menu opens inside the drawer; the dialog fills the width less the gutter; Escape closes only the menu or the dialog; a backdrop tap does nothing and leaves focus in the dialog; saving keeps the drawer open | `about-you.member`, AboutYouDialog.test, Shell.test | – |
| 75 | The dialog and its text survive a resize across the breakpoint and a remount of the sidebar; it closes when the signed-in member changes, and a save under another member's cookie does not go out | `about-you.member` (resize), AboutYouProvider.test, Shell.test (route change: no journey can open the dialog in time) | – |
| 77 | Delete targets (conversation and document rows) are at least 44 px wide, conversation ones 44 px tall, and never overlap a neighbour; AA contrast at rest | `chat-basics.member`, `documents-panel.member` (the contrast: L) | – |

## Auth

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 50 | Login success goes to `/chat` | setup (not a spec) | – |
| 51 | Wrong-credentials message with Google hint; rate-limit message | `auth-login.guest` (rate limit: py:test_login_gate, API side) | – |
| 52 | Unverified-email message and Resend button | `auth-login.guest`, py:test_login_gate, useResend.test | – |
| 53 | `?error=` messages; `?verified` / `?reset` banners; email prefilled | `auth-login.guest` | – |
| 54 | Signup: check-your-inbox panel, resend, validation, rate limit | `auth-signup.guest` (rate limit: py:test_signup_flow) | – |
| 55 | Verify: no token → invalid view; verifies only on Confirm, then `/login?verified=1`; invalid link → resend form | `auth-signup.guest` (invalid paths), `auth-email.guest`, py:test_verify_email | – |
| 56 | Forgot password: same panel whatever the email; error messages | `auth-signup.guest`, py:test_password_reset | – |
| 57 | Reset: "Checking your link…", invalid view, validation, success → `/chat` | `auth-signup.guest` (checking, invalid view), `auth-email.guest`, py:test_password_reset (validation) | – |
| 58 | Reset succeeds but sign-in fails → `/login?reset=1` | none | U |
| 59 | Google button shows "Redirecting…" | `google-button.guest` (the logo's look: L) | – |
| 60 | Password Show/Hide | `auth-login.guest` | – |
| 61 | Resend status messages | `auth-login.guest` (sent), useResend.test, authApi.test | – |
| 76 | A write signed in by the cookie from a page that is not hax's own is refused (403); hax's own pages write as before | py:test_cross_site_writes (every member journey writes through the check; a refusal needs a sibling-subdomain page, which the e2e stack cannot serve) | – |

## Other

| # | Behaviour | Pinned by | Gap |
|---|---|---|---|
| 62 | Privacy page public; mailto link | `routing.guest` | – |
| 63 | Greeting by time of day and name; weekday; names shown as typed | greeting.test | – |
| 64 | Greeting blank until hydrated | none | U |
| 65 | Wordmark accessible name | Wordmark.test | – |
| 66 | Fonts and dark-mode look | none | L |

## Counts

Produced by `python scripts/testing_map_counts.py` from the tables above; rerun it after editing a row and paste its output here.

83 behaviours; 76 covered; 7 gaps: J 3 (J\* 2, J† 0), U 2, L 2.
