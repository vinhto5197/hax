// The feature chain's control flow, driven by stubbed agents through the
// runtime harness: which stages run, where a run stops, and what reaches the
// gate block. Run with `node --test tests/workflows/`.

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

import { runWorkflow, stubAgent, defaultArgs, extractRecord, PR_URL, REQUIRED_CHECKS } from './harness.mjs'

const SCRIPT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../.claude/workflows/feature-chain.js')

async function run(overrides = {}, argsOver = {}) {
  const args = defaultArgs(argsOver)
  const out = await runWorkflow(SCRIPT, { args, agent: stubAgent(args, overrides) })
  return { ...out, args }
}

const labels = (calls) => calls.map((c) => c.label)
const called = (calls, pred) => calls.filter((c) => pred(c.label ?? ''))
const startsWith = (p) => (l) => l.startsWith(p)
const text = (v) => (typeof v === 'string' ? v : JSON.stringify(v ?? ''))

function nonEmpty(v) {
  if (v == null) return false
  if (Array.isArray(v)) return v.length > 0
  if (typeof v === 'string') return v.trim().length > 0
  return Object.keys(v).length > 0
}

function gateBlockCalls(calls) {
  return called(calls, (l) => l === 'gate-block')
}

function record(calls) {
  const gb = gateBlockCalls(calls)
  assert.ok(gb.length >= 1, 'gate-block was called')
  return extractRecord(gb[gb.length - 1].prompt)
}

// Titles are unique and never a substring of one another.
function finding(n, severity, extra = {}) {
  const id = String(n).padStart(2, '0')
  return {
    title: `Finding Q${id}x ${severity}`,
    severity,
    file: `packages/core/f${id}.py`,
    line: 10 + n,
    claim: `claim ${id}`,
    scenario: `scenario ${id}`,
    ...extra,
  }
}

// The verifier stub: `verdicts` maps a title to a result (or a function that
// may throw); a title not listed is refuted.
function verifier(verdicts) {
  return (prompt) => {
    for (const [title, v] of Object.entries(verdicts)) {
      if (prompt.includes(title)) return typeof v === 'function' ? v() : v
    }
    return { confirmed: false, reason: 'refuted' }
  }
}

const CONFIRMED = { confirmed: true, reason: 'reproduced' }

function verifyCallFor(calls, title) {
  return called(calls, startsWith('review:verify:#')).filter((c) => c.prompt.includes(title))
}

function assertNoShip(out) {
  assert.equal(out.result.shipped, false)
  assert.equal(called(out.calls, (l) => l === 'ship').length, 0, 'ship was not called')
}

// Each stopping scenario, shared with behaviour 30.
const STOPS = {
  '3 brief digest differs': () => run({ 'precheck:brief': { sha256: 'b'.repeat(64) } }),
  '4 precheck null': () => run({ 'precheck:brief': null }),
  '4 precheck throws': () => run({ 'precheck:brief': () => { throw new Error('died') } }),
  '5 test writer null': () => run({ 'build:tests': null }),
  '5 test writer throws': () => run({ 'build:tests': () => { throw new Error('died') } }),
  '6 test writer empty': () => run({ 'build:tests': { tests: [], files: [] } }),
  '9 gate 2 red': () => {
    const red = { passed: false, results: REQUIRED_CHECKS.map((check) => ({ check, passed: check !== 'make test', tail: 'x' })) }
    return run({ 'gate:1': red, 'gate:2': red })
  },
  '10 verifier null on high': () => {
    const f = finding(1, 'high')
    return run({ 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: null }) })
  },
  '11 verifier throws': () => {
    const f = finding(1, 'high')
    return run({ 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: () => { throw new Error('died') } }) })
  },
  '12 verifier null on low': () => {
    const f = finding(1, 'low')
    return run({ 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: null }) })
  },
  '13 fresh-eyes null': () => run({ 'review:fresh-eyes': null }),
  '13 lens null': () => run({ 'review:find:concurrency': null }),
  '18 keep ruling on needsDecision': () => {
    const f = finding(1, 'high', { needsDecision: true })
    return run(
      { 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: CONFIRMED }) },
      { rulings: [{ match: 'Q01x', ruling: 'keep', note: 'keep the test' }] },
    )
  },
  '22 recheck medium': () => {
    const f = finding(1, 'high')
    return run({
      'review:fresh-eyes': { findings: [f] },
      'review:verify:*': verifier({ [f.title]: CONFIRMED }),
      'review:recheck': { findings: [finding(50, 'medium')] },
    })
  },
  '24 recheck null': () => {
    const f = finding(1, 'high')
    return run({
      'review:fresh-eyes': { findings: [f] },
      'review:verify:*': verifier({ [f.title]: CONFIRMED }),
      'review:recheck': null,
    })
  },
  '26 evidence journey failed': () =>
    run({ evidence: { passed: true, journeys: [{ name: 'a', passed: true }, { name: 'b', passed: false }], screenshots: [] } }),
  '35 recheck finding with a fix ruling': () => {
    const f = finding(1, 'high')
    return run(
      {
        'review:fresh-eyes': { findings: [f] },
        'review:verify:*': verifier({ [f.title]: CONFIRMED }),
        'review:recheck': { findings: [{ ...finding(70, 'medium'), title: 'Recheck Wib-Wobble regression' }] },
      },
      { rulings: [{ match: 'wib_WOBBLE', ruling: 'fix', note: 'fix it' }] },
    )
  },
  '28 shipper declines': () => run({ ship: { shipped: false, reason: 'push rejected by the remote' } }),
  '29 shipper null': () => run({ ship: null }),
}

