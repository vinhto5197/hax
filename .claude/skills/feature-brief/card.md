# <id> — <title>

What the maintainer reads and approves: one screen, written for an engineering manager or a technical product manager. The brief beside it is the spec the agents build from; the card states what the brief decides, never anything the brief does not.

**What changes for the user.** Two or three sentences: what someone can do or sees afterwards that they cannot now.

**Why now.** One or two sentences: who asked, and what goes wrong if it is never built.

**How, in one paragraph.** The shape of the change in plain words: which parts of the product move (the server, the app, a background job, the database), and the one idea that makes it work. No file names, function names or code.

**Not in this one.** What a reader might expect that is deliberately left out, and where it goes instead.

**Risks and trade-offs.** At most three bullets, each one sentence: what could go wrong or what we give up, and why it is acceptable.

**Decisions for you.** Each with the options and a recommendation, one or two sentences each; "None" when none.

**Size.** Lines of code, a token estimate, wall time, and the review ceiling approval pre-authorizes, on one line.

**Design review.** The reviewer's verdict in one line.

Reply "approved", or say what to change.
