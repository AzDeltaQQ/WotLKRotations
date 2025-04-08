import os # Needed for checking file existence
import time # May be needed for delays or GCD tracking
import json # For handling potential rule files
from memory import MemoryHandler
from object_manager import ObjectManager
# from luainterface import LuaInterface # Old
from gameinterface import GameInterface # New
from rules import Rule, ConditionChecker # Import rule processing
from typing import List, Dict, Any, Optional

# Project Modules
from wow_object import WowObject # Import for type constants like POWER_RAGE

class CombatRotation:
    """
    Manages and executes combat rotations, either via loaded Lua scripts
    or a defined set of prioritized rules.
    """
    def __init__(self, mem: MemoryHandler, om: ObjectManager, game: GameInterface):
        self.mem = mem
        self.om = om
        self.game = game
        self.condition_checker = ConditionChecker(om) # Initialize condition checker
        self.rules: List[Rule] = []
        self.last_rule_execution_time: Dict[int, float] = {} # Store last time a rule (by index) was executed
        # For Script based rotations
        self.rotation_script_content: Optional[str] = None
        self.script_execution_interval = 1.0 # Default: execute script every 1 second
        self.last_script_execution_time = 0.0

        # Rotation State
        self.current_rotation_script_path = None # Path if using a Lua script file
        self.lua_script_content = None         # Content if using a Lua script file
        self.rotation_rules = []               # List of rule dicts if using the rule engine
        self.last_action_time = 0.0            # Timestamp of the last action taken
        self.gcd_duration = 1.5                # Default GCD in seconds (Needs dynamic update later)
        self.last_rule_executed_time: dict[int, float] = {} # Track internal cooldowns per spell ID {spell_id: last_exec_time}


    def load_rotation_script(self, script_path: str) -> bool:
        """Reads the content of a Lua script file. Clears any existing rules."""
        try:
            if os.path.exists(script_path):
                with open(script_path, 'r', encoding='utf-8') as f:
                    self.lua_script_content = f.read()
                self.current_rotation_script_path = script_path
                self._clear_rules() # Clear rules when loading a script
                print(f"Successfully read Lua script: {script_path}")
                return True
            else:
                print(f"Error: Rotation script not found at {script_path}")
                self._clear_rotation()
                return False
        except Exception as e:
            print(f"Error reading rotation script {script_path}: {e}")
            self._clear_rotation()
            return False

    def load_rotation_rules(self, rules: list):
        """Loads rules from the editor or a file. Clears any existing script."""
        self.rotation_rules = rules
        self._clear_script() # Clear script when loading rules
        self.last_rule_executed_time.clear() # Reset internal cooldown tracking
        print(f"Loaded {len(rules)} rotation rules.")
        # TODO: Implement saving/loading rules to/from file (e.g., JSON)

    def _clear_script(self):
        """Clears loaded script data."""
        self.current_rotation_script_path = None
        self.lua_script_content = None

    def _clear_rules(self):
         """Clears loaded rule data."""
         self.rotation_rules = []
         self.last_rule_executed_time.clear()

    def _clear_rotation(self):
        """Clears both script and rule data."""
        self._clear_script()
        self._clear_rules()

    def run(self):
        """Executes the loaded rotation logic (prioritizes rules over script)."""
        if not self.om.local_player or self.om.local_player.is_dead:
            return # Don't run if player doesn't exist or is dead

        # --- Rule-Based Rotation has Priority ---
        if self.rotation_rules:
            self._execute_rule_engine()

        # --- Fallback to Monolithic Lua Script ---
        elif self.lua_script_content:
            if not self.game.is_ready(): return # Need Lua for script execution
            # Execute the entire loaded script content
            self.game.execute(self.lua_script_content, source_name=os.path.basename(self.current_rotation_script_path or "RotationScript"))
            # Note: Timing/GCD for monolithic scripts must be handled *within* the script itself.

        # --- No rotation loaded ---
        # else: pass # No rotation active


    def _execute_rule_engine(self):
        """Runs the rule-based rotation logic."""
        if not self.game.is_ready(): return # Need Lua for actions

        now = time.time()

        # --- Global Checks ---
        # Check GCD (placeholder - requires querying game state via Lua C API)
        # Example placeholder: Use simple time-based GCD
        if now < self.last_action_time + self.gcd_duration:
             return # Still on GCD

        # Add checks for player casting, stunned, etc.
        if self.om.local_player.is_casting or self.om.local_player.is_channeling:
             return # Don't interrupt self
        if self.om.local_player.is_stunned or self.om.local_player.has_flag(WowObject.UNIT_FLAG_CONFUSED | WowObject.UNIT_FLAG_FLEEING):
             return # Can't act

        # --- Iterate Rules by Priority ---
        # Assumes self.rotation_rules is ordered by priority (index 0 highest)
        for rule in self.rotation_rules:
            spell_id = rule.get("spell_id")
            internal_cd = rule.get("cooldown", 0)

            # Check Internal Cooldown defined in the rule
            if spell_id and internal_cd > 0:
                last_exec = self.last_rule_executed_time.get(spell_id, 0)
                if now < last_exec + internal_cd:
                     continue # Rule is on internal cooldown

            # Check Game State Condition
            if self._check_rule_condition(rule):
                # Condition met, attempt action
                if self._execute_rule_action(rule):
                    # Action successful
                    self.last_action_time = now # Record action time for GCD tracking
                    if spell_id and internal_cd >= 0: # Record execution time for internal CD tracking
                         self.last_rule_executed_time[spell_id] = now
                    # Rotation logic for this tick is done, break the loop
                    break


    def _check_rule_condition(self, rule: dict) -> bool:
        """
        Evaluates the condition string defined in the rule.
        This is a basic placeholder and needs significant expansion using LuaInterface.
        """
        condition_str = rule.get("condition", "None").strip()
        target_unit_str = rule.get("target", "target").lower()

        # --- Get target object based on rule ---
        target_obj = None
        if target_unit_str == "target": target_obj = self.om.target
        elif target_unit_str == "player": target_obj = self.om.local_player
        # Add focus, pet, mouseover later using respective GUIDs/API calls
        # elif target_unit_str == "focus": target_obj = self.om.get_object_by_guid(self.om.focus_guid) # Needs focus GUID tracking

        # --- Basic Existence Checks ---
        if condition_str == "None":
            return True # No condition check needed
        if condition_str == "Target Exists" or target_unit_str == "target": # Implicit target exists if rule targets it
            if not target_obj: return False
            # Also check if target is attackable (basic check)
            if not target_obj.is_attackable: return False
        # Add checks for player/focus existing if needed

        player = self.om.local_player
        if not player: return False # Need player for most checks

        # --- Simple String Matching (Placeholder Logic) ---
        try:
            if condition_str == "Target < 20% HP":
                return target_obj and target_obj.max_health > 0 and (target_obj.health / target_obj.max_health) < 0.20
            elif condition_str == "Target < 35% HP":
                return target_obj and target_obj.max_health > 0 and (target_obj.health / target_obj.max_health) < 0.35
            elif condition_str == "Player < 30% HP":
                return player.max_health > 0 and (player.health / player.max_health) < 0.30
            elif condition_str == "Player < 50% HP":
                return player.max_health > 0 and (player.health / player.max_health) < 0.50
            elif condition_str.startswith("Rage >"):
                return player.power_type == WowObject.POWER_RAGE and player.energy > int(condition_str.split('>')[1].strip())
            elif condition_str.startswith("Energy >"):
                return player.power_type == WowObject.POWER_ENERGY and player.energy > int(condition_str.split('>')[1].strip())
            elif condition_str.startswith("Mana >") and condition_str.endswith('%'):
                 if player.power_type == WowObject.POWER_MANA and player.max_energy > 0:
                      return (player.energy / player.max_energy * 100) > int(condition_str.split('>')[1].strip()[:-1])
            elif condition_str.startswith("Mana <") and condition_str.endswith('%'):
                 if player.power_type == WowObject.POWER_MANA and player.max_energy > 0:
                      return (player.energy / player.max_energy * 100) < int(condition_str.split('<')[1].strip()[:-1])

            # --- Conditions needing Lua Calls (Requires Stable LuaInterface) ---
            elif condition_str == "Is Spell Ready":
                 spell_id = rule.get("spell_id")
                 if not spell_id: return False
                 # TODO: Call self.game.get_spell_cooldown(spell_id) and check if ready
                 # print(f"DEBUG: Condition 'Is Spell Ready' for {spell_id} - Not Implemented")
                 return True # Placeholder: Assume ready for now
            elif condition_str == "Target Has Debuff":
                 # TODO: Implement self.game.unit_has_debuff(target_obj.guid, spell_id_from_condition, ...)
                 # print(f"DEBUG: Condition 'Target Has Debuff' - Not Implemented")
                 return False # Placeholder: Assume false
            elif condition_str == "Player Has Buff":
                 # TODO: Implement self.game.unit_has_buff(player.guid, spell_id_from_condition, ...)
                 # print(f"DEBUG: Condition 'Player Has Buff' - Not Implemented")
                 return False # Placeholder: Assume false
            elif condition_str == "Is Moving":
                 # TODO: Check player movement flags (if offset known) or use Lua IsMoving()
                 return False # Placeholder: Assume not moving
            elif condition_str == "Is Casting":
                 return player.is_casting or player.is_channeling
            elif condition_str == "Target Is Casting":
                 return target_obj is not None and (target_obj.is_casting or target_obj.is_channeling)

        except Exception as e:
            # Avoid crashing rotation on bad condition string/logic
            print(f"Error evaluating condition '{condition_str}': {e}")
            return False

        # If condition string not recognized, treat as false
        # print(f"Warning: Unrecognized condition string: '{condition_str}'") # Debug spam
        return False


    def _execute_rule_action(self, rule: dict) -> bool:
        """Executes the action associated with a rule (e.g., cast spell)."""
        spell_id = rule.get("spell_id")
        target_unit = rule.get("target", "target").lower() # Default to 'target'

        if spell_id:
            # Map target string to unitID used by WoW API if needed
            wow_target_unitid = target_unit # Use directly for [@unitid] syntax if possible

            # Construct Lua command
            # Option 1: Simple CastSpellByID (targets current target by default)
            # lua_code = f"CastSpellByID({spell_id})"
            # Option 2: Use /cast macro text for flexible targeting
            # Note: Requires RunMacroText or similar execute capability
            macro_text = f"/cast [@{wow_target_unitid}] {spell_id}" # Assumes spell ID works in /cast
            # Alternative: Get spell name via lookup and use that? Slower.
            # spell_name = self.game.get_spell_name(spell_id) # Needs stable C API
            # if spell_name: macro_text = f"/cast [@{wow_target_unitid}] {spell_name}"

            # Choose execution method (simple CastSpellByID often sufficient if target is managed correctly)
            if target_unit == "target": # Default WoW API target
                 lua_code = f"CastSpellByID({spell_id})"
            else:
                 # Use macro for specific targets (might be less reliable than direct API calls if available)
                 # Need to escape quotes properly if using RunMacroText
                 # lua_code = f'RunMacroText("{macro_text}")'
                 # For now, try simple CastSpellByID approach, assuming API handles some units
                 if target_unit == "player":
                      lua_code = f"CastSpellByID({spell_id}, 'player')" # Check if API supports this arg
                 else:
                      print(f"Warning: Targeting unit '{target_unit}' not fully implemented, using default target.")
                      lua_code = f"CastSpellByID({spell_id})" # Fallback

            if lua_code:
                 # print(f"ROTATION ACTION: {lua_code}") # Debug Spam
                 success = self.game.execute(lua_code, f"Rule_{spell_id}")
                 return success

        # TODO: Add other actions like UseItem(itemId), RunMacroText("/startattack") etc.
        print(f"Warning: Rule action not recognized or missing spell_id: {rule}")
        return False

    