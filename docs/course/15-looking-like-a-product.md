# 15. Looking like a product

Threads: B (full-stack engineering) · C (building with Claude Code)

## The idea

Software can work and still look like a demo: mismatched grays, a guess at every dark-mode color, a sidebar that crowds a phone. Each piece is fine alone; together they read as experiments.

A design system fixes this by moving every visual decision to one place. Think of a house painted from one color card: nobody picks a shade on site, and repainting means changing the card. In code, the card is a set of design tokens: named values such as "ground," "ink" and "accent" that every component uses instead of raw colors.

## How hax does it

**One token file.** All colors, type sizes and corner radii live in [globals.css](../../apps/web/app/globals.css). The light theme is a list of CSS (the language that styles web pages) custom properties, variables the browser resolves at render time, on `:root`. Among them: `--ground`, `--surface-1` to `--surface-3`, `--ink` to `--ink-3`, `--border`, `--accent`, the user's chat bubble, and two status colors. A second list redefines the same names inside `@media (prefers-color-scheme: dark)`, the browser's report of the system theme. A block called `@theme inline` hands each variable to Tailwind (the utility-class CSS framework the web app uses), so a class like `bg-ground` or `text-ink-2` always points at the live value. There is no theme toggle and no `.dark` class: the page follows the operating system.

The same block defines six text styles, from `caption` (11 px on a 16 px line) to `display` (34 on 40). It also defines two radii, `control` (8 px) and `card` (14 px). Three typefaces come from Google Fonts but are downloaded at build time and served from hax's own site by next/font (Next.js's font loader): Instrument Sans for text, Instrument Serif for the greeting only, JetBrains Mono for code.

**A few global rules.** Keyboard focus is a 2 px accent ring on every control. Reduced-motion settings shrink every animation to one instant frame. A `color-scheme` declaration makes the browser's own parts, such as a dropdown's popup, follow the theme. Commit `439c6c5` added it after the model picker's popup showed white in dark mode on Windows and Linux.

**The wordmark is drawn.** [Wordmark.tsx](../../apps/web/components/Wordmark.tsx) is an inline SVG (a vector drawing in the page) that takes its color from the surrounding text. The favicon (the small icon on the browser tab), [icon.svg](../../apps/web/app/icon.svg), is the mark's x on an accent tile.

**The phone shell.** On a phone, [Shell.tsx](../../apps/web/components/chat/Shell.tsx) swaps the fixed sidebar for a top bar (menu, wordmark, new chat) and a drawer. "Phone" means narrower than 48 rem (a unit tied to the browser's text size; 768 px by default) or no taller than 500 px. The queries live in [media.ts](../../apps/web/lib/media.ts). The drawer behaves as a dialog. Focus moves in and back out, the page behind is inert (unclickable), and the backdrop, Escape, navigating or widening the window closes it. The sidebar is mounted in only one place at a time, so features that look for it have one target.

## What was decided, and why

[ADR 0014](../adr/0014-design-system.md) starts from the problem. Until then the styling was the Next.js starter's: two variables, Arial, and black or white at different opacities chosen per component. As the ADR puts it, every color choice was made locally, dark mode was a second set of guesses, and nothing could be changed in one place.

Rejected:
- **Tidying the starter styles.** Two color systems cannot be tuned from one place.
- **A component library** (shadcn/ui, Radix themes). The app had eight components, and a library's own tokens and dark mode would sit on top of hax's.
- **A theme object in TypeScript.** Tailwind v4 already turns CSS variables into classes, so a second copy would only duplicate the stylesheet.

Four colors stay outside the tokens, each with a reason: the modal and drawer backdrops, the code block (dark in both themes because its highlight palette assumes it), the Google button (Google's brand rules), and the favicon (an icon file cannot read CSS variables). Contrast was checked by computation: 4.5:1 for text, 3:1 for control edges. The one known limit is that `ink-3` holds only on three surfaces. Buttons come in three tiers, with at most one accent-filled primary per screen.

A color change is one line. But builds now need Google Fonts reachable once, and a later addendum to [ADR 0013](../adr/0013-deploy-topology.md) notes that an outage there can fail a deploy.

## The episode

The phone shell landed on 2026-10-11 (`a06dfff`). The next day brought four fixes, each a case the first version missed:

- **iOS zoom (`9a4f211`).** Safari zooms the page into any focused field with text under 16 px, and the zoom stays after the keyboard closes. The type scale put controls at 15 px. The fix set inputs to 16 px on narrow screens.
- **Landscape (`6c7b3bc`, `8b42987`).** A phone turned sideways is wider than the width where the layout switches, so the zoom rule missed it and the sidebar ate the short screen. The 16 px rule now keys on "no hover" (a touchscreen) instead of width. A window under 500 px tall also gets the phone shell.
- **The documents panel (`539fae7`).** On a landscape phone it hid the conversations. On a short screen it now starts collapsed.
- **"Show in panel" (`9a1b21e`).** With the sidebar unmounted behind a closed drawer, the button found no row to scroll to. It now sends an event, and the shell opens the drawer and waits for the row.

Later, [CLAUDE.md](../../CLAUDE.md) gained a rule (`45df6cd`, 2026-10-20): after a UI change, the assistant drives the changed screen with a browser at desktop and phone width. The weekly journeys routine later added a Playwright journey (an automated browser test) for the top bar and drawer (`0374ae3`).

## Look at

- [docs/adr/0014-design-system.md](../adr/0014-design-system.md): tokens, exceptions, alternatives
- [apps/web/app/globals.css](../../apps/web/app/globals.css): both themes and the global rules
- [apps/web/components/chat/Shell.tsx](../../apps/web/components/chat/Shell.tsx): the drawer and the phone shell
- [apps/web/components/Wordmark.tsx](../../apps/web/components/Wordmark.tsx): the drawn wordmark
- [apps/web/app/icon.svg](../../apps/web/app/icon.svg): the favicon
- [docs/adr/0013-deploy-topology.md](../adr/0013-deploy-topology.md): the 2026-10-11 addendum on the font fetch at build
- [CLAUDE.md](../../CLAUDE.md): Verifying web changes
- [apps/web/lib/media.ts](../../apps/web/lib/media.ts): the two queries that define "phone"
- `4e25760`: design tokens, typefaces and the wordmark
- `a06dfff`: the chat shell on a phone
- `9a4f211`, `6c7b3bc`: 16 px controls, keyed on touchscreens
- `8b42987`, `539fae7`: the landscape fixes
- `9a1b21e`: Show in panel reaches the drawer
- `439c6c5`: `color-scheme` so native control parts follow the theme
- `45df6cd`: how web changes are verified, including the assistant's browser look
- `0374ae3`: the phone top bar and drawer journey
