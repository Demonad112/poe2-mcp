"""
Path of Exile 2 Attack (weapon-based) DPS Calculator

Companion to spell_dps_calculator.py for skills that scale off weapon
damage instead of an innate spell base (bow/melee attacks such as
Tornado Shot, Ice Shot, Snipe). Same canonical formula shape as the
spell calculator - weapon damage stands in for spell base damage, and
"damage effectiveness" (the skill's % of weapon damage per hit) plays
the same role spell.damage_effectiveness plays for the added-damage
term - so the two calculators share EnemyStats and the crit/increased/
more/resistance machinery is mirrored rather than duplicated by import.

Formula (see src/calculator/spell_dps_calculator.py for the identical
spell-side derivation):
    Final Damage = (WeaponDamage + Added) x Effectiveness
                   x (1 + SIncreased) x Pi(1 + More)
                   x CritMultiplier x (1 - EffectiveRes)
    DPS = Final Damage x AttacksPerSecond

Damage effectiveness / attack-speed-multiplier source: PathOfBuilding-
PoE2's extracted skill data (data/game/skill_gems/skill_gems_v2.json,
`levels[N].baseMultiplier` / `levels[N].attackSpeedMultiplier`) - see
v2_spell_db.resolve_attack_from_v2. Weapon damage and attack speed
themselves are NOT in that file; the caller (analyze_character /
inspect_base_item) supplies them.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

from .spell_dps_calculator import EnemyStats

logger = logging.getLogger(__name__)


@dataclass
class WeaponDamageRange:
    """One weapon's flat damage roll for a single damage type, min/max."""

    min_damage: float = 0.0
    max_damage: float = 0.0

    @property
    def average(self) -> float:
        return (self.min_damage + self.max_damage) / 2.0


@dataclass
class WeaponStats:
    """Aggregated weapon damage the attack skill scales off of.

    All fields default to zero-damage ranges so a caller only needs to
    populate the damage types their weapon actually rolls (usually just
    physical, plus any added elemental mods already on the weapon
    itself - added-from-gear/tree elemental damage belongs in
    AttackModifiers.added_*, not here).
    """

    physical: WeaponDamageRange = None
    fire: WeaponDamageRange = None
    cold: WeaponDamageRange = None
    lightning: WeaponDamageRange = None
    chaos: WeaponDamageRange = None
    attacks_per_second: float = 1.0  # base weapon APS (local attack speed already rolled in)

    def __post_init__(self) -> None:
        for field_name in ("physical", "fire", "cold", "lightning", "chaos"):
            if getattr(self, field_name) is None:
                setattr(self, field_name, WeaponDamageRange())

    def average_by_type(self) -> Dict[str, float]:
        return {
            "physical": self.physical.average,
            "fire": self.fire.average,
            "cold": self.cold.average,
            "lightning": self.lightning.average,
            "chaos": self.chaos.average,
        }


@dataclass
class AttackStats:
    """Attack-skill base statistics (the weapon-attack analogue of SpellStats)."""

    name: str
    damage_effectiveness: float = 1.0  # skill's baseMultiplier - 0.95 = 95% of weapon damage
    attack_speed_multiplier: float = 0.0  # skill-innate %inc/dec attack speed (e.g. Ice Shot -10)
    damage_types: List[str] = None  # primary type first, e.g. ['physical', 'cold']

    def __post_init__(self) -> None:
        if self.damage_types is None:
            self.damage_types = ["physical"]


@dataclass
class AttackModifiers:
    """Character damage modifiers for a weapon attack.

    Mirrors CharacterModifiers in spell_dps_calculator.py field-for-field
    except cast->attack naming and no Archmage (spell-only mechanic).
    """

    increased_attack_damage: float = 0.0
    increased_attack_speed: float = 0.0
    increased_crit_damage: float = 0.0

    more_multipliers: List[float] = None

    added_fire: float = 0.0
    added_cold: float = 0.0
    added_lightning: float = 0.0
    added_chaos: float = 0.0
    added_physical: float = 0.0

    added_crit_bonus: float = 100.0  # PoE2 base: +100%
    increased_crit_chance: float = 0.0
    base_crit_chance: float = 5.0  # PoE2 default weapon/global base

    def __post_init__(self) -> None:
        if self.more_multipliers is None:
            self.more_multipliers = []


