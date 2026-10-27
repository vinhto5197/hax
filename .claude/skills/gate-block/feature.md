# <id> — gate block

## Conformance
One line per brief section (Goal, UX, Backend, Infra, Interface, Verification plan): `as specified`, or `DEVIATION: <what differs>` with the stop-and-report that approved it. A deviation without an approved stop-and-report is a chain bug, reported as such.

## Calls made during build
The implementer's own choices below the roadblock line (names, placement, wording within the brief's copy), one line each.

## Evidence
Journeys run, by name, with pass/fail. Screenshot paths (desktop and phone, or simulator). Test counts per suite. CI run URL and state. No completion claim without fresh evidence: CI green is necessary, not sufficient.

## Reviews
Fresh-eyes: findings fixed, findings open. Adversarial review: confirmed / refuted / unverified counts; each open item triaged as Act, Consider, Noted or Dismissed with one line of reason.

## Test names
Every new or changed test, by name, grouped by file; any test that pins a behaviour the controller is unsure is intended is flagged.

## Flags
Anything the maintainer might decide differently; tests whose meaning changed; follow-ups recorded in the backlog.

## New to you
Concepts in this change not yet on the front-loading ledger, two lines each, with an offer to go deeper. "Nothing new" when none.

## Cost
Tokens by phase (build, tests, reviews, fixes) and total, wall time, against the brief's estimate.

## Your review
What only the maintainer can judge, as a checklist of a few minutes (skill gate-block, "Your review, on every Show and Ask"): one line on what the machines already proved; then, numbered, what to look at (screenshot paths, a screen to try), the judgment calls to accept or refuse (copy, behaviour choices, deferrals, trade-offs; one sentence each), code worth raising (`file:line` and why) or "no code to read", and the word that ends the review. Written by the chain from its own record; the controller completes it after its own look at the screens, and the chat hand-off leads with it.

## Merge?
`ready` with the PR URL, or `UNSHIPPED` with the reason (ceiling reached, blocked on a decision, a gate red).
