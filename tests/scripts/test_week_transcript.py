"""scripts/week_transcript.py slices a Claude Code transcript into one ISO week.
The week is bounded by local midnights (the due hook and the week file use the
local date), so the tests pin TZ to a zone with a non-zero UTC offset and place
messages either side of the local Monday midnight, where UTC and local disagree."""

import importlib.util
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts/week_transcript.py"
_NY = ZoneInfo("America/New_York")

# EST (UTC-5) on both sides of the 2026-W45/W46 boundary; DST ended 2026-11-01.
_SUNDAY_LATE = "2026-11-09T03:00:00Z"  # Sun 2026-11-08 22:00 local: W45
_MONDAY_EARLY = "2026-11-09T05:30:00Z"  # Mon 2026-11-09 00:30 local: W46

pytestmark = pytest.mark.skipif(
    not hasattr(time, "tzset"), reason="time.tzset is unavailable on this platform"
)


@pytest.fixture
def new_york(monkeypatch):
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    # monkeypatch restores TZ only after this fixture finishes, so tzset must
    # run against the restored value here, not rely on teardown ordering.
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.fixture
def week_transcript(new_york):
    # Loaded after TZ is set, in case the module resolves the local zone at import.
    spec = importlib.util.spec_from_file_location("week_transcript", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _human(timestamp: str, text: str) -> dict:
    return {
        "type": "user",
        "timestamp": timestamp,
        "origin": {"kind": "human"},
        "message": {"role": "user", "content": text},
    }


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    path = tmp_path / "session.jsonl"
    with path.open("w") as f:
        f.write(json.dumps(_human(_SUNDAY_LATE, "sunday-late-message")) + "\n")
        f.write(json.dumps(_human(_MONDAY_EARLY, "monday-early-message")) + "\n")
    return path


def _texts(module, path: Path, week: str) -> list[str]:
    start, end = module.week_bounds(week)
    return [text for _, text in module.events(path, start, end)]


def _contains(texts: list[str], needle: str) -> bool:
    return any(needle in text for text in texts)


def test_sunday_evening_local_stays_in_its_own_week(week_transcript, transcript):
    # 03:00Z Monday is still Sunday in New York: a UTC week start puts it in W46.
    w45 = _texts(week_transcript, transcript, "2026-W45")
    w46 = _texts(week_transcript, transcript, "2026-W46")
    assert _contains(w45, "sunday-late-message")
    assert not _contains(w46, "sunday-late-message")


def test_monday_after_local_midnight_belongs_to_the_new_week(
    week_transcript, transcript
):
    w45 = _texts(week_transcript, transcript, "2026-W45")
    w46 = _texts(week_transcript, transcript, "2026-W46")
    assert _contains(w46, "monday-early-message")
    assert not _contains(w45, "monday-early-message")


def test_typed_message_is_rendered_as_you_line(week_transcript, transcript):
    w46 = _texts(week_transcript, transcript, "2026-W46")
    assert any(t.startswith("YOU") and "monday-early-message" in t for t in w46)


def test_event_times_are_tz_aware(week_transcript, transcript):
    start, end = week_transcript.week_bounds("2026-W46")
    whens = [when for when, _ in week_transcript.events(transcript, start, end)]
    assert whens
    assert all(when.tzinfo is not None for when in whens)


def test_week_bounds_are_local_monday_midnights(week_transcript):
    start, end = week_transcript.week_bounds("2026-W46")
    assert start.tzinfo is not None and end.tzinfo is not None
    assert start.astimezone(_NY).replace(tzinfo=None) == datetime(2026, 11, 9)
    assert end.astimezone(_NY).replace(tzinfo=None) == datetime(2026, 11, 16)
