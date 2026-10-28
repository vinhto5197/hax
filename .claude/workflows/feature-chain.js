// The feature lane's build: one approved brief → implementation + blind
// tests → gate → review (fresh-eyes + a five-lens adversarial pass) → fix →
// gate → evidence → ship → gate block. Deterministic order, so no agent can
// skip a review or ship over a red gate.
//
// Launch contract: args = { id, brief, worktree, repoRoot, branch, date,
// briefSha256, ship (default true), plan: "max-5x", rulings? }, with the turn's token
// ceiling passed as the "+Nk" directive (the budget below). The controller
// creates the worktree (scripts/feature-worktree.sh) and is the only writer
// of local/features.json; this script writes only under local/briefs/<id>/.
// A chain never commits unless `ship` is true, and then only its shipper, on
// branch feat/<id> inside the worktree.
// `rulings` carries the maintainer's decisions after a stop at Fix:
// [{ match, ruling, note }]. On a review finding, `match` is a substring of its
// title and `ruling` is "fix" or "defer"; at the gate's fix, a ruling names a
// test and says to keep, rewrite or retire it. They enter through the fix
// stages only, never through
// the brief, so a resumed run (resumeFromRunId, same args otherwise) replays
// Build, the blind tests and the reviews from cache: changing the brief would
// change its hash, which every prompt carries, and rerun the whole chain.
export const meta = {
  name: 'feature-chain',
  description: 'Build one feature-lane item from its approved brief: implement + blind tests, gate, review, fix, evidence, ship, gate block',
  phases: [
    { title: 'Build', detail: 'implementer + blind test writer, in parallel' },
    { title: 'Gate', detail: 'lint, types, unit, pytest and journeys under the lock' },
    { title: 'Review', detail: 'fresh-eyes reviewer + five adversarial lenses with one-vote verifiers' },
    { title: 'Fix', detail: 'implementer applies confirmed findings' },
    { title: 'Evidence', detail: 'journeys named in the brief, screenshots at desktop and phone width' },
    { title: 'Ship', detail: 'commit, push, PR on feat/<id>' },
    { title: 'GateBlock', detail: 'gate.md and chain.json beside the brief' },
  ],
}

const ALLOWED_PLANS = new Set(['max-5x', 'max-20x'])
if (!args || !ALLOWED_PLANS.has(args.plan)) {
  log('Refusing to run: pass args.plan = "max-5x" or "max-20x" to confirm the subscription tier.')
  return { refused: true, reason: 'plan tier not acknowledged (args.plan)' }
}
for (const k of ['id', 'brief', 'worktree', 'repoRoot', 'branch', 'date', 'briefSha256']) {
  if (!args[k]) { log(`Refusing to run: args.${k} is missing.`); return { refused: true, reason: `args.${k} missing` } }
}
const ship = args.ship !== false
const out = `${args.repoRoot}/local/briefs/${args.id}`

// The hash is in every prompt so an amended brief invalidates a resumed run's
// cached prefix instead of replaying a stale result.
const BASE = `You are one stage of the feature chain for feature "${args.id}".
The approved brief is ${args.brief} (sha256 ${args.briefSha256}): read it first; it is the spec, and its Interface section is frozen.
Work ONLY inside the worktree ${args.worktree} (cd there for every command; it is a git worktree on branch ${args.branch}). Never touch ${args.repoRoot}'s own working tree. Never read any .env* file except the committed templates. Never run git commit, push, stash, reset or checkout unless your stage says you are the shipper. Never kill a process by pattern (pkill -f, killall): other worktrees and the maintainer run the same servers; stop only a process you started, by its pid. \`make test\` and \`make e2e\` take a shared lock and may make you wait; wait.
Outputs for the maintainer go under ${out}/ only (it is reachable from the worktree as local/briefs/${args.id}/).
Your final message is data for the chain, not prose for a human: answer the schema exactly.`

const BUILD_SCHEMA = { type: 'object', required: ['status', 'files', 'calls'], properties: {
  status: { type: 'string', enum: ['done', 'blocked'] },
  blockedOn: { type: 'string' },
  files: { type: 'array', items: { type: 'string' } },
  calls: { type: 'array', items: { type: 'string' } },
  notes: { type: 'string' } } }
const TESTS_SCHEMA = { type: 'object', required: ['tests', 'files'], properties: {
  tests: { type: 'array', items: { type: 'string' } },
  files: { type: 'array', items: { type: 'string' } },
  inexpressible: { type: 'array', items: { type: 'string' } },
  assumptions: { type: 'array', items: { type: 'string' } } } }
