"""
Spell base-stats lookup against data/game/skill_gems/skill_gems_v2.json.

Bridges the rich v2 extraction (PR #125, Issue #119) to the SpellStats
dataclass consumed by SpellDPSCalculator. Lets calculate_character_dps
cover ~1,249 spells instead of the 3 hardcoded ones in SPELL_DATABASE.

Lightweight module - no SQLAlchemy, no MCP imports - so unit tests run
without paying the gem_synergy_calculator / mcp_server import cost.

Heuristics, not perfect translation: the v2 statSet schema is rich but
heterogeneous, and not every spell stores its base damage in the same
positions. This module covers the common spell pattern where the first
two stats in `statSets[0].stats` are spell_minimum_base_X_damage /
spell_maximum_base_X_damage. Spells with other layouts (channeled
attacks, percent-of-weapon, etc.) return None - the caller should fall
back to its existing SPELL_DATABASE or accept a spell_stats override.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Damage-type tags from PoB's skillTypes table that map to a single
# canonical damage type for the SpellStats.damage_types field.
SKILLTYPE_TO_DAMAGE_TYPE: Dict[str, str] = {
    "Cold": "cold",
    "Fire": "fire",
    "Lightning": "lightning",
    "Chaos": "chaos",
    "Physical": "physical",
}


def _skill_gems_v2_path() -> Path:
    """Resolve data/game/skill_gems/skill_gems_v2.json relative to repo root."""
    # src/calculator/v2_spell_db.py -> repo root
    return (
        Path(__file__).resolve().parent.parent.parent
        / "data"
        / "game"
        / "skill_gems"
        / "skill_gems_v2.json"
    )


# Module-level cache so repeated lookups don't re-read the 7.9 MB file.
_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _load_v2_skills() -> Dict[str, Dict[str, Any]]:
    """Read skill_gems_v2.json once and cache. Returns {} on any failure."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    p = _skill_gems_v2_path()
    if not p.exists():
        _CACHE = {}
        return _CACHE
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        _CACHE = data.get("skills", {}) or {}
    except Exception as e:
        logger.warning(f"Failed to load skill_gems_v2.json: {e}")
        _CACHE = {}
    return _CACHE


