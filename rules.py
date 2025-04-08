from typing import TypedDict, Optional, List, Any, Dict
from object_manager import ObjectManager

# Define the structure of a rule using TypedDict for clarity
class Rule(TypedDict):
    name: str
    condition: str
    action_type: str # e.g., 'spell', 'lua', 'item', 'macro'
    action_value: str # e.g., spell ID, lua code, item ID, macro text
    target: Optional[str] # e.g., 'target', 'player', 'focus' (default 'target')
    cooldown: Optional[float] # Internal cooldown in seconds
    enabled: bool
    # Add other potential fields as needed
    spell_id: Optional[int] # Often redundant if action_value is spell_id


class ConditionChecker:
    """Evaluates rule conditions based on game state."""

    def __init__(self, om: ObjectManager):
        self.om = om

    def check(self, condition_str: str, rule_context: Rule) -> bool:
        """Main method to evaluate a condition string."""
        if not self.om or not self.om.local_player:
            # print("ConditionChecker Error: ObjectManager or LocalPlayer not available.")
            return False # Cannot check conditions without game state

        player = self.om.local_player
        target_unit_str = rule_context.get("target", "target").lower()
        target_obj = None

        # Resolve target object
        if target_unit_str == "target": target_obj = self.om.target
        elif target_unit_str == "player": target_obj = player
        # TODO: Add focus, pet, mouseover, etc.

        # --- Basic Checks ---
        if condition_str == "None": return True
        if condition_str == "Target Exists":
            return target_obj is not None and target_obj.is_valid() and not target_obj.is_dead
        if condition_str == "Target Attackable":
             return target_obj is not None and target_obj.is_valid() and not target_obj.is_dead and target_obj.is_attackable
        if condition_str == "Is Casting":
             return player.is_casting or player.is_channeling
        if condition_str == "Target Is Casting":
             return target_obj is not None and target_obj.is_valid() and (target_obj.is_casting or target_obj.is_channeling)
        # Add "Is Moving" later if needed

        # --- Health/Resource Checks ---
        try:
            if condition_str.startswith("Target <") and condition_str.endswith("% HP"):
                if not target_obj or not target_obj.is_valid() or target_obj.max_health == 0:
                    return False
                percent = int(condition_str.split("<")[1].split("%")[0].strip())
                return (target_obj.health / target_obj.max_health * 100) < percent
            # Add Target >, Player <, Player > HP checks similarly

            # Add Rage/Energy/Mana checks similarly
        except (ValueError, IndexError, ZeroDivisionError) as e:
            print(f"Error parsing condition '{condition_str}': {e}")
            return False

        # --- Spell/Buff/Debuff Checks (Requires Direct Calls or Lua) ---
        spell_id = rule_context.get("spell_id")
        if condition_str == "Is Spell Ready":
            if not spell_id: return False
            # Placeholder - Needs call to game.get_spell_cooldown_direct
            # cooldown_info = self.om.game_interface_ref.get_spell_cooldown_direct(spell_id)
            # return cooldown_info['is_ready'] if cooldown_info else False
            print(f"DEBUG: Condition 'Is Spell Ready' for {spell_id} - Not Implemented")
            return True # Assume ready for now
        # Add Target Has Debuff, Player Has Buff later

        print(f"Warning: Unrecognized condition: '{condition_str}'")
        return False


class RuleSet:
    """Manages a collection of rules."""
    # Placeholder - Could manage loading/saving rules from files etc.
    def __init__(self):
        self.rules: List[Rule] = []

    def load_from_list(self, rule_list: List[Dict[str, Any]]):
        self.rules = [Rule(**rule_data) for rule_data in rule_list] # Basic validation

    def get_active_rules(self) -> List[Rule]:
        return [rule for rule in self.rules if rule.get('enabled', True)]
