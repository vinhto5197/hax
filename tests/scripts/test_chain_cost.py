"""scripts/chain_cost.py totals a feature-chain run's tokens per phase from its
agents' transcripts. Driven as a subprocess with HOME pointed at a tmp dir of
fake transcripts, so the real ~/.claude is never read."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
# The interpreter running the suite: CI has no .venv.
_PY = sys.executable
_SCRIPT = _REPO / "scripts/chain_cost.py"
_PROJECT_DIR = str(_REPO).replace("/", "-")
_RUN = "wf_test-0001"


def _write_run(
    home: Path, transcripts: dict[str, list[dict]], run_id: str = _RUN
) -> None:
    run_dir = (
        home
        / ".claude/projects"
        / _PROJECT_DIR
        / "session-1/subagents/workflows"
        / run_id
    )
    run_dir.mkdir(parents=True)
    with (run_dir / "journal.jsonl").open("w") as journal:
        for i, agent_id in enumerate(transcripts):
            phase = "Build" if i == 0 else "Review"
            journal.write(
                json.dumps({"type": "started", "agentId": agent_id, "phase": phase})
                + "\n"
            )
    for agent_id, lines in transcripts.items():
        with (run_dir / f"agent-{agent_id}.jsonl").open("w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")


def _run(home: Path, run_id: str = _RUN) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "HOME"}
    env["HOME"] = str(home)
    return subprocess.run(
        [str(_PY), str(_SCRIPT), run_id],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _total_row(stdout: str) -> str:
    rows = [
        line
        for line in stdout.splitlines()
        if re.match(r"^\W*total\b", line.strip(), re.I)
    ]
    assert rows, f"no total row in:\n{stdout}"
    return rows[-1]


_USAGE = {
    "input_tokens": 600_000,
    "cache_read_input_tokens": 300_000,
    "cache_creation_input_tokens": 100_000,
    "output_tokens": 7_000,
}


def _assistant(msg_id: str, block: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": msg_id,
            "role": "assistant",
            "content": [block],
            "usage": _USAGE,
        },
    }


def test_one_api_message_split_over_two_lines_is_counted_once(tmp_path):
    text = {"type": "text", "text": "thinking aloud"}
    tool = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}

    split_home = tmp_path / "split"
    _write_run(
        split_home, {"a1": [_assistant("msg_1", text), _assistant("msg_1", tool)]}
    )
    single_home = tmp_path / "single"
    _write_run(single_home, {"a1": [_assistant("msg_1", text)]})
    two_home = tmp_path / "two"
    _write_run(two_home, {"a1": [_assistant("msg_1", text), _assistant("msg_2", tool)]})

    split, single, two = _run(split_home), _run(single_home), _run(two_home)
    for r in (split, single, two):
        assert r.returncode == 0, r.stderr
    assert _total_row(split.stdout) == _total_row(single.stdout)
    assert _total_row(two.stdout) != _total_row(single.stdout), (
        "two distinct messages must count twice"
    )


def test_a_run_with_no_usage_prints_a_zero_total_and_exits_0(tmp_path):
    _write_run(
        tmp_path,
        {
            "a1": [
                {"type": "user", "message": {"role": "user", "content": "go"}},
                {
                    "type": "assistant",
                    "message": {"id": "msg_1", "role": "assistant", "content": []},
                },
            ],
            "a2": [],
        },
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr
    numbers = re.findall(r"\d+(?:[.,]\d+)?", _total_row(r.stdout))
    assert numbers, "the total row carries numbers"
    # A small integer may be the agent count (two agents in the journal); every
    # token figure must be zero.
    tokens = [n for n in numbers if not (n.isdigit() and 0 < int(n) <= 2)]
    assert tokens, "the total row carries a token figure"
    assert all(float(n.replace(",", "")) == 0 for n in tokens)


def test_an_unknown_run_id_exits_1(tmp_path):
    _write_run(
        tmp_path,
        {"a1": [_assistant("msg_1", {"type": "text", "text": "x"})]},
        run_id="wf_other-0002",
    )
    r = _run(tmp_path, run_id="wf_nope-9999")
    assert r.returncode == 1
    empty = tmp_path / "empty-home"
    empty.mkdir()
    assert _run(empty, run_id="wf_nope-9999").returncode == 1