// --- Happy path ---

test('1. every stage succeeds with ship true: shipped, pr is the shipper URL, stoppedAt null', async () => {
  const { result } = await run()
  assert.equal(result.shipped, true)
  assert.equal(result.pr, PR_URL)
  assert.equal(result.stoppedAt, null)
})

test('2. ship false, all green: not shipped, stoppedAt null, the ship stage never called', async () => {
  const { result, calls } = await run({}, { ship: false })
  assert.equal(result.shipped, false)
  assert.equal(result.stoppedAt, null)
  assert.equal(called(calls, (l) => l === 'ship').length, 0)
})

// --- Brief hash ---

test('3. a brief digest different from args.briefSha256 stops at Brief naming both digests, no build agent, gate block still runs', async () => {
  const { result, calls, args } = await STOPS['3 brief digest differs']()
  assert.equal(calls[0]?.label, 'precheck:brief', 'precheck:brief is the first agent')
  assert.equal(result.stoppedAt, 'Brief')
  assert.ok(text(result.blockedOn).includes(args.briefSha256))
  assert.ok(text(result.blockedOn).includes('b'.repeat(64)))
  assert.equal(called(calls, startsWith('build:')).length, 0)
  assert.equal(gateBlockCalls(calls).length, 1)
})

test('4. precheck:brief returning null or throwing stops at Brief with no build agent', async () => {
  for (const key of ['4 precheck null', '4 precheck throws']) {
    const { result, calls } = await STOPS[key]()
    assert.equal(result.stoppedAt, 'Brief', key)
    assert.equal(called(calls, startsWith('build:')).length, 0, key)
  }
})

// --- Blind test writer ---

function assertStoppedAtTestWriter({ result, calls }, key) {
  assert.equal(result.stoppedAt, 'Build', key)
  assert.match(text(result.blockedOn), /test/i, `${key}: blockedOn names the test writer`)
  assert.equal(called(calls, startsWith('gate:')).length, 0, `${key}: no gate`)
  assert.equal(called(calls, startsWith('review:')).length, 0, `${key}: no review`)
  assert.equal(called(calls, (l) => l === 'ship').length, 0, `${key}: no ship`)
}

test('5. the test writer returning null or throwing while the implementer is done stops at Build naming it; no gate, review or ship', async () => {
  for (const key of ['5 test writer null', '5 test writer throws']) {
    assertStoppedAtTestWriter(await STOPS[key](), key)
  }
})

test('6. the test writer returning an empty tests list stops at Build like 5', async () => {
  assertStoppedAtTestWriter(await STOPS['6 test writer empty'](), '6')
})

