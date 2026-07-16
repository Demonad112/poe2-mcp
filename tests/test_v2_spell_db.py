"""
Tests for the v2 spell-DB lookup that bridges skill_gems_v2.json (#119)
to SpellStats for calculate_character_dps (#114). Closes the follow-up
mentioned in PR #125 (expansion from 3 hardcoded spells to ~1,249).

Light-module pattern: src/calculator/v2_spell_db.py imports only json /
logging / pathlib, so these tests run instantly without pulling MCP /
SQLAlchemy / calculator dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calculator.v2_spell_db import (  # noqa: E402
    SKILLTYPE_TO_DAMAGE_TYPE,
    resolve_attack_from_v2,
    resolve_spell_from_v2,
)

V2_FILE = PROJECT_ROOT / "data" / "game" / "skill_gems" / "skill_gems_v2.json"
needs_v2 = pytest.mark.skipif(
    not V2_FILE.exists(),
    reason="data/game/skill_gems/skill_gems_v2.json not present "
    "(depends on PR #125 - run extractor + commit before testing).",
)


# ---------------------------------------------------------------------------
# Real-data lookups (skip when v2 file isn't shipped)
# ---------------------------------------------------------------------------


@needs_v2
def test_resolve_ice_nova_by_name():
    r = resolve_spell_from_v2("Ice Nova")
    assert r is not None
    assert r["name"] == "Ice Nova"
    assert r["base_damage_min"] > 0
    assert r["base_damage_max"] > r["base_damage_min"]
    # Ice Nova is a cold spell
    assert "cold" in r["damage_types"]


@needs_v2
def test_resolve_ice_nova_by_skill_id():
    r = resolve_spell_from_v2("IceNovaPlayer")
    assert r is not None
    assert r["name"] == "Ice Nova"


@needs_v2
def test_resolve_fireball_returns_fire_type():
    r = resolve_spell_from_v2("Fireball")
    assert r is not None
    assert "fire" in r["damage_types"]
    # Fireball at level 20 deals more damage than at level 1
    r20 = resolve_spell_from_v2("Fireball", gem_level=20)
    r1 = resolve_spell_from_v2("Fireball", gem_level=1)
    assert r20["base_damage_max"] > r1["base_damage_max"]


@needs_v2
def test_resolve_spark_returns_lightning_type():
    r = resolve_spell_from_v2("Spark")
    assert r is not None
    assert "lightning" in r["damage_types"]


@needs_v2
def test_resolve_unknown_spell_returns_none():
    assert resolve_spell_from_v2("NotARealSpellAtAll") is None
    assert resolve_spell_from_v2("") is None


@needs_v2
def test_resolve_includes_v2_meta():
    r = resolve_spell_from_v2("Ice Nova")
    assert r is not None
    meta = r.get("_v2_meta")
    assert meta is not None
    assert meta["skill_id"] == "IceNovaPlayer"
    assert "skill_gems_v2" in meta["source"]
    assert meta["gem_level"] == 20


@needs_v2
def test_gem_level_clamps_at_array_bounds():
    """Asking for level 999 should not crash; clamps to last available."""
    r = resolve_spell_from_v2("Ice Nova", gem_level=999)
    assert r is not None
    # Should match the last level's damage
    r_last = resolve_spell_from_v2("Ice Nova", gem_level=40)
    assert r["base_damage_max"] == r_last["base_damage_max"]


@needs_v2
def test_gem_level_1_returns_low_damage():
    """Level 1 should return modest base damage (not zero, not max-level)."""
    r1 = resolve_spell_from_v2("Ice Nova", gem_level=1)
    r20 = resolve_spell_from_v2("Ice Nova", gem_level=20)
    assert r1 is not None and r20 is not None
    assert 0 < r1["base_damage_max"] < r20["base_damage_max"]


@needs_v2
def test_crit_chance_pulled_from_per_level_entry():
    """critChance lives on record.levels[N].critChance, not on the spell."""
    r = resolve_spell_from_v2("Ice Nova")
    assert r is not None
    # Ice Nova has 12% crit chance at all levels per the data file
    assert r["base_crit_chance"] == 12.0


@needs_v2
def test_cast_time_preserved():
    r = resolve_spell_from_v2("Ice Nova")
    assert r is not None
    # Ice Nova's castTime is 1.0 in the data
    assert r["base_cast_time"] == 1.0


# ---------------------------------------------------------------------------
# Schema vocab
# ---------------------------------------------------------------------------


def test_skilltype_mapping_covers_all_elements():
    """The damage-type mapping should handle the 5 PoE damage types."""
    expected = {"fire", "cold", "lightning", "chaos", "physical"}
    actual = set(SKILLTYPE_TO_DAMAGE_TYPE.values())
    assert expected.issubset(actual)


def test_skilltype_keys_are_titlecase():
    """PoB's SkillType.X names are TitleCase (Cold, Fire, ...) - mapping
    must use the same casing as our extractor produces."""
    for k in SKILLTYPE_TO_DAMAGE_TYPE.keys():
        assert k[0].isupper(), f"SkillType key {k!r} should be TitleCase"


def test_resolve_returns_none_when_v2_file_absent(tmp_path, monkeypatch):
    """When the v2 file path doesn't exist, returns None gracefully (not
    a crash) — same behavior as a fresh checkout before extraction."""
    import src.calculator.v2_spell_db as mod

    # Point the helper at a non-existent path
    fake = tmp_path / "definitely_not_there.json"
    monkeypatch.setattr(mod, "_skill_gems_v2_path", lambda: fake)
    monkeypatch.setattr(mod, "_CACHE", None)

    assert resolve_spell_from_v2("Ice Nova") is None


# ---------------------------------------------------------------------------
# resolve_attack_from_v2 — weapon-attack skills (bow/melee), companion to
# resolve_spell_from_v2 for skills with no innate spell base damage.
# ---------------------------------------------------------------------------


@needs_v2
def test_resolve_ice_shot_by_name():
    r = resolve_attack_from_v2("Ice Shot", gem_level=20)
    assert r is not None
    assert r["name"] == "Ice Shot"
    assert r["damage_effectiveness"] > 1.0  # Ice Shot scales well past 100% by lvl 20
    assert "physical" in r["damage_types"]
    assert "cold" in r["damage_types"]


@needs_v2
def test_resolve_ice_shot_by_skill_id():
    r = resolve_attack_from_v2("IceShotPlayer", gem_level=1)
    assert r is not None
    assert r["name"] == "Ice Shot"


@needs_v2
def test_resolve_tornado_shot_has_baseMultiplier_derived_effectiveness():
    r = resolve_attack_from_v2("Tornado Shot", gem_level=20)
    assert r is not None
    assert r["damage_effectiveness"] > 0
    assert r["damage_types"][0] == "physical"


@needs_v2
def test_resolve_snipe_gem_level_1_has_no_basemultiplier():
    """Snipe's gem_level=1 entry (levels[0]) carries no baseMultiplier
    (it's the channel-charge tier) — must return None, not crash, so the
    MCP handler can fall back to attack_stats."""
    r = resolve_attack_from_v2("Snipe", gem_level=1)
    assert r is None


@needs_v2
def test_resolve_snipe_gem_level_20_has_basemultiplier():
    r = resolve_attack_from_v2("Snipe", gem_level=20)
    assert r is not None
    assert r["damage_effectiveness"] > 0


@needs_v2
def test_resolve_attack_damage_types_always_leads_with_physical():
    """Weapon-attack hits are physical-primary by convention here, even
    when the gem also carries an elemental skillType tag (e.g. Ice
    Shot's Cold tag) — resistance math uses damage_types[0]."""
    r = resolve_attack_from_v2("Ice Shot", gem_level=20)
    assert r is not None
    assert r["damage_types"][0] == "physical"


def test_resolve_attack_returns_none_for_unknown_skill():
    assert resolve_attack_from_v2("Definitely Not A Real Skill Name") is None


def test_resolve_attack_returns_none_when_v2_file_absent(tmp_path, monkeypatch):
    import src.calculator.v2_spell_db as mod

    fake = tmp_path / "definitely_not_there.json"
    monkeypatch.setattr(mod, "_skill_gems_v2_path", lambda: fake)
    monkeypatch.setattr(mod, "_CACHE", None)

    assert resolve_attack_from_v2("Ice Shot") is None
