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
  page. The text styles (caption 11/16 … display 34/40) and two radii
  (control 8, card 14) are tokens with their own names; Tailwind's defaults
  are left intact so untouched components keep rendering as before.
- **Three literals stay outside the tokens**, each for a reason the tokens
  cannot express: the modal and drawer scrims and the code block are dark in both themes
  (the highlight palette assumes a dark block), and the Google sign-in button
  keeps Google's own light and dark colours, which its brand guidelines
  require.
- **Links**: a link inside a sentence is underlined, since colour alone does
  not separate it from the words around it; a link standing on its own (a
  footer row, a "back" line) is the accent with an underline on hover.
- **Buttons** come in three tiers, and a screen has at most one of the first:
  the accent fill for the primary action, the outlined control for secondary
  actions, plain text for the rest. The composer's send square is the chat
  screen's primary and is grey until there is something to send; the shell's
  New chat is secondary.
- **The wordmark is drawn, not typed**: `components/Wordmark.tsx` is an
  inline SVG (lowercase "hax", one stroke, round terminals) in
  `currentColor`, and `app/icon.svg` is the x of that mark on the accent
  tile. The name is a graphic only there; in prose it is the plain word.
  The proxy's matcher excludes `icon.svg`, since a logged-out page's favicon
  request would otherwise be redirected to the login page.
- **Two global rules carry accessibility**: keyboard focus is a 2 px accent
  ring on every control (`:focus-visible`, in the base layer so a component
  can opt out), and `prefers-reduced-motion` reduces every animation and
  transition to a single instant frame.

## Alternatives considered

- **Keep the starter's styles and tidy them.** Rejected: two colour systems
  (black-at-an-opacity and a dark-mode guess per component) cannot be
  tuned from one place, which is the whole requirement.
- **A component library** (shadcn/ui, Radix themes). Rejected for v0: the
  app has eight components, and a library's own tokens and dark-mode
  mechanism would sit on top of the ones designed for hax.
- **CSS-in-JS or a theme object in TypeScript.** Rejected: Tailwind v4's
  `@theme` already turns CSS variables into utilities, so a second theme
  representation would duplicate the stylesheet.

## Consequences

- A colour or radius change is one line in `globals.css`; a new component
  has no colour decisions to make.
- Builds depend on fonts.googleapis.com being reachable once. If that ever
  blocks a deploy, the upgrade is `next/font/local` with the OFL-licensed
  files vendored; nothing else changes.
- The starter's utilities (`bg-black/5` and kin) were removed component by
  component, each diff reviewable on its own; the `--background` and
  `--foreground` aliases that bridged the migration went with the last one.