const GATE_SCHEMA = { type: 'object', required: ['passed', 'results'], properties: {
  passed: { type: 'boolean' },
  results: { type: 'array', items: { type: 'object', required: ['check', 'passed', 'tail'], properties: {
    check: { type: 'string' }, passed: { type: 'boolean' }, tail: { type: 'string' } } } } } }
const FINDINGS_SCHEMA = { type: 'object', required: ['findings'], properties: {
  findings: { type: 'array', items: { type: 'object', required: ['title', 'severity', 'file', 'line', 'claim', 'scenario'], properties: {
    title: { type: 'string' }, severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    file: { type: 'string' }, line: { type: 'integer' }, claim: { type: 'string' }, scenario: { type: 'string' },
    needsDecision: { type: 'boolean' } } } } } }
const VERDICT_SCHEMA = { type: 'object', required: ['confirmed', 'reason'], properties: {
  confirmed: { type: 'boolean' }, reason: { type: 'string' } } }
const EVIDENCE_SCHEMA = { type: 'object', required: ['journeys', 'screenshots', 'passed'], properties: {
  passed: { type: 'boolean' },
  journeys: { type: 'array', items: { type: 'object', required: ['name', 'passed'], properties: { name: { type: 'string' }, passed: { type: 'boolean' } } } },
  screenshots: { type: 'array', items: { type: 'string' } },
  notes: { type: 'string' } } }
const SHIP_SCHEMA = { type: 'object', required: ['shipped'], properties: {
  shipped: { type: 'boolean' }, pr: { type: 'string' }, commit: { type: 'string' }, reason: { type: 'string' } } }

const phases = []
let state = { stoppedAt: null, blockedOn: null }
let spentAt = budget.spent()
function record(name, outcome) {
  const now = budget.spent()
  phases.push({ name, outputTokens: budget.total ? now - spentAt : null, outcome })
  spentAt = now
}
// A budget stop is recorded like any other stop, so the gate block says why.
function stop(name) {
  if (budget.total && budget.remaining() < 60_000) {
    log(`Budget nearly exhausted before ${name}; stopping without shipping.`)
    state.stoppedAt = name; state.blockedOn = 'token ceiling reached'
    return true
  }
  return false
}
// A solitary agent that throws (terminal API error, ceiling hit mid-call)
// must not end the script before the gate block is written.
async function tryAgent(prompt, opts) {
  try { return await agent(prompt, opts) } catch (e) { log(`${opts.label}: ${e && e.message ? e.message : e}`); return null }
}

const GATE_PROMPT = `${BASE}
## Stage: gate
Run, in this order, and read every output: \`.venv/bin/ruff check .\`; \`.venv/bin/ruff format --check .\`; \`cd apps/web && npx tsc --noEmit && npx eslint . && npx vitest run\`; \`make test\`; \`make e2e\`. The last two take a shared lock (local/.gate.lock) and may wait for another chain; wait, do not skip. A check you did not run is reported as not passed. Report each check with its last five lines.`

async function gate(label) {
  const r = await tryAgent(GATE_PROMPT, { label, phase: 'Gate', schema: GATE_SCHEMA, agentType: 'general-purpose', effort: 'low' })
  return r || { passed: false, results: [{ check: 'gate agent', passed: false, tail: 'agent returned nothing' }] }
}

let build = null, tests = null, gate1 = null, gate2 = null, review = null, fix = null, gate3 = null, evidence = null, shipped = null

// Build: implementer and blind test writer in parallel, both against the frozen Interface.
phase('Build')
const built = await parallel([
  () => agent(`${BASE}
## Stage: implementer
Implement the brief exactly: its UX, Backend, Infra and Interface sections. Write no tests: a separate agent writes them from the Interface at the same time, so never bend the interface to make a test pass. The roadblock line: any choice that would appear in the brief's UX, Backend or Infra sections, or that changes user-visible behaviour, a public interface or a test expectation, is not yours to make — stop and return status "blocked" with blockedOn naming the decision; smaller choices (a helper's name or placement, wording within the brief's copy) you make and list under calls. Run the checks you can (ruff, tsc, eslint, the unit tests you did not write may fail until the test writer is done — that is expected). Return the files you touched and your calls.`,
    { label: 'build:implement', phase: 'Build', schema: BUILD_SCHEMA, agentType: 'implementer' }),
  () => agent(`${BASE}
## Stage: blind test writer
Write the tests the brief's Verification plan names, from the brief's Interface and Verification plan sections ONLY. Do not open the implementation files beyond their exported names, and do not open an existing test of the same unit beyond its fixtures and mocking style (read ${args.repoRoot}/.claude/skills/blind-tests/SKILL.md for the rules). Name every test as the behaviour it checks. Create or extend exactly the test files the brief names. Run only those files; failures from an implementation still in progress are expected: report them, do not work around them. Return every test name, anything you could not express, and every assumption about the interface.`,
    { label: 'build:tests', phase: 'Build', schema: TESTS_SCHEMA, agentType: 'general-purpose' }),
])
build = built[0]; tests = built[1]
if (!build) { state.stoppedAt = 'Build'; state.blockedOn = 'implementer returned nothing'; record('Build', 'failed') }
else if (build.status === 'blocked') { state.stoppedAt = 'Build'; state.blockedOn = build.blockedOn || 'unspecified'; record('Build', 'blocked') }
else record('Build', 'done')

