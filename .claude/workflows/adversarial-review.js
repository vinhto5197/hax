export const meta = {
  name: 'adversarial-review',
  description: 'Diff-scoped adversarial review: lenses find -> dedup -> severity-tiered adversarial verify -> synthesize; Opus tiers, Fable only where it counts',
  whenToUse: 'After a slice or fix lands: Workflow({name: "adversarial-review", args: {range, diffPath, repo, date, context, extraLenses?}}) with a +Nk ceiling (3M slice / 7M whole-project). Show the cost preview and get "go" first.',
  phases: [
    { title: 'Find', detail: 'one agent per lens; Opus, Fable on the sensitive lenses' },
    { title: 'Dedup', detail: 'one Fable agent merges overlapping findings' },
    { title: 'Verify', detail: 'Opus skeptics: 3 votes high/medium, 1 vote low; cited files only' },
    { title: 'Synthesize', detail: 'one Fable agent writes the ranked report' },
  ],
}

// PLAN REQUIREMENT — READ BEFORE RUNNING. This workflow spawns ~60 agents and
// consumes roughly 25% of a Claude Max 5x ($100/mo) 5-hour usage window per
// diff-scoped run (~2.5M Opus + ~0.2M Fable tokens), more for a whole-project
// range. On Pro or Max 1x it will exhaust the window mid-run and die with
// partial coverage. It refuses to start unless the launcher acknowledges the
// tier explicitly: args.plan must equal "max-5x" (or "max-20x").
//
// Tiers decided 2026-09-08 (see memory: ar-config-and-calibration). Fable ≈ 4-6x
// Opus on the usage meter, so it is confined to two singleton agents and the
// lenses where a missed finding is most expensive.
const ALLOWED_PLANS = new Set(['max-5x', 'max-20x'])
if (!ALLOWED_PLANS.has(args.plan)) {
  log(`Refusing to run: pass args.plan = "max-5x" or "max-20x" to confirm your subscription tier. ` +
      `This review needs ~25% of a Max 5x usage window; lower tiers exhaust mid-run.`)
  return { refused: true, reason: 'plan tier not acknowledged (args.plan)' }
}
const FINDER_MODEL = 'opus'
const VERIFY_MODEL = 'opus'
const HEAVY_MODEL = 'fable'
const FABLE_LENSES = new Set(['authz', 'auth-crypto', 'concurrency'])

const { range, diffPath, repo, date, context = '', extraLenses = [] } = args

const BASE = `
You are reviewing changes in the repo at ${repo} (git range ${range}). A full diff is at ${diffPath}; you may run read-only git/grep and read repo files. NEVER read .env. Modify nothing. Start no services. Run a focused test only when a concrete doubt needs it.

${context}
`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          file: { type: 'string' },
          line: { type: 'integer' },
          claim: { type: 'string' },
          evidence: { type: 'string' },
          scenario: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['title', 'severity', 'file', 'line', 'claim', 'evidence', 'scenario', 'fix'],
      },
    },
  },
  required: ['findings'],
}

const LENSES = [
  { key: 'authz', prompt: 'Authorization / BOLA lens: trace every caller-controlled identifier to the query that consumes it; is the caller\'s identity bound there in every case? Existence leaks via status/body/timing?' },
  { key: 'injection', prompt: 'Injection lens: SQL (interpolation vs bound params), prompt injection through any model-fillable field or document content, command/path injection, log injection.' },
  { key: 'auth-crypto', prompt: 'Auth / crypto / session lens: token verification, claim confusion, revocation windows, secret handling, cookie vs bearer precedence, CSRF surface of cookie-authenticated state changes.' },
  { key: 'concurrency', prompt: 'Concurrency / race / isolation lens: TOCTOU between check and write, per-request state leaking across requests/tasks/pooled connections, worker-process reuse, cancellation and finally paths.' },
  { key: 'data-migrations', prompt: 'Data integrity + migration lens: migration correctness and reversibility, constraints, cascades, backfills, what breaks on a database that is not dev.' },
  { key: 'ops-deploy', prompt: 'Operations / deploy lens: env contracts and fallbacks, role/privilege drift between environments, deploy ordering, CI parity, anything that only fails in prod.' },
  { key: 'scale', prompt: 'Production-scale lens (10k users): hot-path cost, N+1s, indexes vs predicates, connection-pool holds, per-request round-trips; concrete and measurable only.' },
  { key: 'tests', prompt: 'Test-integrity lens: for each new test ask what product change turns it red; tautologies, seed coincidences, fixtures masking bleed, layers answering for each other.' },
  { key: 'errors-leaks', prompt: 'Error-handling / leak lens: raw driver/SDK text or user content reaching user-visible fields or logs, swallowed exceptions, fail-open vs fail-closed drift.' },
  { key: 'hygiene-docs', prompt: 'Public-repo hygiene + doc accuracy lens: private strategy or internal references in committed files; every ADR/README/CLAUDE.md claim checked against code; comment-policy drift.' },
  ...extraLenses,
]

function stop(phaseName) {
  if (budget.total && budget.remaining() < 60_000) {
    log(`Budget ceiling reached before ${phaseName}; stopping with partial coverage.`)
    return true
  }
  return false
}

phase('Find')
const perLens = await parallel(LENSES.map(l => () => stop('Find') ? null :
  agent(`${BASE}\n## Your lens: ${l.key}\n${l.prompt}\n\nReport ONLY findings you can substantiate with file:line evidence and a concrete scenario. Fewer, sharper findings beat volume. Severity: critical = exposure/corruption/bypass reachable today; high = same with an uncommon precondition, or prod-outage class; medium = defense gap with a realistic future trigger; low = hygiene/quality. An empty list is a valid result.`,
    { label: `find:${l.key}`, phase: 'Find', schema: FINDINGS_SCHEMA, model: FABLE_LENSES.has(l.key) ? HEAVY_MODEL : FINDER_MODEL })))
