// A stand-in for the Workflow runtime, so a workflow script's control flow can
// be driven by stubbed agents under node:test. It implements the runtime
// contract the scripts are written against: `args`, `agent`, `parallel`
// (a throwing thunk resolves to null, never rejects), `pipeline` (stages get
// (prev, item, index); a throwing stage drops that item to null and skips its
// later stages), `phase`, `log`, `budget`. The script file starts with
// `export const meta = {...}` and its body uses top-level `return` and
// `await`, so it is loaded as the body of an async function, not as a module.

import { readFileSync } from 'node:fs'

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

const GLOBALS = ['args', 'agent', 'parallel', 'pipeline', 'phase', 'log', 'budget', 'workflow']

export async function runWorkflow(scriptPath, { args, agent, budgetTotal = null } = {}) {
  const source = readFileSync(scriptPath, 'utf8')
  // Only the leading meta export is a module construct; the runtime treats the
  // rest as a function body.
  const body = source.replace(/^export\s+const\s+meta\s*=/m, 'const meta =')
  if (/^\s*(export|import)\s/m.test(body)) {
    throw new Error('harness: the script has a module statement other than `export const meta`')
  }

  const logs = []
  const calls = []
  const phases = []

  const agentFn = async (prompt, opts = {}) => {
    calls.push({ label: opts?.label, prompt, opts })
    return await agent(prompt, opts)
  }

  const parallel = async (thunks) =>
    Promise.all(
      thunks.map(async (thunk) => {
        try {
          return await thunk()
        } catch {
          return null
        }
      }),
    )

  const pipeline = async (items, ...stages) =>
    Promise.all(
      items.map(async (item, index) => {
        let prev = item
        for (const stage of stages) {
          try {
            prev = await stage(prev, item, index)
          } catch {
            return null
          }
        }
        return prev
      }),
    )

  const phase = (title) => {
    phases.push(title)
  }
  const log = (msg) => {
    logs.push(String(msg))
  }
  const budget = {
    total: budgetTotal,
    spent: () => 0,
    remaining: () => (budgetTotal == null ? Infinity : Math.max(0, budgetTotal)),
  }
  const workflow = async () => {
    throw new Error('harness: workflow() is not supported')
  }

  const fn = new AsyncFunction(...GLOBALS, body)
  const result = await fn(args, agentFn, parallel, pipeline, phase, log, budget, workflow)
  return { result, logs, calls, phases }
}

export const REQUIRED_CHECKS = ['ruff check', 'ruff format', 'web', 'make test', 'make e2e']

export const PR_URL = 'https://github.com/example/hax/pull/4242'

export function defaultArgs(over = {}) {
  return {
    id: 'f1-test',
    brief: '/repo/local/briefs/f1-test/brief.md',
    worktree: '/repo/.worktrees/f1-test',
    repoRoot: '/repo',
    branch: 'feat/f1-test',
    date: '2026-11-03',
    briefSha256: 'a'.repeat(64),
    ship: true,
    plan: 'max-5x',
    ...over,
  }
}

// The all-green result for a stage label.
export function greenResult(label, args) {
  if (label === 'precheck:brief') return { sha256: args.briefSha256 }
  if (label === 'build:implement' || label?.startsWith('fix:')) {
    return { status: 'done', files: ['packages/core/x.py'], calls: [], notes: '' }
  }
  if (label === 'build:tests') {
    return { tests: ['a behaviour is observed'], files: ['tests/test_x.py'] }
  }
  if (label?.startsWith('gate:')) {
    return {
      passed: true,
      results: REQUIRED_CHECKS.map((check) => ({ check, passed: true, tail: 'ok' })),
    }
  }
  if (label === 'review:fresh-eyes' || label === 'review:recheck' || label?.startsWith('review:find:')) {
    return { findings: [] }
  }
  if (label?.startsWith('review:verify:')) return { confirmed: false, reason: 'refuted' }
  if (label === 'evidence') {
    return { passed: true, journeys: [{ name: 'journey one', passed: true }], screenshots: ['desktop.png'] }
  }
  if (label === 'ship') return { shipped: true, pr: PR_URL, commit: 'abc1234' }
  if (label === 'gate-block') return 'gate block written'
  return null
}

// A stub agent: every stage green unless overridden. `overrides` maps a label
// to a value (returned as is, null included) or to a function
// (prompt, opts, green) => result, which may throw. A key ending in `*` is a
// label prefix; an exact key wins over a prefix.
export function stubAgent(args, overrides = {}) {
  return async (prompt, opts = {}) => {
    const label = opts?.label
    const green = greenResult(label, args)
    let key
    if (Object.prototype.hasOwnProperty.call(overrides, label)) key = label
    else {
      key = Object.keys(overrides)
        .filter((k) => k.endsWith('*') && label?.startsWith(k.slice(0, -1)))
        .sort((a, b) => b.length - a.length)[0]
    }
    if (key === undefined) return green
    const v = overrides[key]
    if (typeof v === 'function') return await v(prompt, opts, green)
    return v === null ? null : structuredClone(v)
  }
}

// The chain record embedded in the gate-block prompt after the line `Record:`.
export function extractRecord(prompt) {
  const at = prompt.indexOf('Record:')
  if (at < 0) throw new Error('no `Record:` in the gate-block prompt')
  const start = prompt.indexOf('{', at)
  let depth = 0
  let inStr = false
  let esc = false
  for (let i = start; i < prompt.length; i++) {
    const c = prompt[i]
    if (inStr) {
      if (esc) esc = false
      else if (c === '\\') esc = true
      else if (c === '"') inStr = false
      continue
    }
    if (c === '"') inStr = true
    else if (c === '{') depth++
    else if (c === '}') {
      depth--
      if (depth === 0) return JSON.parse(prompt.slice(start, i + 1))
    }
  }
  throw new Error('unterminated record JSON')
}