// --- Gate trust ---

test('7. a gate that says passed but has a failed result is red: the gate-fix stage runs', async () => {
  const lying = { passed: true, results: REQUIRED_CHECKS.map((check) => ({ check, passed: check !== 'web', tail: 'x' })) }
  const { calls } = await run({ 'gate:1': lying })
  assert.ok(called(calls, (l) => l === 'fix:gate').length >= 1)
})

test('8. a gate that says passed with a required check missing from results is red', async () => {
  const missing = {
    passed: true,
    results: REQUIRED_CHECKS.filter((c) => c !== 'make e2e').map((check) => ({ check, passed: true, tail: 'ok' })),
  }
  const { calls } = await run({ 'gate:1': missing })
  assert.ok(called(calls, (l) => l === 'fix:gate').length >= 1)
})

test('9. gate 2 red after the fix stops at Gate with no review agent', async () => {
  const { result, calls } = await STOPS['9 gate 2 red']()
  assert.ok(labels(calls).includes('gate:2'))
  assert.equal(result.stoppedAt, 'Gate')
  assert.equal(called(calls, startsWith('review:')).length, 0)
  assert.equal(result.shipped, false)
})

// --- Review completeness ---

function assertUnverifiedStop(out, title) {
  assert.equal(out.result.stoppedAt, 'Review')
  assert.ok(text(out.result.blockedOn).includes(title), 'blockedOn names the finding')
  assertNoShip(out)
  const rec = record(out.calls)
  assert.ok(text(rec.review?.unverified).includes(title), 'the finding is in review.unverified')
}

test('10. a verifier returning null for a high finding stops at Review naming it, listed unverified', async () => {
  const out = await STOPS['10 verifier null on high']()
  assert.equal(verifyCallFor(out.calls, finding(1, 'high').title).length >= 1, true)
  assertUnverifiedStop(out, finding(1, 'high').title)
})

test('11. a verifier that throws stops at Review like 10', async () => {
  assertUnverifiedStop(await STOPS['11 verifier throws'](), finding(1, 'high').title)
})

test('12. a verifier returning null for a low finding stops at Review like 10', async () => {
  assertUnverifiedStop(await STOPS['12 verifier null on low'](), finding(1, 'low').title)
})

test('13. a reviewer (fresh-eyes or a lens) returning null stops at Review with no ship', async () => {
  for (const key of ['13 fresh-eyes null', '13 lens null']) {
    const out = await STOPS[key]()
    assert.equal(out.result.stoppedAt, 'Review', key)
    assertNoShip(out)
  }
})

// --- Verification cap ---

test('14. with 15 findings of which 13 are high, every high is verified and only medium/low are left unverified', async () => {
  const findings = [
    ...Array.from({ length: 13 }, (_, i) => finding(i + 1, 'high')),
    finding(14, 'medium'),
    finding(15, 'low'),
  ]
  const { calls } = await run({ 'review:fresh-eyes': { findings } })
  for (const f of findings.slice(0, 13)) {
    assert.ok(verifyCallFor(calls, f.title).length >= 1, `${f.title} has a verifier call`)
  }
  const unverified = record(calls).review?.unverified ?? []
  for (const u of unverified) {
    const f = findings.find((x) => text(u).includes(x.title))
    assert.ok(f, `unverified entry ${text(u)} is one of the findings`)
    assert.ok(['medium', 'low'].includes(f.severity), `${f.title} unverified is medium/low`)
  }
})

test('15. with 15 medium findings exactly 12 are verified, 3 listed unverified, and the run is not stopped by them', async () => {
  const findings = Array.from({ length: 15 }, (_, i) => finding(i + 1, 'medium'))
  const { result, calls } = await run({ 'review:fresh-eyes': { findings } })
  assert.equal(called(calls, startsWith('review:verify:#')).length, 12)
  const unverified = text(record(calls).review?.unverified)
  assert.equal(findings.filter((f) => unverified.includes(f.title)).length, 3)
  assert.equal(result.stoppedAt, null)
  assert.equal(result.shipped, true)
})

// --- Rulings ---

