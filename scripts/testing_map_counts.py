"""Prints the Counts line of docs/testing-map.md from its tables. Read-only.

Usage: python scripts/testing_map_counts.py
"""

import re
from collections import Counter
from pathlib import Path

MAP = Path(__file__).resolve().parents[1] / "docs" / "testing-map.md"
ROW = re.compile(r"^\| \d+[a-z]? \|.*\| (\S+) \|$")
gaps = [m[1] for line in MAP.read_text().splitlines() if (m := ROW.match(line))]
STAR = r"J\*"  # escaped in the Markdown, so it is not read as emphasis
n = Counter(gaps)
j = n["J"] + n[STAR] + n["J†"]
print(
    f"{len(gaps)} behaviours; {n['–']} covered; {len(gaps) - n['–']} gaps: "
    f"J {j} ({STAR} {n[STAR]}, J† {n['J†']}), U {n['U']}, L {n['L']}."
)