// Gate, with one fix attempt on red.
if (!state.stoppedAt && !stop('Gate')) {
  gate1 = await gate('gate:1')
  if (!gate1.passed) {
    phase('Fix')
    const f = await tryAgent(`${BASE}
## Stage: fix (gate red)
The gate failed. Failures:\n${JSON.stringify(gate1.results.filter(r => !r.passed), null, 1)}\nFix the code, never the tests' intent (a test that contradicts the brief is a wrong behaviour line: report it as blocked instead of changing it). Same roadblock line as the implementer.${(args.rulings || []).length ? `\nThe maintainer's rulings, which outrank the brief for exactly the tests or findings they name (a test named here may be rewritten or retired as its ruling says; name each such change in your calls):\n${JSON.stringify(args.rulings, null, 1)}` : ''} Return status, files, calls.`,
      { label: 'fix:gate', phase: 'Fix', schema: BUILD_SCHEMA, agentType: 'implementer' })
    if (!f || f.status === 'blocked') { state.stoppedAt = 'Fix'; state.blockedOn = f ? f.blockedOn : 'fixer returned nothing'; record('Gate', 'failed') }
    else { gate2 = await gate('gate:2'); record('Gate', gate2.passed ? 'done after fix' : 'failed'); if (!gate2.passed) state.stoppedAt = 'Gate' }
  } else record('Gate', 'done')
}