const raw = perLens.filter(Boolean).flatMap((r, i) => r.findings.map(f => ({ ...f, lens: LENSES[i].key })))
log(`Find: ${raw.length} raw findings from ${perLens.filter(Boolean).length}/${LENSES.length} lenses`)

phase('Dedup')
const DEDUP_SCHEMA = {
  type: 'object',
  properties: {
    merged: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' }, severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          file: { type: 'string' }, line: { type: 'integer' }, claim: { type: 'string' }, evidence: { type: 'string' },
          scenario: { type: 'string' }, fix: { type: 'string' }, lenses: { type: 'array', items: { type: 'string' } },
        },
        required: ['title', 'severity', 'file', 'line', 'claim', 'evidence', 'scenario', 'fix', 'lenses'],
      },
    },
  },
  required: ['merged'],
}
let merged = []
if (raw.length && !stop('Dedup')) {
  const d = await agent(`Merge overlapping findings (same root defect) into one each, keeping the strongest evidence, the union of lenses, and the highest defensible severity. Drop nothing distinct; judge nothing (a later stage does).\n\n${raw.map((f, i) => `${i}: ${JSON.stringify(f)}`).join('\n')}`,
    { label: 'dedup', phase: 'Dedup', schema: DEDUP_SCHEMA, model: HEAVY_MODEL })
  merged = d ? d.merged : raw.map(f => ({ ...f, lenses: [f.lens] }))
}
log(`Dedup: ${raw.length} -> ${merged.length}`)

phase('Verify')
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    refuted: { type: 'boolean' }, confidence: { type: 'number', minimum: 0, maximum: 1 },
    reasoning: { type: 'string' }, severity_adjustment: { type: 'string', enum: ['keep', 'raise', 'lower'] },
  },
  required: ['refuted', 'confidence', 'reasoning', 'severity_adjustment'],
}
const VOTERS = [
  { key: 'repro', instr: 'REPRODUCTION: walk the scenario step by step against the real code; refute if any step cannot happen.' },
  { key: 'impact', instr: 'IMPACT: assume the mechanism is real; refute if the consequence is already mitigated by another layer or is an accepted/known item.' },
  { key: 'skeptic', instr: 'SKEPTIC: find the strongest reason this is wrong or overstated; default refuted=true below confidence 0.8.' },
]
const votersFor = f => (f.severity === 'low' ? [VOTERS[2]] : VOTERS)
const verified = await pipeline(merged,
  (f, _i, idx) => stop('Verify') ? { ...f, votes: [], survived: null } :
    parallel(votersFor(f).map(v => () =>
      agent(`${BASE}\n## Finding #${idx}\n${JSON.stringify(f, null, 2)}\n\n## ${v.instr}\n\nRead ONLY the files this finding cites (plus their direct callers if the scenario depends on them) — do not read the whole diff. Cite file:line for the decisive evidence.`,
        { label: `verify:${v.key}:#${idx}`, phase: 'Verify', schema: VERDICT_SCHEMA, model: VERIFY_MODEL, effort: 'medium' })))
      .then(votes => {
        const vs = votes.filter(Boolean)
        const refutes = vs.filter(x => x.refuted).length
        return { ...f, votes: vs, survived: vs.length === 0 ? null : refutes * 2 < vs.length }
      }))
const confirmed = verified.filter(Boolean).filter(v => v.survived === true)
const refuted = verified.filter(Boolean).filter(v => v.survived === false)
const unverified = verified.filter(Boolean).filter(v => v.survived === null)
log(`Verify: ${confirmed.length} confirmed, ${refuted.length} refuted, ${unverified.length} unverified`)

phase('Synthesize')
const report = stop('Synthesize') ? null : await agent(`${BASE}\nWrite the adversarial-review report (date ${date}) in Markdown, tightly, file:line everywhere, no invented findings:\n1. Five-line executive summary (verdict, confirmed counts by severity, the single most important action).\n2. CONFIRMED, ranked by severity then confidence: title, severity, file:line, claim, decisive evidence, scenario, fix, suggested home (fix-now / next milestone / cleanup / v1) with a one-line reason.\n3. REFUTED, one line each: title — why (so a wrong refutation can be spotted).\n4. UNVERIFIED (budget stopped before verification), one line each.\n5. Lens coverage table: lens -> raw -> confirmed -> what it satisfied itself about.\n6. Residual risks needing a live probe / load test / prod.\n\nCONFIRMED:\n${JSON.stringify(confirmed, null, 1)}\n\nREFUTED:\n${JSON.stringify(refuted.map(r => ({ title: r.title, file: r.file, line: r.line, claim: r.claim, votes: r.votes })), null, 1)}\n\nUNVERIFIED:\n${JSON.stringify(unverified.map(u => ({ title: u.title, severity: u.severity, file: u.file, line: u.line })), null, 1)}\n\nLENS RAW COUNTS:\n${JSON.stringify(LENSES.map((l, i) => ({ lens: l.key, raw: perLens[i] ? perLens[i].findings.length : null })))}`,
  { label: 'synthesize', phase: 'Synthesize', model: HEAVY_MODEL, effort: 'high' })

return { report, confirmed: confirmed.length, refuted: refuted.length, unverified: unverified.length, raw: raw.length, lensesRun: perLens.filter(Boolean).length }
