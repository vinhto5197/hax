# <id> — <title>

What the maintainer reads and approves: one screen, written for an engineering manager or a technical product manager. The brief beside it is the spec the agents build from; the card states what the brief decides, never anything the brief does not.

**What changes for the user.** Two or three sentences: what someone can do or sees afterwards that they cannot now.

**Why now.** One or two sentences: who asked, and what goes wrong if it is never built.

**How, in one paragraph.** The shape of the change in plain words: which parts of the product move (the server, the app, a background job, the database), and the one idea that makes it work. No file names, function names or code.

**Adds to the stack.** Always present, "None" when none. Every new service or container (in production, CI or the test stack), dependency (a package, an image, an external API), database table or column, environment variable, and production code that exists only for tests, one line each with why; never only under the brief's calls.

**Not in this one.** What a reader might expect that is deliberately left out, and where it goes instead.

**Risks and trade-offs.** At most three bullets, each one sentence: what could go wrong or what we give up, and why it is acceptable.

**Decisions for you.** Each with the options and a recommendation, one or two sentences each; "None" when none.

**Slices.** "One pull request" or one line per slice in build order: what it delivers on its own and its reviewed lines. Each slice is its own pull request, built after the previous one merges.

**Size.** Reviewed lines (code, test infrastructure, CI, docs) and test lines, a token estimate, wall time, and the review ceiling approval pre-authorizes, on one line; per slice when sliced.

**Design review.** The reviewer's verdict in one line.

Reply "approved", or say what to change.