def _find_skill(
    needle: str, skills: Dict[str, Dict[str, Any]]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Look up a skill by display name or skill_id (case-insensitive)."""
    if not needle:
        return None
    n = needle.strip().lower()
    # Exact name match first
    for sid, rec in skills.items():
        if (rec.get("name") or "").lower() == n:
            return sid, rec
    # Exact id match
    if needle in skills:
        return needle, skills[needle]
    for sid, rec in skills.items():
        if sid.lower() == n:
            return sid, rec
    # Substring on name
    for sid, rec in skills.items():
        if n in (rec.get("name") or "").lower():
            return sid, rec
    return None


def _derive_damage_types(skill_record: Dict[str, Any]) -> List[str]:
    """Extract canonical damage-type strings from a v2 record's skillTypes."""
    types = skill_record.get("skillTypes")
    out: List[str] = []
    if isinstance(types, list):
        for t in types:
            mapped = SKILLTYPE_TO_DAMAGE_TYPE.get(t)
            if mapped and mapped not in out:
                out.append(mapped)
    elif isinstance(types, dict):
        for k in types.keys():
            mapped = SKILLTYPE_TO_DAMAGE_TYPE.get(k)
            if mapped and mapped not in out:
                out.append(mapped)
    return out


def _derive_damage_range(
    statset: Dict[str, Any], level_index: int
) -> Optional[Tuple[float, float]]:
    """Try to pull (min, max) base damage from a statSet's per-level entry.

    The common spell pattern is:
        statSets[0].stats = ["spell_minimum_base_X_damage", "spell_maximum_base_X_damage", ...]
        statSets[0].levels[N] = {"1": <min>, "2": <max>, ...other positional stats...}

    where the "1" / "2" string keys are the stringified Lua positional
    indices that pair with the stats string list. Returns None when the
    layout doesn't match (caller falls back to SPELL_DATABASE or
    spell_stats override).
    """
    stats_list = statset.get("stats")
    if not isinstance(stats_list, list) or len(stats_list) < 2:
        return None

    # Confirm first two stats look like the spell-damage pair
    s0 = (stats_list[0] or "").lower()
    s1 = (stats_list[1] or "").lower()
    if not (("minimum" in s0 and "damage" in s0) and ("maximum" in s1 and "damage" in s1)):
        return None

    levels = statset.get("levels")
    if not isinstance(levels, list) or not levels:
        return None
    idx = max(0, min(level_index, len(levels) - 1))
    entry = levels[idx]
    if not isinstance(entry, dict):
        return None
    try:
        dmin = float(entry["1"])
        dmax = float(entry["2"])
    except (KeyError, ValueError, TypeError):
        return None
    return dmin, dmax


def get_v2_skill_record(spell_name: str) -> Optional[Dict[str, Any]]:
    """Return the FULL v2 record for a spell, or None when unresolved.

    Where resolve_spell_from_v2 derives a flat SpellStats-kwargs dict
    for the DPS calculator, this returns the raw record: castTime,
    skillTypes, qualityStats, the full levels[] array, and statSets[]
    with their constantStats + per-level damage arrays.

    Used by inspect_spell_gem to surface the rich v2 data when a spell
    is present in the canonical extraction. Returns None when the v2
    file is absent or the spell can't be resolved by name/skill_id/
    substring (matching the lookup semantics of resolve_spell_from_v2).
    """
    skills = _load_v2_skills()
    if not skills:
        return None
    found = _find_skill(spell_name, skills)
    if not found:
        return None
    skill_id, record = found
    # Return a copy with the resolved skill_id stamped on so callers
    # don't lose the key context after the lookup.
    out = dict(record)
    out["_v2_skill_id"] = skill_id
    return out


def resolve_attack_from_v2(skill_name: str, gem_level: int = 20) -> Optional[Dict[str, Any]]:
    """Look up a weapon-attack skill in skill_gems_v2.json and derive
    AttackStats-shaped kwargs, for skills that scale off weapon damage
    (Tornado Shot, Ice Shot, Snipe, ...) rather than an innate spell
    base. Companion to resolve_spell_from_v2 - see that function's
    docstring for the general lookup semantics (name/skill_id/substring,
    case-insensitive).

    Attack skills don't carry min/max base damage in their statSets the
    way spells do; instead `record.levels[N]` carries:
      - baseMultiplier: the skill's damage effectiveness (% of weapon
        damage per hit, e.g. 0.95 = 95%, 4.14 = 414%)
      - attackSpeedMultiplier: a skill-innate +/-% attack speed modifier
        (e.g. Ice Shot -10, Snipe -55)

    Args:
        skill_name: User-supplied skill name (e.g. "Ice Shot") or skill_id.
        gem_level: 1-indexed gem level. Defaults to 20.

    Returns:
        Dict shaped for ``AttackStats(**resolve_attack_from_v2(...))``
        (after popping `_v2_meta`):
          {name, damage_effectiveness, attack_speed_multiplier,
           damage_types, _v2_meta: {skill_id, gem_level, source}}

        Returns None when:
          - skill_gems_v2.json is absent
          - skill_name doesn't resolve to any record
          - the resolved level entry has no baseMultiplier (e.g. Snipe's
            gem level 1, or a non-attack/spell skill) - the caller should
            fall back to spell_stats-style overrides for these.
    """
    skills = _load_v2_skills()
    if not skills:
        return None

    found = _find_skill(skill_name, skills)
    if not found:
        return None
    skill_id, record = found

    record_levels = record.get("levels")
    if not isinstance(record_levels, list) or not record_levels:
        return None
    level_idx = max(0, min(gem_level - 1, len(record_levels) - 1))
    lvl_entry = record_levels[level_idx]
    if not isinstance(lvl_entry, dict) or "baseMultiplier" not in lvl_entry:
        return None

    try:
        damage_effectiveness = float(lvl_entry["baseMultiplier"])
    except (ValueError, TypeError):
        return None
    try:
        attack_speed_multiplier = float(lvl_entry.get("attackSpeedMultiplier", 0) or 0)
    except (ValueError, TypeError):
        attack_speed_multiplier = 0.0

    damage_types = _derive_damage_types(record)
    if "physical" not in damage_types:
        damage_types = ["physical"] + damage_types

    return {
        "name": record.get("name") or skill_name,
        "damage_effectiveness": damage_effectiveness,
        "attack_speed_multiplier": attack_speed_multiplier,
        "damage_types": damage_types,
        "_v2_meta": {
            "skill_id": skill_id,
            "gem_level": gem_level,
            "source": "data/game/skill_gems/skill_gems_v2.json",
        },
    }


def resolve_spell_from_v2(spell_name: str, gem_level: int = 20) -> Optional[Dict[str, Any]]:
    """Look up a spell in skill_gems_v2.json and derive SpellStats-shaped dict.

    Args:
        spell_name: User-supplied spell name (e.g. "Ice Nova") or skill_id.
        gem_level: 1-indexed gem level. Defaults to 20 (PoB's "natural max"
            for most player skills).

    Returns:
        Dict with the same shape as SpellStats's __init__ kwargs, suitable
        for ``SpellStats(**resolve_spell_from_v2(...))``:

          {name, base_damage_min, base_damage_max, damage_effectiveness,
           base_crit_chance, base_cast_time, damage_types,
           _v2_meta: {skill_id, statset_label, gem_level, source}}

        Returns None when:
          - skill_gems_v2.json is absent (extractor hasn't run)
          - spell_name doesn't resolve to any record
          - the spell's statSet layout doesn't match the
            min/max-damage-pair pattern this helper handles
    """
    skills = _load_v2_skills()
    if not skills:
        return None

    found = _find_skill(spell_name, skills)
    if not found:
        return None
    skill_id, record = found

    statsets = record.get("statSets")
    if not isinstance(statsets, list) or not statsets:
        return None

    # gem_level is 1-indexed; level array is 0-indexed.
    level_idx = max(0, gem_level - 1)

    dmg = None
    chosen_statset = None
    for ss in statsets:
        dmg = _derive_damage_range(ss, level_idx)
        if dmg is not None:
            chosen_statset = ss
            break
    if dmg is None or chosen_statset is None:
        return None
    dmin, dmax = dmg

    # crit chance lives on the gem-level entry (record.levels[N].critChance)
    base_crit_chance = 0.0
    record_levels = record.get("levels")
    if isinstance(record_levels, list) and record_levels:
        idx = max(0, min(level_idx, len(record_levels) - 1))
        lvl_entry = record_levels[idx]
        if isinstance(lvl_entry, dict):
            try:
                base_crit_chance = float(lvl_entry.get("critChance", 0) or 0)
            except (ValueError, TypeError):
                base_crit_chance = 0.0

    base_cast_time = float(record.get("castTime") or 1.0)
    damage_types = _derive_damage_types(record)

    # damage_effectiveness: not directly in v2 schema; PoB uses
    # baseEffectiveness as a damage-scaling multiplier applied alongside
    # this. Default to 1.0 here and let the caller override if they need
    # a different effective ratio.
    damage_effectiveness = 1.0

    return {
        "name": record.get("name") or spell_name,
        "base_damage_min": dmin,
        "base_damage_max": dmax,
        "damage_effectiveness": damage_effectiveness,
        "base_crit_chance": base_crit_chance,
        "base_cast_time": base_cast_time,
        "damage_types": damage_types,
        "_v2_meta": {
            "skill_id": skill_id,
            "statset_label": chosen_statset.get("label"),
            "gem_level": gem_level,
            "source": "data/game/skill_gems/skill_gems_v2.json",
        },
    }
