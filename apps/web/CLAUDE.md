# TypeScript guidelines (gradual typing)

We are writing TypeScript but learning it gradually. Prioritize clarity for a JavaScript developer over type wizardry.

## Type the boundaries first
- Exported functions/components
- API responses
- Props
- Shared utilities

Inside a function, prefer type inference unless it gets confusing.

## Rules
- Avoid `any`. If unsure, use `unknown` and narrow with checks.
- Prefer `type` aliases for unions and simple shapes; use `interface` for React props if it reads better.
- Add return types for exported functions and hooks when it improves readability.
- Prefer `as const` for literal objects/arrays used as enums.

## JS → TS conversion (small steps)
1. Rename `*.js` → `*.ts` (or `*.jsx` → `*.tsx`) only if the file is already stable.
2. Fix minimum TS errors in order:
   - Add parameter/prop types
   - Type object shapes
   - Add return types (especially exported funcs)
   - Replace unsafe access with narrowing (`if (!x) return;`, `typeof`, `in`, etc.)
3. If types are unclear, introduce a small helper type and move on — don't block the whole PR.

## Preferred patterns
- Union types over enums: `type Status = "idle" | "loading" | "success" | "error"`
- `Record<string, T>` for dictionaries
- `readonly` arrays when returning constants
- React components should have typed props
- React event handlers use React types only when needed

## Avoided patterns
- No heavy generics unless they simplify code
- No advanced conditional types unless there is a clear payoff
- Don't introduce a new library solely for typing

## When responding with code
- Keep changes minimal and localized
- If adding a type, include a 1-line comment only when it teaches a TS concept
- If there are multiple options, choose the simplest and mention the alternative briefly
