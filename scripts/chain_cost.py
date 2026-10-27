"""Tokens per phase of one feature-chain run, from its agents' own transcripts.

    .venv/bin/python scripts/chain_cost.py <runId>   (e.g. wf_c358384c-a03)

Reads ~/.claude/projects/<this project>/*/subagents/workflows/<runId>/: the
journal maps each agent to its phase, and each agent's transcript carries the
API's usage per message. Input counts cache reads and writes, so it is the
volume the agents read, not the bill. A resumed run reuses the runId, so the
figures cover both launches. Read-only.
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = Path.home() / ".claude" / "projects" / str(ROOT).replace("/", "-")


def main(run_id: str) -> int:
    runs = list(PROJECTS.glob(f"*/subagents/workflows/{run_id}"))
    if not runs:
        print(f"no run {run_id} under {PROJECTS}", file=sys.stderr)
        return 1
    run = runs[0]
    phase_of = {}
    for line in (run / "journal.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row.get("type") == "started":
            phase_of[row["agentId"]] = row.get("phase") or "?"
    tokens_in, tokens_out, agents = Counter(), Counter(), Counter()
    for transcript in run.glob("agent-*.jsonl"):
        phase = phase_of.get(transcript.stem.removeprefix("agent-"), "?")
        agents[phase] += 1
        for line in transcript.read_text().splitlines():
            try:
                message = json.loads(line).get("message")
            except json.JSONDecodeError:
                continue
            usage = message.get("usage") if isinstance(message, dict) else None
            if usage:
                tokens_in[phase] += (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
                tokens_out[phase] += usage.get("output_tokens", 0)
    total = sum(tokens_in.values()) + sum(tokens_out.values())
    print(f"{'phase':<10} {'agents':>6} {'input':>8} {'output':>8} {'share':>6}")
    for phase in sorted(agents, key=lambda p: -(tokens_in[p] + tokens_out[p])):
        both = tokens_in[phase] + tokens_out[phase]
        print(
            f"{phase:<10} {agents[phase]:>6} {tokens_in[phase] / 1e6:>7.2f}M"
            f" {tokens_out[phase] / 1e3:>7.1f}k {both / total:>6.0%}"
        )
    print(f"{'total':<10} {sum(agents.values()):>6} {total / 1e6:>7.2f}M")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        sys.exit(64)
    sys.exit(main(sys.argv[1]))