class AttackDPSCalculator:
    """
    Calculates weapon-attack DPS using the same canonical PoE2 formula
    shape as SpellDPSCalculator, substituting weapon damage for spell
    base damage and an attack rate for cast rate.
    """

    def calculate_dps(
        self,
        weapon: WeaponStats,
        attack: AttackStats,
        char_mods: AttackModifiers,
        enemy: Optional[EnemyStats] = None,
    ) -> Dict[str, Any]:
        """Calculate complete attack DPS.

        Args:
            weapon: Weapon damage ranges + base attacks-per-second
            attack: Skill's damage effectiveness / attack-speed multiplier
            char_mods: Aggregated character modifiers
            enemy: Enemy defensive stats (if None, assumes a target dummy)

        Returns:
            Dictionary with DPS breakdown, same shape as
            SpellDPSCalculator.calculate_dps for a consistent tool response.
        """
        if enemy is None:
            enemy = EnemyStats()

        try:
            # Step 1: weapon damage average, by type
            weapon_by_type = weapon.average_by_type()
            base_damage = sum(weapon_by_type.values())

            # Step 2: added flat damage, scaled by the skill's damage
            # effectiveness exactly like weapon damage (effectiveness
            # scales everything the skill deals, not just the weapon roll)
            added_damage = self._calculate_added_damage(attack, char_mods)

            # Step 3: damage effectiveness applied to weapon + added damage together
            total_base_damage = (base_damage + added_damage) * attack.damage_effectiveness

            # Step 4: increased (additive sum)
            increased_multiplier = 1.0 + (char_mods.increased_attack_damage / 100.0)
            damage_after_increased = total_base_damage * increased_multiplier

            # Step 5: more (multiplicative stack)
            more_multiplier = self._calculate_more_multiplier(char_mods.more_multipliers)
            damage_after_more = damage_after_increased * more_multiplier

            # Step 6: crit-weighted expected hit (identical formula to spells - PoE2
            # crit is a flat system-wide mechanic, not spell/attack specific)
            crit_chance = (
                min(char_mods.base_crit_chance + char_mods.increased_crit_chance, 100.0) / 100.0
            )
            crit_multiplier = self._calculate_crit_multiplier(
                char_mods.added_crit_bonus, char_mods.increased_crit_damage
            )
            non_crit_damage = damage_after_more * (1.0 - crit_chance)
            crit_damage = damage_after_more * crit_multiplier * crit_chance
            expected_hit_damage = non_crit_damage + crit_damage

            # Step 7: resistances (reuses the same primary-damage-type
            # simplification the spell calculator uses)
            damage_after_resistance = self._apply_resistances(
                expected_hit_damage, attack.damage_types, enemy
            )
            if enemy.is_shocked:
                damage_after_resistance *= 1.2

            # Step 8: attacks per second
            attacks_per_second = self._calculate_attack_speed(
                weapon.attacks_per_second,
                attack.attack_speed_multiplier,
                char_mods.increased_attack_speed,
            )
            dps = damage_after_resistance * attacks_per_second

            return {
                "total_dps": round(dps, 2),
                "average_hit": round(damage_after_resistance, 2),
                "attacks_per_second": round(attacks_per_second, 3),
                "crit_chance": round(crit_chance * 100, 2),
                "breakdown": {
                    "weapon_damage_by_type": {k: round(v, 2) for k, v in weapon_by_type.items()},
                    "base_damage": round(base_damage, 2),
                    "added_damage": round(added_damage, 2),
                    "after_effectiveness": round(
                        base_damage * attack.damage_effectiveness + added_damage, 2
                    ),
                    "after_increased": round(damage_after_increased, 2),
                    "after_more": round(damage_after_more, 2),
                    "expected_hit": round(expected_hit_damage, 2),
                    "after_resistance": round(damage_after_resistance, 2),
                    "multipliers": {
                        "effectiveness": round(attack.damage_effectiveness, 3),
                        "increased": round(increased_multiplier, 3),
                        "more": round(more_multiplier, 3),
                        "crit": round(crit_multiplier, 3) if crit_chance > 0 else 1.0,
                    },
                },
            }

        except Exception as e:
            logger.error(f"Error calculating attack DPS for {attack.name}: {e}", exc_info=True)
            return {
                "total_dps": 0,
                "average_hit": 0,
                "attacks_per_second": 0,
                "error": str(e),
            }

    def _calculate_added_damage(self, attack: AttackStats, char_mods: AttackModifiers) -> float:
        """Sum flat added damage across all types (effectiveness applied by caller)."""
        return (
            char_mods.added_fire
            + char_mods.added_cold
            + char_mods.added_lightning
            + char_mods.added_chaos
            + char_mods.added_physical
        )

    def _calculate_more_multiplier(self, more_multipliers: List[float]) -> float:
        """Identical to SpellDPSCalculator._calculate_more_multiplier - 'more' modifiers
        stack multiplicatively.

        Examples:
            >>> calc = AttackDPSCalculator()
            >>> calc._calculate_more_multiplier([25, 30])
            1.625
        """
        total = 1.0
        for more_percent in more_multipliers:
            total *= 1.0 + more_percent / 100.0
        return total

    def _calculate_crit_multiplier(self, added_crit_bonus: float, increased_crit: float) -> float:
        """Identical to SpellDPSCalculator._calculate_crit_multiplier - PoE2's crit
        system (+100% base bonus) is shared between spells and attacks.

        Examples:
            >>> calc = AttackDPSCalculator()
            >>> calc._calculate_crit_multiplier(100, 0)
            2.0
        """
        total_bonus = added_crit_bonus / 100.0
        increased_mult = 1.0 + (increased_crit / 100.0)
        return 1.0 + (total_bonus * increased_mult)

    def _apply_resistances(
        self, damage: float, damage_types: List[str], enemy: EnemyStats
    ) -> float:
        """Identical resistance/exposure/penetration handling to the spell
        calculator, using the attack's primary (first-listed) damage type.
        """
        if not damage_types:
            return damage

        primary_type = damage_types[0].lower()
        resistance_map = {
            "fire": (enemy.fire_resistance, enemy.fire_exposure, enemy.fire_penetration),
            "cold": (enemy.cold_resistance, enemy.cold_exposure, enemy.cold_penetration),
            "lightning": (
                enemy.lightning_resistance,
                enemy.lightning_exposure,
                enemy.lightning_penetration,
            ),
            "chaos": (enemy.chaos_resistance, 0, 0),
            "physical": (enemy.physical_resistance, 0, 0),
        }
        if primary_type not in resistance_map:
            return damage

        base_res, exposure, penetration = resistance_map[primary_type]
        res_after_exposure = base_res - exposure
        effective_resistance = max(res_after_exposure - penetration, 0.0)
        return damage * (1.0 - effective_resistance / 100.0)

    def _calculate_attack_speed(
        self,
        weapon_attacks_per_second: float,
        skill_attack_speed_multiplier: float,
        increased_attack_speed: float,
    ) -> float:
        """Combine weapon base APS with the skill's own +/-% and the
        character's aggregated %increased attack speed.

        The skill-innate attack_speed_multiplier (from
        levels[N].attackSpeedMultiplier in the v2 extraction - e.g. Ice
        Shot -10, Snipe -55) is treated as one more additive term in the
        same increased/decreased stack, matching how such skill-specific
        speed modifiers are conventionally described (additive with
        other %increased attack speed sources), since PathOfBuilding-
        PoE2's exact internal handling of this field could not be
        verified line-by-line for this change.

        Examples:
            >>> calc = AttackDPSCalculator()
            >>> round(calc._calculate_attack_speed(1.5, 0, 20), 3)
            1.8
        """
        total_increased = 1.0 + ((skill_attack_speed_multiplier + increased_attack_speed) / 100.0)
        return max(weapon_attacks_per_second * total_increased, 0.0)