// Review: a fresh-eyes reviewer plus five adversarial lenses, each finding verified by one skeptic.
const LENSES = [
  { key: 'correctness', prompt: 'Wrong outputs, unhandled states, off-by-one, broken invariants.' },
  { key: 'concurrency', prompt: 'Races, lost updates, check-then-act, cancellation and disconnect paths, pooled connections held across awaits.' },
  { key: 'boundaries', prompt: 'The trust boundaries this diff touches: ownership checks, identity propagation, anything user-controlled reaching a query, a log or a prompt.' },
  { key: 'tests-claim-vs-check', prompt: 'Tests whose names promise more than their assertions check; tests that pass regardless of the code; behaviours in the brief with no test.' },
  { key: 'brief-conformance', prompt: 'Every section of the brief against the diff: a deviation the implementer did not report, an Interface bullet not implemented as written, copy that differs.' },
]
if (!state.stoppedAt && !stop('Review')) {
  phase('Review')
  const REVIEW_BASE = `${BASE}\nThe change is \`git diff origin/main\` inside the worktree (plus untracked files; \`git status --short\`). Read only the files the diff touches and their direct callers. Report ONLY findings you can substantiate with file:line and a concrete scenario; an empty list is a valid result. Severity: critical = exposure or corruption reachable today; high = same with an uncommon precondition; medium = a defense gap with a realistic trigger; low = hygiene. Mark needsDecision when fixing it would change what the brief specifies. Accessibility (ARIA, screen readers, keyboard-only navigation, focus management, contrast) is out of scope for a first implementation by the maintainer's rule: never report it as a finding; the controller queues such points separately.`
  const [fresh, ...lensResults] = await parallel([
    () => agent(`${REVIEW_BASE}\n## Stage: fresh-eyes reviewer\nWalk the change caller-first. Real defects only.`,
      { label: 'review:fresh-eyes', phase: 'Review', schema: FINDINGS_SCHEMA, agentType: 'general-purpose' }),
    ...LENSES.map(l => () => agent(`${REVIEW_BASE}\n## Stage: adversarial finder, lens "${l.key}"\n${l.prompt}`,
      { label: `review:find:${l.key}`, phase: 'Review', schema: FINDINGS_SCHEMA, agentType: 'general-purpose' })),
  ])
  // A reviewer that returned nothing did not review; the chain fails closed
  // rather than reading silence as "no findings".
  const missing = []
  if (!fresh) missing.push('fresh-eyes')
  lensResults.forEach((r, i) => { if (!r) missing.push(LENSES[i].key) })
  // Findings keep their source so the gate block can tell fresh-eyes from the lenses.
  const tagged = []
  if (fresh) tagged.push(...fresh.findings.map(f => ({ ...f, source: 'fresh-eyes' })))
  lensResults.forEach((r, i) => { if (r) tagged.push(...r.findings.map(f => ({ ...f, source: LENSES[i].key }))) })
  if (missing.length) { state.stoppedAt = 'Review'; state.blockedOn = `reviewer did not run: ${missing.join(', ')}` }
  // Bounded verification keeps the chain's cost finite without a token directive.
  const MAX_VERIFY = 12
  const order = { critical: 0, high: 1, medium: 2, low: 3 }
  tagged.sort((a, b) => order[a.severity] - order[b.severity])
  const raw = tagged.slice(0, MAX_VERIFY)
  const unverified = tagged.slice(MAX_VERIFY)
  if (unverified.length) log(`Verifying the ${MAX_VERIFY} most severe of ${tagged.length} findings; ${unverified.length} listed unverified.`)
  const verified = await pipeline(raw, (f, _, i) =>
    agent(`${REVIEW_BASE}\n## Stage: skeptic for finding #${i}\n${JSON.stringify(f, null, 1)}\nTry to refute it: read ONLY the files it cites (and their direct callers if the scenario depends on them). Confirm only if the scenario really produces the wrong outcome in this code.`,
      { label: `review:verify:#${i}`, phase: 'Review', schema: VERDICT_SCHEMA, agentType: 'general-purpose', effort: 'medium' })
      .then(v => ({ ...f, verdict: v })))
  const confirmed = verified.filter(Boolean).filter(v => v.verdict && v.verdict.confirmed)
  const refuted = verified.filter(Boolean).filter(v => v.verdict && !v.verdict.confirmed)
  review = { raw: tagged.length, confirmed, refuted: refuted.map(r => ({ title: r.title, source: r.source, reason: r.verdict.reason })), unverified, deferred: [], missing }
  record('Review', missing.length ? `incomplete: ${missing.join(', ')} did not run` : `${confirmed.length} confirmed / ${refuted.length} refuted of ${tagged.length}`)
}

// Fix: apply confirmed findings. A finding that needs a decision blocks the chain
// only above low severity; a low one is left for the maintainer as "Consider".
if (!state.stoppedAt && review && review.confirmed.length && !stop('Fix')) {
  phase('Fix')
  const rulingFor = f => (args.rulings || []).find(r => r.match && f.title.includes(r.match))
  const ruled = review.confirmed.map(f => ({ ...f, ruling: rulingFor(f) }))
  const blocking = ruled.filter(f => f.needsDecision && f.severity !== 'low' && !f.ruling)
  review.deferred = ruled.filter(f => f.ruling ? f.ruling.ruling === 'defer' : (f.needsDecision && f.severity === 'low'))
  const fixable = ruled.filter(f => f.ruling ? f.ruling.ruling === 'fix' : !f.needsDecision)
  if (blocking.length) {
    state.stoppedAt = 'Fix'; state.blockedOn = `review findings need a decision: ${blocking.map(d => d.title).join('; ')}`
    record('Fix', 'blocked')
  } else if (!fixable.length) {
    record('Fix', `nothing to fix; ${review.deferred.length} low finding(s) left for the maintainer`)
  } else {
    fix = await tryAgent(`${BASE}
## Stage: fix (review findings)
Apply these confirmed findings, each with the smallest change that removes the defect; add or adjust a test where the brief's Verification plan names one, or where the test pins behaviour the brief's Backend, UX or Interface sections already specify (a missing test for specified behaviour is a gap to close, not a decision), or where the finding carries a maintainer's ruling (its \`ruling.note\` says what is allowed, and it outranks the brief's test list for that finding only):\n${JSON.stringify(fixable.map(f => ({ title: f.title, file: f.file, line: f.line, claim: f.claim, scenario: f.scenario, ruling: f.ruling || undefined })), null, 1)}\nSame roadblock line as the implementer. Return status, files, calls.`,
      { label: 'fix:review', phase: 'Fix', schema: BUILD_SCHEMA, agentType: 'implementer' })
    if (!fix || fix.status === 'blocked') { state.stoppedAt = 'Fix'; state.blockedOn = fix ? fix.blockedOn : 'fixer returned nothing'; record('Fix', 'blocked') }
    else {
      record('Fix', 'done')
      if (!stop('Gate')) { gate3 = await gate('gate:3'); record('Gate', gate3.passed ? 'done after review fixes' : 'failed'); if (!gate3.passed) state.stoppedAt = 'Gate' }
    }
  }
}