test('16. a ruling "Fix" (capitalised) or " defer " (spaced) is handled as fix / defer', async () => {
  const f = finding(1, 'high', { needsDecision: true })
  const base = { 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: CONFIRMED }) }

  const fixed = await run(base, { rulings: [{ match: 'Q01x', ruling: 'Fix', note: 'fix it' }] })
  assert.notEqual(fixed.result.refused, true)
  const fixPrompts = called(fixed.calls, (l) => l === 'fix:review')
  assert.ok(fixPrompts.some((c) => c.prompt.includes(f.title)), 'Fix: the finding reaches fix:review')
  assert.equal(fixed.result.stoppedAt, null)

  const deferred = await run(base, { rulings: [{ match: 'Q01x', ruling: ' defer ', note: 'later' }] })
  assert.notEqual(deferred.result.refused, true)
  assert.ok(!called(deferred.calls, (l) => l === 'fix:review').some((c) => c.prompt.includes(f.title)), 'defer: not sent to fix')
  assert.ok(text(record(deferred.calls).review?.deferred).includes(f.title), 'defer: listed in review.deferred')
  assert.equal(deferred.result.stoppedAt, null)
})

test('17. a Fix-stage ruling outside fix/defer/keep/rewrite/retire refuses before any agent, naming the bad ruling', async () => {
  const { result, calls } = await run({}, { rulings: [{ match: 'some title', ruling: 'maybe', note: 'n' }] })
  assert.equal(result.refused, true)
  assert.equal(calls.length, 0)
  assert.ok(/maybe|some title/.test(text(result.reason)), 'reason names the bad ruling')
})

test('18. a confirmed needsDecision high finding matched by a keep ruling still blocks at Fix naming it', async () => {
  const out = await STOPS['18 keep ruling on needsDecision']()
  assert.equal(out.result.stoppedAt, 'Fix')
  assert.ok(text(out.result.blockedOn).includes(finding(1, 'high').title))
  assertNoShip(out)
})

test('19. a confirmed finding without needsDecision matched by a keep ruling is fixed, not dropped', async () => {
  const f = finding(1, 'high')
  const { calls } = await run(
    { 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: CONFIRMED }) },
    { rulings: [{ match: 'Q01x', ruling: 'keep', note: 'keep the test' }] },
  )
  assert.ok(called(calls, (l) => l === 'fix:review').some((c) => c.prompt.includes(f.title)))
})

test('20. the fix:review prompt never contains a ruling\'s keywords', async () => {
  const f = { ...finding(1, 'high', { needsDecision: true }), title: 'Qux-Zorbled lock is held across the await' }
  const g = finding(2, 'high')
  const { calls } = await run(
    {
      'review:fresh-eyes': { findings: [f, g] },
      'review:verify:*': verifier({ [f.title]: CONFIRMED, [g.title]: CONFIRMED }),
    },
    {
      rulings: [
        { keywords: ['qux_zorbled', 'LOCK'], ruling: 'fix', note: 'fix the lock' },
        { keywords: ['plugh_xyzzy'], ruling: 'defer', note: 'unrelated' },
      ],
    },
  )
  const fixes = called(calls, (l) => l === 'fix:review')
  assert.ok(fixes.length >= 1, 'fix:review ran')
  for (const c of fixes) {
    for (const kw of ['qux_zorbled', 'LOCK', 'plugh_xyzzy']) {
      assert.ok(!c.prompt.includes(kw), `fix:review prompt carries keyword ${kw}`)
    }
  }
})

// --- Re-review of review fixes ---

function confirmedOne(extra = {}) {
  const f = finding(1, 'high')
  return { f, overrides: { 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: CONFIRMED }), ...extra } }
}

test('21. after fix:review is done there is exactly one review:recheck, before gate:3', async () => {
  const { overrides } = confirmedOne()
  const { calls } = await run(overrides)
  const ls = labels(calls)
  assert.ok(ls.includes('fix:review'))
  assert.equal(ls.filter((l) => l === 'review:recheck').length, 1)
  assert.ok(ls.includes('gate:3'), 'gate:3 ran')
  assert.ok(ls.indexOf('fix:review') < ls.indexOf('review:recheck'))
  assert.ok(ls.indexOf('review:recheck') < ls.indexOf('gate:3'))
})

