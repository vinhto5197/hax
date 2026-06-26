# scripts/ — ad-hoc dev utilities

One-off, **read-mostly** tools for poking at a running local stack (DB, etc.)
while developing. Not part of the app; not imported by it. Each script
bootstraps its own path + `.env`, so you can run it from anywhere with the
venv's deps available.

| Script | What it does | Example |
|---|---|---|
| `corpus.py` | List ingested documents, or dump one document's chunk content | `python scripts/corpus.py` / `python scripts/corpus.py glimmerwick.md` |

Add new utilities here as needed. Keep them read-only unless clearly named
otherwise (a destructive script should make that obvious).