// Evidence: the journeys the brief names, screenshots at desktop and phone width.
if (!state.stoppedAt && !stop('Evidence')) {
  phase('Evidence')
  evidence = await tryAgent(`${BASE}
## Stage: evidence
Run the journeys the brief's Verification plan names (\`make e2e ARGS="<spec file names>"\`; the lock may make you wait). Then capture the screens the plan names at 1280×800 and 390×844 with a throwaway Playwright spec (as apps/web/e2e/*.member.spec.ts, deleted afterwards) that writes PNGs to local/briefs/${args.id}/evidence/ (create it). Return each journey's name and result and every screenshot path; passed is true only if every named journey passed.`,
    { label: 'evidence', phase: 'Evidence', schema: EVIDENCE_SCHEMA, agentType: 'general-purpose' })
  if (!evidence || !evidence.passed) { state.stoppedAt = 'Evidence'; record('Evidence', 'failed') } else record('Evidence', `${evidence.journeys.length} journeys, ${evidence.screenshots.length} screenshots`)
}

// Ship: commit, push, PR — only the shipper, only on the feature branch, only inside the worktree.
if (!state.stoppedAt && ship && !stop('Ship')) {
  phase('Ship')
  shipped = await tryAgent(`${BASE}
## Stage: shipper
You are the one stage allowed to use git write commands, under these refusals: if \`git branch --show-current\` is not "${args.branch}", or \`pwd\` is not ${args.worktree}, return shipped=false with the reason and do nothing else. Never force-push, never touch main, never merge.
Otherwise: \`git add -A\` (local/ is gitignored and must not appear in the diff; verify with \`git status --short\`), commit with a conventional message whose subject is the brief's title line and whose body is two sentences from the brief's Goal, push with \`git push -u origin ${args.branch}\`, then open a PR against main with \`gh pr create\` whose title is the brief's title and whose body follows ${args.repoRoot}/.claude/skills/gate-block/pr-body.md exactly (public parts only: never review findings, cost or "new to you"). Return the PR URL and the commit sha.`,
    { label: 'ship', phase: 'Ship', schema: SHIP_SCHEMA, agentType: 'general-purpose' })
  record('Ship', shipped && shipped.shipped ? 'shipped' : `not shipped: ${shipped ? shipped.reason : 'shipper returned nothing'}`)
} else if (!state.stoppedAt && !ship) {
  record('Ship', 'skipped (ship=false)')
}

// Gate block: the maintainer's read, plus the chain's own record.
phase('GateBlock')
const summary = {
  id: args.id, date: args.date, brief: args.brief, briefSha256: args.briefSha256 || null, branch: args.branch, worktree: args.worktree,
  stoppedAt: state.stoppedAt, blockedOn: state.blockedOn,
  build, tests, gates: [gate1, gate2, gate3].filter(Boolean), review, fix, evidence, shipped, phases, ship,
}
const gateBlock = await tryAgent(`${BASE}
## Stage: gate block
Write ${out}/gate.md following ${args.repoRoot}/.claude/skills/gate-block/feature.md section for section, from this chain record (JSON) and the diff in the worktree; leave "New to you" and "Cost" as the headings with "(controller fills)" under them. Conformance: one line per brief section; a deviation is only what the implementer reported under calls or blockedOn — anything else that differs from the brief is a chain bug, written as "CHAIN BUG: …". Reviews: findings whose source is "fresh-eyes" are the fresh-eyes reviewer's, the rest the adversarial lenses'; review.deferred are open items triaged "Consider"; review.unverified are listed as unverified. Merge?: "ready <PR URL>" when shipped, else "UNSHIPPED: <stoppedAt — blockedOn or the failed check>". Then write ${out}/chain.json with exactly this record, pretty-printed. Return the gate.md text.
Record:\n${JSON.stringify(summary, null, 1)}`,
  { label: 'gate-block', phase: 'GateBlock', agentType: 'general-purpose', effort: 'low' })
record('GateBlock', gateBlock ? 'written' : 'failed')

return { id: args.id, shipped: !!(shipped && shipped.shipped), pr: shipped ? shipped.pr || null : null, branch: args.branch, stoppedAt: state.stoppedAt, blockedOn: state.blockedOn, phases }
