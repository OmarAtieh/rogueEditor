"""
Enhanced Modifier Schema System

Based on comprehensive analysis of OmarAtieh save data revealing 29 unique modifier types
with specific argument patterns and Pokemon ID requirements.

This module provides type-safe modifier creation and validation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, Literal
from enum import Enum

logger = logging.getLogger(__name__)


class ModifierTarget(Enum):
    """Defines whether a modifier targets the trainer or a specific Pokemon."""
    TRAINER = "trainer"  # Affects all party or trainer-wide
    POKEMON = "pokemon"  # Affects specific Pokemon


class ArgumentType(Enum):
    """Types of arguments modifiers can accept."""
    POKEMON_ID = "pokemon_id"
    STAT_TYPE = "stat_type"
    BERRY_TYPE = "berry_type"
    FORM_CHANGE_TYPE = "form_change_type"
    PERCENTAGE = "percentage"
    COUNT = "count"
    BOOLEAN = "boolean"


@dataclass
class ModifierSchema:
    """Schema definition for a modifier type."""
    type_id: str
    class_name: str
    target: ModifierTarget
    description: str
    requires_pokemon_id: bool
    arg_structure: List[ArgumentType]
    has_type_pregen_args: bool
    stack_count_range: tuple[int, int]

    # Based on analysis findings
    frequency_in_saves: int = 0
    example_args: Optional[List[Any]] = None


class EnhancedModifierCatalog:
    """Catalog of all modifier types based on save analysis."""

    def __init__(self):
        self._modifiers = self._build_modifier_catalog()

    def _build_modifier_catalog(self) -> Dict[str, ModifierSchema]:
        """Build the complete modifier catalog based on analysis findings."""

        # Trainer-targeting modifiers (affect all party or trainer-wide)
        trainer_modifiers = {
            # Experience and battle modifiers
            "EXP_CHARM": ModifierSchema(
                type_id="EXP_CHARM",
                class_name="ExpBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Multiplies experience gained from battles",
                requires_pokemon_id=False,
                arg_structure=[ArgumentType.PERCENTAGE],
                has_type_pregen_args=False,
                stack_count_range=(7, 15),
                frequency_in_saves=4,
                example_args=[[25]]
            ),
            "SUPER_EXP_CHARM": ModifierSchema(
                type_id="SUPER_EXP_CHARM",
                class_name="ExpBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Multiplies experience gained from battles (enhanced)",
                requires_pokemon_id=False,
                arg_structure=[ArgumentType.PERCENTAGE],
                has_type_pregen_args=False,
                stack_count_range=(7, 15),
                frequency_in_saves=2,
                example_args=[[60]]
            ),
            "EXP_SHARE": ModifierSchema(
                type_id="EXP_SHARE",
                class_name="ExpShareModifier",
                target=ModifierTarget.TRAINER,
                description="Distributes experience to all party members",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(5, 5),
                frequency_in_saves=3,
                example_args=[None]
            ),

            # Battle encounter modifiers
            "SUPER_LURE": ModifierSchema(
                type_id="SUPER_LURE",
                class_name="DoubleBattleChanceBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Increases the odds of encountering a double battle",
                requires_pokemon_id=False,
                arg_structure=[ArgumentType.PERCENTAGE, ArgumentType.COUNT],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[15, 8]]
            ),
            "MAX_LURE": ModifierSchema(
                type_id="MAX_LURE",
                class_name="DoubleBattleChanceBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Significantly increases double battle encounter odds",
                requires_pokemon_id=False,
                arg_structure=[ArgumentType.PERCENTAGE, ArgumentType.COUNT],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[30, 4]]
            ),

            # Utility and access modifiers
            "IV_SCANNER": ModifierSchema(
                type_id="IV_SCANNER",
                class_name="IvScannerModifier",
                target=ModifierTarget.TRAINER,
                description="Reveals individual values of Pokemon",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[None]
            ),
            "MAP": ModifierSchema(
                type_id="MAP",
                class_name="MapModifier",
                target=ModifierTarget.TRAINER,
                description="Provides access to map functionality",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[None]
            ),
            "GOLDEN_POKEBALL": ModifierSchema(
                type_id="GOLDEN_POKEBALL",
                class_name="ExtraModifierModifier",
                target=ModifierTarget.TRAINER,
                description="Increases available modifier slots",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(2, 3),
                frequency_in_saves=3,
                example_args=[None]
            ),

            # Evolution and form access
            "MEGA_BRACELET": ModifierSchema(
                type_id="MEGA_BRACELET",
                class_name="MegaEvolutionAccessModifier",
                target=ModifierTarget.TRAINER,
                description="Enables Mega Evolution",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[None]
            ),
            "TERA_ORB": ModifierSchema(
                type_id="TERA_ORB",
                class_name="TerastallizeAccessModifier",
                target=ModifierTarget.TRAINER,
                description="Enables Terastallization",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[None]
            ),
            "DYNAMAX_BAND": ModifierSchema(
                type_id="DYNAMAX_BAND",
                class_name="GigantamaxAccessModifier",
                target=ModifierTarget.TRAINER,
                description="Enables Gigantamax transformation",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[None]
            ),

            # Special utility modifiers
            "LOCK_CAPSULE": ModifierSchema(
                type_id="LOCK_CAPSULE",
                class_name="LockModifierTiersModifier",
                target=ModifierTarget.TRAINER,
                description="Allows the trainer to lock rewards from certain tiers",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[None]
            ),
            "CANDY_JAR": ModifierSchema(
                type_id="CANDY_JAR",
                class_name="LevelIncrementBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Increases the number of levels that rare and rarer candies increase",
                requires_pokemon_id=False,
                arg_structure=[],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[None]
            ),

            # Temporary stat boosters (trainer-wide)
            "TEMP_STAT_STAGE_BOOSTER": ModifierSchema(
                type_id="TEMP_STAT_STAGE_BOOSTER",
                class_name="TempStatStageBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Temporarily boosts stats at battle start",
                requires_pokemon_id=False,
                arg_structure=[ArgumentType.STAT_TYPE, ArgumentType.COUNT, ArgumentType.COUNT],
                has_type_pregen_args=True,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[[2, 5, 3]]
            ),
            "DIRE_HIT": ModifierSchema(
                type_id="DIRE_HIT",
                class_name="TempCritBoosterModifier",
                target=ModifierTarget.TRAINER,
                description="Increases the critical hit rate of the Pokemon in party by one stage",
                requires_pokemon_id=False,
                arg_structure=[ArgumentType.COUNT, ArgumentType.COUNT],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[5, 5]]
            ),
        }

        # Pokemon-targeting modifiers (affect specific Pokemon)
        pokemon_modifiers = {
            # Base stat boosters - CRITICAL for Pokémon targeting
            "BASE_STAT_BOOSTER": ModifierSchema(
                type_id="BASE_STAT_BOOSTER",
                class_name="BaseStatModifier",
                target=ModifierTarget.POKEMON,
                description="Increases base stats of specific Pokemon permanently",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.STAT_TYPE],
                has_type_pregen_args=True,
                stack_count_range=(1, 4),
                frequency_in_saves=39,  # Most common modifier
                example_args=[[2749149711, 0]]
            ),

            # Held items and equipment
            "BERRY": ModifierSchema(
                type_id="BERRY",
                class_name="BerryModifier",
                target=ModifierTarget.POKEMON,
                description="Held berries that activate under specific conditions",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.BERRY_TYPE],
                has_type_pregen_args=True,
                stack_count_range=(1, 2),
                frequency_in_saves=30,
                example_args=[[2749149711, 2]]
            ),
            "WIDE_LENS": ModifierSchema(
                type_id="WIDE_LENS",
                class_name="PokemonMoveAccuracyBoosterModifier",
                target=ModifierTarget.POKEMON,
                description="Increases accuracy of Pokemon moves",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.COUNT],
                has_type_pregen_args=False,
                stack_count_range=(1, 3),
                frequency_in_saves=6,
                example_args=[[1624686641, 5]]
            ),
            "FOCUS_BAND": ModifierSchema(
                type_id="FOCUS_BAND",
                class_name="SurviveDamageModifier",
                target=ModifierTarget.POKEMON,
                description="Gives the Pokemon a chance to survive fatal damage with 1 HP",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=3,
                example_args=[[3727313294]]
            ),
            "LEFTOVERS": ModifierSchema(
                type_id="LEFTOVERS",
                class_name="TurnHealModifier",
                target=ModifierTarget.POKEMON,
                description="Heals Pokemon at the end of each turn",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=5,
                example_args=[[1624686641]]
            ),
            "SHELL_BELL": ModifierSchema(
                type_id="SHELL_BELL",
                class_name="HitHealModifier",
                target=ModifierTarget.POKEMON,
                description="Recovers HP based on the Pokemon's damage dealt",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=2,
                example_args=[[1624686641]]
            ),
            "SCOPE_LENS": ModifierSchema(
                type_id="SCOPE_LENS",
                class_name="CritBoosterModifier",
                target=ModifierTarget.POKEMON,
                description="Increases critical hit rate of Pokemon moves",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.COUNT],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=2,
                example_args=[[2197697824, 1]]
            ),

            # Special Pokemon items
            "RARE_FORM_CHANGE_ITEM": ModifierSchema(
                type_id="RARE_FORM_CHANGE_ITEM",
                class_name="PokemonFormChangeItemModifier",
                target=ModifierTarget.POKEMON,
                description="Changes Pokemon form (e.g., Blastoise, Gyarados)",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.FORM_CHANGE_TYPE, ArgumentType.BOOLEAN],
                has_type_pregen_args=True,
                stack_count_range=(1, 1),
                frequency_in_saves=2,
                example_args=[[3727313294, 56, True], [2749149711, 22, True]]  # Blastoise & Gyarados
            ),
            "GOLDEN_PUNCH": ModifierSchema(
                type_id="GOLDEN_PUNCH",
                class_name="DamageMoneyRewardModifier",
                target=ModifierTarget.POKEMON,
                description="Grants a money reward based on the damage dealt",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=2,
                example_args=[[1624686641]]
            ),
            "GRIP_CLAW": ModifierSchema(
                type_id="GRIP_CLAW",
                class_name="ContactHeldItemTransferChanceModifier",
                target=ModifierTarget.POKEMON,
                description="Grants a chance to transfer a held item to a Pokemon",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.COUNT],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[2749149711, 10]]
            ),
            "KINGS_ROCK": ModifierSchema(
                type_id="KINGS_ROCK",
                class_name="FlinchChanceModifier",
                target=ModifierTarget.POKEMON,
                description="Grants a chance to flinch the target",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[2749149711]]
            ),
            "MYSTICAL_ROCK": ModifierSchema(
                type_id="MYSTICAL_ROCK",
                class_name="FieldEffectModifier",
                target=ModifierTarget.POKEMON,
                description="Increases the duration of a field effect",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[3727313294]]
            ),
            "ATTACK_TYPE_BOOSTER": ModifierSchema(
                type_id="ATTACK_TYPE_BOOSTER",
                class_name="AttackTypeBoosterModifier",
                target=ModifierTarget.POKEMON,
                description="Increases the attack power of the Pokemon in party by one stage",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.COUNT, ArgumentType.COUNT],
                has_type_pregen_args=True,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[3727313294, 14, 20]]
            ),
            "SOUL_DEW": ModifierSchema(
                type_id="SOUL_DEW",
                class_name="PokemonNatureWeightModifier",
                target=ModifierTarget.POKEMON,
                description="Doubles the effectiveness of the Pokemon's nature",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[1624686641]]
            ),
            "MULTI_LENS": ModifierSchema(
                type_id="MULTI_LENS",
                class_name="PokemonMultiHitModifier",
                target=ModifierTarget.POKEMON,
                description="Converts 25% of the pokemon's damage into a second hit",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[2749149711]]
            ),
            "LUCKY_EGG": ModifierSchema(
                type_id="LUCKY_EGG",
                class_name="PokemonExpBoosterModifier",
                target=ModifierTarget.POKEMON,
                description="Increases experience gained by specific Pokemon",
                requires_pokemon_id=True,
                arg_structure=[ArgumentType.POKEMON_ID, ArgumentType.PERCENTAGE],
                has_type_pregen_args=False,
                stack_count_range=(1, 1),
                frequency_in_saves=1,
                example_args=[[2749149711, 40]]
            ),
        }

        # Combine all modifiers
        all_modifiers = {**trainer_modifiers, **pokemon_modifiers}
        return all_modifiers

    def get_modifier_schema(self, type_id: str) -> Optional[ModifierSchema]:
        """Get schema for a modifier type."""
        return self._modifiers.get(type_id)

    def get_trainer_modifiers(self) -> Dict[str, ModifierSchema]:
        """Get all trainer-targeting modifiers."""
        return {k: v for k, v in self._modifiers.items() if v.target == ModifierTarget.TRAINER}

    def get_pokemon_modifiers(self) -> Dict[str, ModifierSchema]:
        """Get all Pokemon-targeting modifiers."""
        return {k: v for k, v in self._modifiers.items() if v.target == ModifierTarget.POKEMON}

    def create_modifier(self, type_id: str, pokemon_id: Optional[int] = None,
                       additional_args: Optional[List[Any]] = None,
                       stack_count: int = 1) -> Dict[str, Any]:
        """
        Create a properly structured modifier.

        Args:
            type_id: Modifier type ID
            pokemon_id: Pokemon ID if required by modifier
            additional_args: Additional arguments based on modifier requirements
            stack_count: Number of stacks

        Returns:
            Complete modifier dictionary ready for save file
        """
        schema = self.get_modifier_schema(type_id)
        if not schema:
            raise ValueError(f"Unknown modifier type: {type_id}")

        # Validate requirements
        if schema.requires_pokemon_id and pokemon_id is None:
            raise ValueError(f"Modifier {type_id} requires a Pokemon ID")

        if not schema.requires_pokemon_id and pokemon_id is not None:
            logger.warning(f"Modifier {type_id} does not require Pokemon ID, ignoring provided ID")
            pokemon_id = None

        # Build arguments based on schema
        args = []
        type_pregen_args = []

        if schema.requires_pokemon_id:
            args.append(pokemon_id)

        # Add additional arguments based on schema
        if additional_args:
            args.extend(additional_args)

        # Handle type pregen args
        if schema.has_type_pregen_args and additional_args:
            # Typically the last additional argument goes to typePregenArgs
            if schema.type_id == "BASE_STAT_BOOSTER":
                type_pregen_args = [additional_args[0]]  # stat_type
            elif schema.type_id == "BERRY":
                type_pregen_args = [additional_args[0]]  # berry_type
            elif schema.type_id == "RARE_FORM_CHANGE_ITEM":
                type_pregen_args = [additional_args[0]]  # form_change_type
            elif schema.type_id == "TEMP_STAT_STAGE_BOOSTER":
                type_pregen_args = [additional_args[0]]  # stat_type
            elif schema.type_id == "ATTACK_TYPE_BOOSTER":
                type_pregen_args = [additional_args[0]]  # attack_type

        # Validate stack count
        min_stack, max_stack = schema.stack_count_range
        if not (min_stack <= stack_count <= max_stack):
            logger.warning(f"Stack count {stack_count} outside range {min_stack}-{max_stack} for {type_id}")

        # Build modifier
        modifier = {
            "className": schema.class_name,
            "player": True,
            "stackCount": stack_count,
            "typeId": type_id,
        }

        # Add args if present
        if args:
            modifier["args"] = args

        # Add typePregenArgs if present
        if type_pregen_args:
            modifier["typePregenArgs"] = type_pregen_args

        return modifier


# Global catalog instance
modifier_catalog = EnhancedModifierCatalog()