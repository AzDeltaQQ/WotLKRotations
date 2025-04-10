import os # Needed for checking file existence
import time # May be needed for delays or GCD tracking
import json # For handling potential rule files
import sys # Added sys import
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
                print(f"Successfully read Lua script: {script_path}", file=sys.stderr)
                return True
            else:
                print(f"Error: Rotation script not found at {script_path}", file=sys.stderr)
                self._clear_rotation()
                return False
        except Exception as e:
            print(f"Error reading rotation script {script_path}: {e}", file=sys.stderr)
            self._clear_rotation()
            return False

    def load_rotation_rules(self, rules: list):
        """Loads rules from the editor or a file. Clears any existing script."""
        self.rotation_rules = rules
        self._clear_script() # Clear script when loading rules
        self.last_rule_executed_time.clear() # Reset internal cooldown tracking
        print(f"Loaded {len(rules)} rotation rules.", file=sys.stderr)
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
        print("[Run] Entering run method", file=sys.stderr) # Debug Entry
        
        player = self.om.local_player
        print(f"[Run] Player object: {'Exists' if player else 'None'}", file=sys.stderr) # Debug Player Check 1
        if not player:
            print("[Run] Exiting: No local player found.", file=sys.stderr)
            return
        
        is_dead = player.is_dead
        print(f"[Run] Player is_dead: {is_dead}", file=sys.stderr) # Debug Player Check 2
        if is_dead:
            print("[Run] Exiting: Player is dead.", file=sys.stderr)
            return 
        
        print("[Run] Passed player checks.", file=sys.stderr) # Debug Checkpoint
        
        has_rules = bool(self.rotation_rules)
        print(f"[Run] Has rules loaded: {has_rules} (Count: {len(self.rotation_rules) if self.rotation_rules else 0})", file=sys.stderr) # Debug Rules Check
        # --- Rule-Based Rotation has Priority ---
        if has_rules:
            print("[Run] Entering rule engine...", file=sys.stderr) # Debug Checkpoint
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
        print("[Engine] Entering _execute_rule_engine", file=sys.stderr) # Debug Entry
        if not self.game.is_ready(): 
            print("[Engine] Exiting: Game interface not ready.", file=sys.stderr)
            return

        now = time.time()

        # --- Global Checks ---
        gcd_remaining = (self.last_action_time + self.gcd_duration) - now
        if gcd_remaining > 0:
             print(f"[Engine] Exiting: On GCD ({gcd_remaining:.2f}s remaining)", file=sys.stderr)
             return # Still on GCD

        is_casting = self.om.local_player.is_casting
        is_channeling = self.om.local_player.is_channeling
        if is_casting or is_channeling:
             print(f"[Engine] Exiting: Player is casting ({is_casting}) or channeling ({is_channeling})", file=sys.stderr)
             return # Don't interrupt self
             
        is_stunned = self.om.local_player.is_stunned
        is_cc_flagged = self.om.local_player.has_flag(WowObject.UNIT_FLAG_CONFUSED | WowObject.UNIT_FLAG_FLEEING)
        if is_stunned or is_cc_flagged:
             print(f"[Engine] Exiting: Player is stunned ({is_stunned}) or CC flagged ({is_cc_flagged})", file=sys.stderr)
             return # Can't act

        print("[Engine] Passed global checks, iterating rules...", file=sys.stderr) # Should see this if checks pass
        # --- Iterate Rules by Priority ---
        # Assumes self.rotation_rules is ordered by priority (index 0 highest)
        for rule in self.rotation_rules:
            # Added detailed logging for this specific condition
            # print("[Condition] Checking rule:", rule, file=sys.stderr) # Debug Spam
            spell_id = rule.get("detail") # Corrected to get 'detail' which holds spell ID for Spell action
            internal_cd = rule.get("cooldown", 0)

            # Check Internal Cooldown defined in the rule
            # Use detail (spell_id) for tracking
            if spell_id and internal_cd > 0:
                last_exec = self.last_rule_executed_time.get(spell_id, 0)
                if now < last_exec + internal_cd:
                     # print(f"[Engine] Rule for {spell_id} on internal CD", file=sys.stderr)
                     continue # Rule is on internal cooldown

            # Check Game State Condition
            if self._check_rule_condition(rule):
                print(f"[Engine] Condition MET for rule: {rule}", file=sys.stderr) # Log condition success
                # Condition met, attempt action
                if self._execute_rule_action(rule):
                    # Action successful
                    print(f"[Engine] Action SUCCESSFUL for rule: {rule}", file=sys.stderr) # Log action success
                    self.last_action_time = now # Record action time for GCD tracking
                    if spell_id and internal_cd >= 0: # Record execution time for internal CD tracking
                         self.last_rule_executed_time[spell_id] = now
                    # Rotation logic for this tick is done, break the loop
                    break
                else:
                     print(f"[Engine] Action FAILED for rule: {rule}", file=sys.stderr) # Log action failure
            # else: # Condition not met
                 # print(f"[Engine] Condition NOT MET for rule: {rule}", file=sys.stderr)


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
        if condition_str == "Target Exists": 
            # Added detailed logging for this specific condition
            if not target_obj:
                print("[Condition] Target Exists: FAILED - target_obj is None", file=sys.stderr) # Debug Spam
                return False
            if not target_obj.is_attackable:
                print(f"[Condition] Target Exists: FAILED - target {target_obj.guid:#X} is not attackable", file=sys.stderr) # Debug Spam
                return False
            print("[Condition] Target Exists: PASSED", file=sys.stderr)
            return True # Passed both checks
            
        # Fallback if target_unit_str was 'target' but condition wasn't 'Target Exists' 
        # (e.g. for HP checks, ensure target exists first)
        if target_unit_str == "target" and not target_obj:
            print("[Condition] Prerequisite FAILED - Rule targets 'target' but target_obj is None", file=sys.stderr)
            return False
            
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
            print(f"Error evaluating condition '{condition_str}': {e}", file=sys.stderr)
            return False

        # If condition string not recognized, treat as false
        # print(f"Warning: Unrecognized condition string: '{condition_str}'") # Debug spam
        return False


    def _execute_rule_action(self, rule: dict) -> bool:
        """Executes the action associated with a rule (e.g., cast spell)."""
        spell_id = rule.get("detail") # Use 'detail' for spell ID
        target_unit = rule.get("target", "target").lower() # Default to 'target'
        action_type = rule.get("action", "Spell") # Get action type
        success = False

        if action_type == "Spell" and spell_id:
            wow_target_unitid = target_unit # Use directly for now
            # Add an in-game print to the Lua code for debugging
            lua_code = f"print('[PyWoW] Trying CastSpellByID({spell_id})'); CastSpellByID({spell_id})"
            # Add more complex targetting/macro logic later if needed

            print(f"[Action] Attempting Lua: {lua_code}", file=sys.stderr) # Debug Spam
            try:
                # Execute and check response
                response = self.game.execute(lua_code)
                print(f"[Action] Lua Response: {response}", file=sys.stderr) # Debug Spam
                
                # Basic success check: Assume success if response doesn't indicate error
                # More robust checking might be needed depending on DLL response format
                if response is None or (isinstance(response, str) and "ERROR" in response.upper()):
                    print(f"[Action] Lua execution FAILED or returned error for: {lua_code}", file=sys.stderr) # Debug Spam
                    success = False
                else:
                    print(f"[Action] Lua execution presumed SUCCESS for: {lua_code}", file=sys.stderr) # Debug Spam
                    success = True 
            except Exception as e:
                print(f"[Action] Error during game.execute for '{lua_code}': {e}", file=sys.stderr)
                success = False
                
        elif action_type == "Macro":
            macro_text = rule.get("detail")
            if macro_text:
                # Need a way to execute macros, e.g., through Lua RunMacroText
                # lua_code = f'RunMacroText("{macro_text.replace("\\"", "\\\\").replace("\"", "\\\"")}')' 
                print(f"[Action] Macro execution not yet implemented: {macro_text}", file=sys.stderr) # Placeholder
                # response = self.game.execute(lua_code)
                # success = ... check response ... 
                pass # Not implemented
        elif action_type == "Lua":
            lua_code_direct = rule.get("detail")
            if lua_code_direct:
                print(f"[Action] Executing direct Lua from rule: {lua_code_direct}", file=sys.stderr) # Debug Spam
                try:
                    response = self.game.execute(lua_code_direct)
                    print(f"[Action] Direct Lua Response: {response}", file=sys.stderr) # Debug Spam
                    if response is None or (isinstance(response, str) and "ERROR" in response.upper()):
                        success = False
                    else:
                        success = True
                except Exception as e:
                    print(f"[Action] Error during game.execute for direct Lua: {e}", file=sys.stderr)
                    success = False

        return success

    