test('22. review:recheck returning a medium-or-above finding stops at Fix naming it, no ship', async () => {
  const out = await STOPS['22 recheck medium']()
  assert.equal(out.result.stoppedAt, 'Fix')
  assert.ok(text(out.result.blockedOn).includes(finding(50, 'medium').title))
  assertNoShip(out)
})

test('23. review:recheck returning only low findings continues and ships, the lows in review.deferred', async () => {
  const low = finding(60, 'low')
  const { overrides } = confirmedOne({ 'review:recheck': { findings: [low] } })
  const { result, calls } = await run(overrides)
  assert.equal(result.stoppedAt, null)
  assert.equal(result.shipped, true)
  assert.ok(text(record(calls).review?.deferred).includes(low.title))
})

test('24. review:recheck returning null stops at Fix with no ship', async () => {
  const out = await STOPS['24 recheck null']()
  assert.equal(out.result.stoppedAt, 'Fix')
  assertNoShip(out)
})

test('25. no confirmed findings means no fix:review and no review:recheck', async () => {
  for (const overrides of [{}, { 'review:fresh-eyes': { findings: [finding(1, 'high')] } }]) {
    const { result, calls } = await run(overrides)
    assert.equal(called(calls, (l) => l === 'fix:review').length, 0)
    assert.equal(called(calls, (l) => l === 'review:recheck').length, 0)
    assert.equal(result.shipped, true)
  }
})

// --- Evidence trust ---

test('26. evidence that says passed with a failed journey stops at Evidence', async () => {
  const out = await STOPS['26 evidence journey failed']()
  assert.equal(out.result.stoppedAt, 'Evidence')
  assertNoShip(out)
})

test('27. evidence that says passed with no journeys is not stopped at Evidence: the run continues to Ship', async () => {
  const { result, calls } = await run({ evidence: { passed: true, journeys: [], screenshots: [] } })
  assert.notEqual(result.stoppedAt, 'Evidence')
  assert.equal(result.stoppedAt, null)
  assert.ok(labels(calls).includes('ship'), 'ship was called')
  assert.equal(result.shipped, true)
})

// --- Ship outcome ---

test('28. the shipper returning shipped false with a reason stops at Ship with blockedOn the reason', async () => {
  const { result } = await STOPS['28 shipper declines']()
  assert.equal(result.stoppedAt, 'Ship')
  assert.equal(result.shipped, false)
  assert.ok(result.blockedOn != null)
  assert.ok(text(result.blockedOn).includes('push rejected by the remote'))
})

test('29. the shipper returning null stops at Ship with a non-empty blockedOn', async () => {
  const { result } = await STOPS['29 shipper null']()
  assert.equal(result.stoppedAt, 'Ship')
  assert.equal(result.shipped, false)
  assert.ok(nonEmpty(result.blockedOn), `blockedOn is non-empty: ${text(result.blockedOn)}`)
})

// --- Gate block always written ---

test('30. every stop ends with exactly one gate-block call', async () => {
  for (const [key, scenario] of Object.entries(STOPS)) {
    const { result, calls } = await scenario()
    assert.ok(result.stoppedAt, `${key}: the run stopped`)
    assert.equal(gateBlockCalls(calls).length, 1, `${key}: one gate-block call`)
    assert.equal(calls[calls.length - 1].label, 'gate-block', `${key}: gate-block is the last agent`)
  }
})

// --- Rulings on re-review findings ---

test('34. a medium-or-above recheck finding matched by a Fix-stage defer ruling does not stop the run: it ships and the finding is in review.deferred', async () => {
  const f = finding(1, 'high')
  const re = { ...finding(70, 'medium'), title: 'Recheck Wib-Wobble regression' }
  const { result, calls } = await run(
    {
      'review:fresh-eyes': { findings: [f] },
      'review:verify:*': verifier({ [f.title]: CONFIRMED }),
      'review:recheck': { findings: [re] },
    },
    { rulings: [{ match: 'wib_WOBBLE', ruling: 'defer', note: 'later' }] },
  )
  assert.notEqual(result.refused, true)
  assert.equal(result.stoppedAt, null)
  assert.equal(result.shipped, true)
  assert.ok(text(record(calls).review?.deferred).includes(re.title))
})

