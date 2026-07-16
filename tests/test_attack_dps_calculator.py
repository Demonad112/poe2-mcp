"""
Tests for src/calculator/attack_dps_calculator.py.

Weapon-attack DPS pipeline (bow/melee skills like Tornado Shot, Ice Shot,
Snipe) — same canonical PoE2 formula shape as spell_dps_calculator.py,
with weapon damage standing in for spell base damage and an attack rate
standing in for cast rate. See that module's test file for the shared
crit/more/resistance math this mirrors.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calculator.attack_dps_calculator import (
    AttackDPSCalculator,
    AttackModifiers,
    AttackStats,
    WeaponDamageRange,
    WeaponStats,
)
from src.calculator.spell_dps_calculator import EnemyStats


@pytest.fixture
def calc():
    return AttackDPSCalculator()


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------


def test_weapon_stats_defaults_to_zero_damage_ranges():
    w = WeaponStats()
    assert w.physical.average == 0.0
    assert w.fire.average == 0.0
    assert w.attacks_per_second == 1.0


def test_weapon_damage_range_average():
    assert WeaponDamageRange(min_damage=20, max_damage=40).average == 30.0


def test_weapon_stats_average_by_type_covers_all_five():
    w = WeaponStats(physical=WeaponDamageRange(10, 20), cold=WeaponDamageRange(4, 6))
    avg = w.average_by_type()
    assert avg == {"physical": 15.0, "fire": 0.0, "cold": 5.0, "lightning": 0.0, "chaos": 0.0}


def test_attack_stats_defaults():
    a = AttackStats(name="X")
    assert a.damage_effectiveness == 1.0
    assert a.attack_speed_multiplier == 0.0
    assert a.damage_types == ["physical"]


def test_attack_modifiers_defaults_match_poe2_baseline():
    m = AttackModifiers()
    assert m.more_multipliers == []
    assert m.added_crit_bonus == 100.0
    assert m.base_crit_chance == 5.0


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------


def test_basic_dps_no_modifiers(calc):
    """30 avg weapon phys damage, 100% effectiveness, no crit, 1 APS -> 30 DPS flat."""
    weapon = WeaponStats(physical=WeaponDamageRange(20, 40), attacks_per_second=1.0)
    attack = AttackStats(name="Test Attack", damage_effectiveness=1.0)
    mods = AttackModifiers(base_crit_chance=0.0)
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    assert result["average_hit"] == 30.0
    assert result["attacks_per_second"] == 1.0
    assert result["total_dps"] == 30.0


def test_damage_effectiveness_scales_weapon_damage(calc):
    """Ice Shot-shaped: 0.95 effectiveness on 100 avg weapon damage -> 95 base hit."""
    weapon = WeaponStats(physical=WeaponDamageRange(80, 120), attacks_per_second=1.0)
    attack = AttackStats(name="Ice Shot", damage_effectiveness=0.95)
    mods = AttackModifiers(base_crit_chance=0.0)
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    assert result["average_hit"] == 95.0


def test_added_damage_scaled_by_effectiveness_like_spells(calc):
    """Added flat damage is scaled by damage_effectiveness together with
    weapon damage, matching SpellDPSCalculator's precedent (effectiveness
    scales everything the skill deals, not just the weapon roll)."""
    weapon = WeaponStats(physical=WeaponDamageRange(0, 0), attacks_per_second=1.0)
    attack = AttackStats(name="Test", damage_effectiveness=0.5)
    mods = AttackModifiers(added_fire=100, base_crit_chance=0.0)
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    assert result["average_hit"] == 50.0  # 100 added * 0.5 effectiveness


def test_increased_and_more_stack_correctly(calc):
    weapon = WeaponStats(physical=WeaponDamageRange(100, 100), attacks_per_second=1.0)
    attack = AttackStats(name="Test", damage_effectiveness=1.0)
    mods = AttackModifiers(
        increased_attack_damage=50, more_multipliers=[20, 10], base_crit_chance=0.0
    )
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    # 100 * 1.5 (increased) * 1.2 * 1.1 (more) = 198.0
    assert result["average_hit"] == pytest.approx(198.0)


def test_crit_chance_is_clamped_and_weighted(calc):
    weapon = WeaponStats(physical=WeaponDamageRange(100, 100), attacks_per_second=1.0)
    attack = AttackStats(name="Test", damage_effectiveness=1.0)
    mods = AttackModifiers(base_crit_chance=100.0, added_crit_bonus=100.0)  # PoE2: 2x on crit
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    assert result["crit_chance"] == 100.0
    assert result["average_hit"] == 200.0  # always crits at 2x


def test_attack_speed_combines_weapon_skill_and_increased(calc):
    """1.5 base APS, Ice-Shot-shaped -10% skill modifier, +20% increased -> 1.5 * 1.1."""
    weapon = WeaponStats(physical=WeaponDamageRange(10, 10), attacks_per_second=1.5)
    attack = AttackStats(name="Ice Shot", damage_effectiveness=1.0, attack_speed_multiplier=-10)
    mods = AttackModifiers(increased_attack_speed=20, base_crit_chance=0.0)
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    assert result["attacks_per_second"] == pytest.approx(1.5 * 1.1)


def test_resistance_applies_to_primary_damage_type(calc):
    weapon = WeaponStats(physical=WeaponDamageRange(100, 100), attacks_per_second=1.0)
    attack = AttackStats(name="Test", damage_effectiveness=1.0, damage_types=["physical"])
    mods = AttackModifiers(base_crit_chance=0.0)
    enemy = EnemyStats(physical_resistance=50.0)
    result = calc.calculate_dps(weapon, attack, mods, enemy)
    assert result["average_hit"] == 50.0


def test_breakdown_reports_weapon_damage_by_type(calc):
    weapon = WeaponStats(
        physical=WeaponDamageRange(10, 20), cold=WeaponDamageRange(5, 5), attacks_per_second=1.0
    )
    attack = AttackStats(name="Test", damage_effectiveness=1.0)
    mods = AttackModifiers(base_crit_chance=0.0)
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    by_type = result["breakdown"]["weapon_damage_by_type"]
    assert by_type["physical"] == 15.0
    assert by_type["cold"] == 5.0


def test_zero_weapon_attacks_per_second_yields_zero_dps(calc):
    weapon = WeaponStats(physical=WeaponDamageRange(100, 100), attacks_per_second=0.0)
    attack = AttackStats(name="Test", damage_effectiveness=1.0)
    mods = AttackModifiers(base_crit_chance=0.0)
    result = calc.calculate_dps(weapon, attack, mods, EnemyStats())
    assert result["attacks_per_second"] == 0.0
    assert result["total_dps"] == 0.0
