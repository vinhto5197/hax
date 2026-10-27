"""apps/web/e2e/prepare.py empties and reseeds a database and a Redis db, so the
only thing that keeps it off dev data is its table of targets: each must be a
throwaway database of its own, never `hax`, never another target's."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "apps/web/e2e/prepare.py"


def _load():
    spec = importlib.util.spec_from_file_location("e2e_prepare", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_flag_still_prepares_the_journey_stack():
    prepare = _load()
    target = prepare.parse_target([])
    assert (target.database, target.redis_db) == ("hax_e2e", 15)


def test_the_explorer_target_is_its_own_database_and_redis_db():
    prepare = _load()
    target = prepare.parse_target(["--target", "explorer"])
    assert (target.database, target.redis_db) == ("hax_explorer", 14)
    assert target.owner_url.endswith("/hax_explorer")
    assert target.app_url.endswith("/hax_explorer")
    assert target.redis_url.endswith("/14")


def test_targets_never_share_a_database_or_reach_dev():
    prepare = _load()
    targets = list(prepare.TARGETS.values())
    assert len({t.database for t in targets}) == len(targets)
    assert len({t.redis_db for t in targets}) == len(targets)
    for t in targets:
        assert t.database not in ("hax", "hax_test", "postgres")
        assert t.redis_db != 0


def test_an_unknown_target_is_refused():
    prepare = _load()
    with pytest.raises(SystemExit):
        prepare.parse_target(["--target", "hax"])
