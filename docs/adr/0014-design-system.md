# 0014 — Design system: tokens in the Tailwind theme, a drawn wordmark

**Status:** accepted
**Date:** 2026-10-09

## Context

Through M4 the web app's styling was the Next.js starter's: two custom
properties (`--background`, `--foreground`), Arial, and ad hoc opacities of
black and white (`bg-black/5`, `dark:text-white/60`) chosen per component.
That is fine for a demo and wrong for a product: every colour decision was
local, dark mode was a second set of guesses, and nothing could be changed in
one place. The cohesion item of M4 ("feels like a product, not a collection
of demos") needs the opposite: one source of colour, type and shape that every
component derives from.

The system itself was designed outside the repo (a design-system artifact and
a screen canvas) and is recorded here only in the form the code consumes.

## Decision

- **Tokens live in `apps/web/app/globals.css` and nowhere else.** Both
  themes are plain custom properties on `:root`, the dark set under
  `@media (prefers-color-scheme: dark)`, exposed to Tailwind v4 through
  `@theme inline` so utilities such as `bg-ground`, `text-ink-2`,
  `border-border-control` and `bg-bubble-user` resolve to the live variable.
  The palette is warm neutrals with one sky-blue accent; contrast was
  verified by computation (4.5:1 for text, 3:1 for control edges) and the
  one documented limit is that `ink-3` holds only on `ground`, `surface-1`
  and `surface-2`. The theme follows the system; there is no toggle and no
  `.dark` class, which keeps every `dark:` variant a media query.
- **Type is three Google faces self-hosted by next/font** (Instrument Sans
  for interface and prose, Instrument Serif for the greeting only, JetBrains
  Mono for code), set as `--font-sans/serif/mono` so Tailwind's preflight
  applies the sans by default. Fetched at build time and served from our
  origin, so the CSP's `font-src 'self'` holds and no request leaves the
  page. The text styles (caption 11/16 … display 28/34) and two radii
  (control 8, card 14) are tokens with their own names; Tailwind's defaults
  are left intact so untouched components keep rendering as before.
- **`--background` and `--foreground` are aliases** of `ground` and `ink`,
  not a second set of values, kept only until the classes that use them are
  migrated. Components adopt the tokens one at a time; a component that has
  not been migrated renders on the new page colours through the aliases.
- **The wordmark is drawn, not typed**: `components/Wordmark.tsx` is an
  inline SVG (lowercase "hax", one stroke, round terminals) in
  `currentColor`, and `app/icon.svg` is the x of that mark on the accent
  tile. The name is a graphic only there; in prose it is the plain word.

## Consequences

- A colour or radius change is one line in `globals.css`; a new component
  has no colour decisions to make.
- Builds depend on fonts.googleapis.com being reachable once. If that ever
  blocks a deploy, the upgrade is `next/font/local` with the OFL-licensed
  files vendored; nothing else changes.
- The starter's utilities (`bg-black/5` and kin) remain valid CSS and are
  removed only as each component is migrated, so the migration is reviewable
  per component rather than as one diff.