test('35. a medium-or-above recheck finding matched by a Fix-stage fix ruling still stops at Fix naming it', async () => {
  const out = await STOPS['35 recheck finding with a fix ruling']()
  assert.notEqual(out.result.refused, true)
  assert.equal(out.result.stoppedAt, 'Fix')
  assert.ok(text(out.result.blockedOn).includes('Recheck Wib-Wobble regression'))
  assertNoShip(out)
})

// --- Rulings reach the stages that judge against them ---

function reachesEveryStage(rulings) {
  const f = finding(1, 'high')
  return run(
    { 'review:fresh-eyes': { findings: [f] }, 'review:verify:*': verifier({ [f.title]: CONFIRMED }) },
    { rulings },
  )
}

const BUILD_NOTE = 'NOTE-ZETA-36'
const FIX_NOTE = 'NOTE-ETA-37'

test('36. a Build-stage ruling\'s note appears in the prompt of every stage that judges the build against the brief', async () => {
  const { result, calls } = await reachesEveryStage([
    { stage: 'Build', match: 'storage layout', ruling: 'use option B', note: BUILD_NOTE },
  ])
  assert.notEqual(result.refused, true)
  const exact = ['precheck:brief', 'build:implement', 'build:tests', 'review:fresh-eyes', 'review:recheck', 'evidence', 'gate-block']
  const prefixes = ['gate:', 'review:find:', 'review:verify:#']
  for (const l of exact) assert.ok(labels(calls).includes(l), `${l} ran`)
  for (const p of prefixes) assert.ok(called(calls, startsWith(p)).length >= 1, `${p}* ran`)
  const judged = calls.filter((c) => exact.includes(c.label) || prefixes.some((p) => (c.label ?? '').startsWith(p)))
  for (const c of judged) {
    assert.ok(c.prompt.includes(BUILD_NOTE), `${c.label} prompt carries the Build ruling's note`)
  }
})

test('37. a Fix-stage ruling\'s note appears in no prompt before Fix', async () => {
  const { result, calls } = await reachesEveryStage([{ stage: 'Fix', match: 'Q01x', ruling: 'fix', note: FIX_NOTE }])
  assert.notEqual(result.refused, true)
  const exact = ['precheck:brief', 'build:implement', 'build:tests', 'gate:1', 'review:fresh-eyes']
  const prefixes = ['review:find:', 'review:verify:#']
  const early = calls.filter((c) => exact.includes(c.label) || prefixes.some((p) => (c.label ?? '').startsWith(p)))
  assert.ok(early.length >= 6, 'the early stages ran')
  for (const c of early) assert.ok(!c.prompt.includes(FIX_NOTE), `${c.label} prompt carries the Fix ruling's note`)
})

test('38. the record passed to gate-block carries a rulings array equal to args.rulings, both stages', async () => {
  const rulings = [
    { stage: 'Build', match: 'storage layout', ruling: 'use option B', note: 'NOTE-THETA-38a' },
    { stage: 'Fix', match: 'Q01x', ruling: 'fix', note: 'NOTE-THETA-38b' },
  ]
  const { calls } = await reachesEveryStage(rulings)
  assert.deepEqual(record(calls).rulings, rulings)
})

test('39. a Build ruling\'s keywords appear in no prompt except gate-block\'s', async () => {
  const kws = ['frobnitz_kw39', 'QUUXLY_kw39']
  const { result, calls } = await reachesEveryStage([
    { stage: 'Build', keywords: kws, ruling: 'use option B', note: 'NOTE-IOTA-39' },
  ])
  assert.notEqual(result.refused, true)
  const others = calls.filter((c) => c.label !== 'gate-block')
  assert.ok(others.length > 0)
  for (const c of others) {
    for (const kw of kws) assert.ok(!c.prompt.includes(kw), `${c.label} prompt carries keyword ${kw}`)
  }
})
