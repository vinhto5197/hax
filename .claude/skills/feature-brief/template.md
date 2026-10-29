# <id> — <title>

## Goal
One line: what a user can do afterwards that they cannot do now.
Then three answers, one line each: who asked for this and how we know; what happens if it is never built; the narrowest version that still answers the demand.

## Slices
"One slice" when the reviewed lines (production code, test infrastructure, CI, infra, docs; not test files or generated types) are about 300 or fewer. Otherwise one line per slice, in build order: what a user or developer has after it merges, the files it changes, its reviewed-line estimate, and the path of its brief. Each slice merges and deploys on its own.

## UX
Where it lives in the app (screen, route, entry point); every screen and state (empty, loading, error, done); copy, verbatim; a mockup or screenshot path whenever the change is visual.

## Backend
Models and migrations (columns, constraints, defaults); API (routes, request and response shapes, status codes); mechanics: the concurrency or consistency choice, named, and which store owns the guard.

## Infra
Anything outside the app: env variables, compose services, Terraform, CI jobs, the deploy. "None" when none.

## Interface
The public surface frozen for the build, as bullets: function signatures, routes with response shapes, component props, test selectors. The blind test writer and the implementer both code against this list and nothing else; the implementer never bends it to make a test pass.

## Calls made
One line per decision the orchestrator made — the rejected alternative after a dash. The design reviewer's verdict is recorded here, with what changed because of it.

## Minimal design
The smallest design that meets the Goal, in a few lines, beside the recommended one above, and the reason to prefer the recommended one; or "the minimal design is the recommended one".

## Open decisions
Decisions only the maintainer can make, each with its options and a recommendation. Ideally empty.

## Verification plan
Journeys by name for every behaviour a browser can observe; unit tests by name for what only a test can stage (a race, an ordering, a mocked boundary); screenshots to capture (which screens, desktop and phone); the CI checks; what counts as evidence of done. A behaviour with neither is named here with the reason.

## Size and cost
Estimated changed lines, per file, split into reviewed lines (the slice limit counts these) and test lines; tokens by phase (build, tests, reviews, fixes); wall time; the adversarial-review ceiling that approval pre-authorizes.

## New to you
Concepts in this brief not yet on the front-loading ledger, two lines each, with an offer to go deeper. "Nothing new" when none.

<!-- forcing questions after gstack's office-hours (MIT); PR shape after pstack (MIT) -->
