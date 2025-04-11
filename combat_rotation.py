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
        # print("[Run] Entering run method", file=sys.stderr) # Debug Entry
        
        player = self.om.local_player
        # print(f"[Run] Player object: {'Exists' if player else 'None'}", file=sys.stderr) # Debug Player Check 1
        if not player:
            print("[Run] Exiting: No local player found.", file=sys.stderr) # DEBUG
            return
        
        is_dead = player.is_dead
        # print(f"[Run] Player is_dead: {is_dead}", file=sys.stderr) # Debug Player Check 2
        if is_dead:
            print("[Run] Exiting: Player is dead.", file=sys.stderr) # DEBUG
            return 
        
        # print("[Run] Passed player checks.", file=sys.stderr) # Debug Checkpoint
        
        has_rules = bool(self.rotation_rules)
        # print(f"[Run] Has rules loaded: {has_rules} (Count: {len(self.rotation_rules) if self.rotation_rules else 0})", file=sys.stderr) # Debug Rules Check
        # --- Rule-Based Rotation has Priority ---
        if has_rules:
            # print("[Run] Entering rule engine...", file=sys.stderr) # Debug Checkpoint
            self._execute_rule_engine()
        # --- Fallback to Monolithic Lua Script ---
        elif self.lua_script_content:
            print("[Run] Exiting: No rules, attempting Lua script (Not fully implemented).", file=sys.stderr) # DEBUG
            if not self.game.is_ready(): return # Need Lua for script execution
            # Execute the entire loaded script content
            self.game.execute(self.lua_script_content, source_name=os.path.basename(self.current_rotation_script_path or "RotationScript"))
            # Note: Timing/GCD for monolithic scripts must be handled *within* the script itself.
        # --- No rotation loaded ---
        else:
            print("[Run] Exiting: No rules or script loaded.", file=sys.stderr) # DEBUG
            pass # No rotation active


    def _execute_rule_engine(self):
        """Runs the rule-based rotation logic."""
        # print("[Engine] Entering _execute_rule_engine", file=sys.stderr) # Debug Entry
        if not self.game.is_ready(): 
            print("[Engine] Exiting: Game interface not ready.", file=sys.stderr) # DEBUG
            return

        now = time.time()

        # --- Global Checks ---
        gcd_remaining = (self.last_action_time + self.gcd_duration) - now
        if gcd_remaining > 0:
            # print(f"[Engine] Exiting: On GCD ({gcd_remaining:.2f}s remaining)", file=sys.stderr) # DEBUG
             return # Still on GCD

        player = self.om.local_player # Get player reference
        if not player:
            # print("[Engine] Exiting: Player object not found within engine loop.", file=sys.stderr) # DEBUG
            return # Should not happen if run() checked, but safety first

        is_casting = player.is_casting
        is_channeling = player.is_channeling
        if is_casting or is_channeling:
            # print(f"[Engine] Exiting: Player is casting ({is_casting}) or channeling ({is_channeling})", file=sys.stderr) # DEBUG
             return # Don't interrupt self
             
        is_stunned = player.is_stunned
        # Combining flags using bitwise OR
        cc_flags = WowObject.UNIT_FLAG_CONFUSED | WowObject.UNIT_FLAG_FLEEING | WowObject.UNIT_FLAG_PACIFIED | WowObject.UNIT_FLAG_SILENCED
        is_cc_flagged = player.has_flag(cc_flags)
        if is_stunned or is_cc_flagged:
            # print(f"[Engine] Exiting: Player is stunned ({is_stunned}) or CC flagged ({is_cc_flagged})", file=sys.stderr) # DEBUG
             return # Can't act

        # print("[Engine] Passed global checks, iterating rules...", file=sys.stderr) # Should see this if checks pass
        # --- Iterate Rules by Priority ---
        # Assumes self.rotation_rules is ordered by priority (index 0 highest)
        for rule in self.rotation_rules:
            # Added detailed logging for this specific condition
            # print("[Condition] Checking rule:", rule, file=sys.stderr) # Debug Spam
            spell_id = rule.get("detail") # Corrected to get 'detail' which holds spell ID for Spell action
            internal_cd = rule.get("cooldown", 0)
            action_type = rule.get("action", "Spell") # Get action type for check

            # --- Check Conditions FIRST --- #
            if not self._check_rule_condition(rule):
                # print(f"[Engine] Condition failed for rule: {rule.get('condition')}", file=sys.stderr)
                continue # Move to the next rule if conditions aren't met
            # else:
            #    print(f"[Engine] Condition PASSED for rule: {rule.get('condition')}", file=sys.stderr)

            # --- ADDED: Check if rule targets "target" and target actually exists --- #
            target_unit_str = rule.get("target", "target").lower()
            if target_unit_str == "target" and self.om.target is None:
                 # print(f"[Engine] Skipping rule for {action_type}:{spell_id} - Rule targets 'target', but no target selected.", file=sys.stderr)
                 continue # Skip this rule if it needs a target and none exists
            # ------------------------------------------------------------------------ #

            # --- Check Cooldowns (Global and Internal) only if condition passed AND target exists (if needed) --- #
            if not self._check_rule_cooldowns(rule):
                # print(f"[Engine] Cooldown failed for rule action: {rule.get('action')}:{rule.get('detail')}", file=sys.stderr)
                continue # Move to the next rule if on cooldown
            # else:
            #    print(f"[Engine] Cooldown PASSED for rule action: {rule.get('action')}:{rule.get('detail')}", file=sys.stderr)

            # --- Execute Action if Conditions and Cooldowns Pass --- #
            # print(f"[Engine] Attempting action for rule...", file=sys.stderr)
            action_succeeded_ingame = self._execute_rule_action(rule)

            if action_succeeded_ingame:
                # print(f"[Engine] Action SUCCEEDED in-game, breaking loop for this tick.", file=sys.stderr)
                break # Action successful, exit the loop for this tick
            else:
                 # print(f"[Engine] Action FAILED in-game (or pipe failed), continuing to next rule.", file=sys.stderr)
                 # Continue to the next rule if the action failed in-game
                 pass # Indentation corrected


    def _check_rule_condition(self, rule: dict) -> bool:
        """
        Evaluates the condition string defined in the rule.
        Resolves the target object dynamically during the check.
        """
        condition_str = rule.get("condition", "None").strip()
        target_unit_str = rule.get("target", "target").lower()

        # --- Resolve target object based on rule - DO THIS INSIDE THE CHECK ---
        target_obj = None
        player = self.om.local_player # Get local player ref
        if not player: return False # Need player for player-based checks

        if target_unit_str == "target":
            target_obj = self.om.target # Fetch current target from OM
        elif target_unit_str == "player":
            target_obj = player
        # TODO: Add focus, pet, mouseover later
        # elif target_unit_str == "focus": target_obj = self.om.get_object_by_guid(self.om.focus_guid)

        # --- Basic Checks --- Now use the resolved target_obj ---
        if condition_str == "None":
            return True # No condition check needed

        # Target Exists Check
        if condition_str == "Target Exists":
            is_valid_target = target_obj and not target_obj.is_dead # Simplified check
            # Log detailed failure reasons
            if not is_valid_target:
                fail_reason = "target_obj is None" if not target_obj else ("target is dead" if target_obj.is_dead else "unknown")
                # print(f"[Condition] Target Exists: FAILED - {fail_reason}", file=sys.stderr)
                return False
            else:
                # print("[Condition] Target Exists: PASSED", file=sys.stderr)
                return True

        # --- Prerequisite: Ensure target exists if rule implies it --- 
        # If the condition requires a target, but we couldn't resolve one based on the rule's
        # target string (e.g. rule targets "target" but none selected), fail early.
        needs_target_obj = condition_str.startswith("Target") # Simple heuristic
        if needs_target_obj and not target_obj:
            # print(f"[Condition] Prerequisite FAILED - Condition '{condition_str}' requires target '{target_unit_str}', but it resolved to None", file=sys.stderr)
            return False

        # --- Specific Conditions --- (Ensure target_obj is checked for None where needed)

        # Player state checks (don't necessarily need target_obj)
        if condition_str == "Is Casting":
            return player.is_casting or player.is_channeling
        elif condition_str == "Player < 30% HP":
            return player.max_health > 0 and (player.health / player.max_health) < 0.30
        elif condition_str == "Player < 50% HP":
            return player.max_health > 0 and (player.health / player.max_health) < 0.50
        elif condition_str.startswith("Rage >"):
            # Ensure player object exists and power type matches
            return player.power_type == WowObject.POWER_RAGE and player.energy > int(condition_str.split('>')[1].strip())
        elif condition_str.startswith("Energy >"):
            # Check player object exists and power type matches
            value_str = condition_str.split('>')[1].strip()
            try:
                required_energy = int(value_str)
                return player.power_type == WowObject.POWER_ENERGY and player.energy > required_energy
            except ValueError:
                print(f"[Condition] Error: Invalid number '{value_str}' in condition '{condition_str}'", file=sys.stderr)
                return False
        # Add other player resource checks (Mana etc.)
        elif condition_str.startswith("Player Energy >= X"):
            value_str = rule.get("condition_value_x", "0") # Get value from rule dict
            try:
                required_energy = float(value_str) # Use float for potential decimals
                current_energy = player.energy
                power_type_match = player.power_type == WowObject.POWER_ENERGY
                return power_type_match and current_energy >= required_energy
            except (ValueError, TypeError) as e:
                print(f"[Condition] Error: Invalid number '{value_str}' for condition_value_x in rule '{rule}': {e}", file=sys.stderr)
                return False
        elif condition_str.startswith("Rage >= X"):
            # Ensure player object exists and power type matches
            return player.power_type == WowObject.POWER_RAGE and player.energy > int(condition_str.split('>')[1].strip())

        # Target state checks (MUST check target_obj is not None)
        if target_obj:
            if condition_str == "Target < 20% HP":
                return target_obj.max_health > 0 and (target_obj.health / target_obj.max_health) < 0.20
            elif condition_str == "Target < 35% HP":
                return target_obj.max_health > 0 and (target_obj.health / target_obj.max_health) < 0.35
            elif condition_str == "Target Is Casting":
                 return target_obj.is_casting or target_obj.is_channeling
            # Add other target conditions here

        # --- Conditions needing Lua Calls (Placeholder/Future) ---
        # Re-check target validity if needed for Lua calls
        # elif condition_str == "Is Spell Ready": # This check happens earlier now
        #      pass

        # Fallback: Condition not recognized or target was required but None
        # print(f"Warning: Unrecognized or inapplicable condition: '{condition_str}' for target_type '{target_unit_str}'", file=sys.stderr)
        return False

    def _check_rule_cooldowns(self, rule: dict) -> bool:
        """Checks internal and game cooldowns for a given rule. Returns True if ready, False if on cooldown."""
        now = time.time()
        spell_id = rule.get("detail") # Corrected to get 'detail' which holds spell ID for Spell action
        internal_cd = rule.get("cooldown", 0)
        action_type = rule.get("action", "Spell")

        # --- Check 1: Internal Cooldown (Defined in Rule) ---
        if spell_id and internal_cd > 0:
            last_exec = self.last_rule_executed_time.get(spell_id, 0)
            if now < last_exec + internal_cd:
                 # print(f"[CooldownCheck] Rule for {spell_id} on internal CD", file=sys.stderr)
                 return False # Rule is on internal cooldown

        # --- Check 2: Actual Game Cooldown (via IPC) ---
        if action_type == "Spell" and spell_id:
            try:
                cooldown_info = self.game.get_spell_cooldown(spell_id)
                if cooldown_info is None:
                    # print(f"[CooldownCheck] Cooldown check FAILED for spell {spell_id} (IPC error/timeout). Assuming NOT ready.", file=sys.stderr)
                    return False # Assume not ready if CD check fails
                elif not cooldown_info.get('isReady', False):
                    # remaining_cd = cooldown_info.get('remaining', 0)
                    # print(f"[CooldownCheck] Spell {spell_id} is on GAME cooldown ({remaining_cd:.1f}s remaining).", file=sys.stderr)
                    return False # Spell is on cooldown
                # else: Spell is ready according to game
            except Exception as e:
                print(f"[CooldownCheck] Error during get_spell_cooldown for {spell_id}: {e}", file=sys.stderr)
                return False # Assume not ready on error

        # --- Check 3: Global Cooldown (redundant with check at start of _execute_rule_engine, but safe) ---
        gcd_remaining = (self.last_action_time + self.gcd_duration) - now
        if gcd_remaining > 0:
             # print(f"[CooldownCheck] On GCD ({gcd_remaining:.2f}s remaining)", file=sys.stderr)
             return False # Still on GCD

        # If we passed all checks, the rule is ready regarding cooldowns
        return True

    def _execute_rule_action(self, rule: dict) -> bool:
        """Executes the action associated with a rule (e.g., cast spell)."""
        spell_id = rule.get("detail") # Use 'detail' for spell ID
        target_unit_str = rule.get("target", "target").lower() # Get target type string
        action_type = rule.get("action", "Spell") # Get action type
        action_succeeded_ingame = False # Track success based on C func/Lua result
        pipe_call_succeeded = False   # Track if the pipe communication worked

        if action_type == "Spell" and spell_id:
            # --- Resolve target object AGAIN, just before the action ---
            target_obj = None
            player = self.om.local_player
            if target_unit_str == "target":
                target_obj = self.om.target # Fetch current target from OM
            elif target_unit_str == "player":
                target_obj = player
            # TODO: Add focus, pet, mouseover later
            # elif target_unit_str == "focus": target_obj = self.om.get_object_by_guid(self.om.focus_guid)

            # Determine target GUID based on resolved object
            target_guid = 0 # Default to 0
            if target_obj and target_obj.guid: # Check if we found a valid object
                 target_guid = target_obj.guid
            else:
                 # If rule specified a target that doesn't resolve (e.g., 'target' but none selected at this exact moment),
                 # we default to GUID 0. The C function will handle this.
                 print(f"[Action] Warning: Rule target '{target_unit_str}' resolved to None just before action. Using Target GUID 0.", file=sys.stderr)

            # print(f"[Action] Attempting C Cast: Spell {spell_id} on GUID 0x{target_guid:X}", file=sys.stderr)
            try:
                # Call the GameInterface method using the internal C function via IPC
                # This now waits for CAST_RESULT and returns True/False based on it.
                action_succeeded_ingame = self.game.cast_spell(spell_id, target_guid)
                pipe_call_succeeded = True # If cast_spell returned without exception, pipe call worked

                if pipe_call_succeeded:
                    # Log success/failure based on C function result
                    if action_succeeded_ingame:
                         # print(f"[Action] CAST_SPELL for {spell_id} reported SUCCESS by DLL.", file=sys.stderr)
                         pass # Reduce log spam on success
                    else:
                         # print(f"[Action] CAST_SPELL for {spell_id} reported FAILURE by DLL (Returned 0). Possible reasons: OOM, LoS, Range, Target Invalid, etc.", file=sys.stderr)
                         pass # Reduce log spam on failure
                else:
                    # This case should technically not be reached if cast_spell returns bool
                    # but kept for robustness
                    print(f"[Action] Failed to send/receive CAST_SPELL command for {spell_id} via pipe.", file=sys.stderr)

            except Exception as e:
                print(f"[Action] Error during game.cast_spell IPC call for spell {spell_id} on GUID 0x{target_guid:X}: {e}", file=sys.stderr)
                action_succeeded_ingame = False
                pipe_call_succeeded = False # Pipe communication failed

        elif action_type == "Macro":
            macro_text = rule.get("detail")
            if macro_text:
                print(f"[Action] Macro execution not yet implemented: {macro_text}", file=sys.stderr) # Placeholder
                pipe_call_succeeded = False # Not implemented
                action_succeeded_ingame = False

        elif action_type == "Lua":
            lua_code_direct = rule.get("detail")
            if lua_code_direct:
                # print(f"[Action] Executing direct Lua from rule: {lua_code_direct}", file=sys.stderr)
                try:
                    response = self.game.execute(lua_code_direct)
                    # print(f"[Action] Direct Lua Response: {response}", file=sys.stderr)
                    # Basic check: Assume pipe call worked if no exception
                    pipe_call_succeeded = True
                    # Check if response indicates error
                    if response is None or (isinstance(response, str) and "ERROR" in response.upper()):
                        action_succeeded_ingame = False
                    else:
                        action_succeeded_ingame = True
                except Exception as e:
                    print(f"[Action] Error during game.execute for direct Lua: {e}", file=sys.stderr)
                    action_succeeded_ingame = False
                    pipe_call_succeeded = False

        # --- Decision Logic --- 
        # Update GCD timer if the PIPE CALL was successful, regardless of in-game success.
        # This prevents spamming actions that fail in-game but still trigger GCD.
        if pipe_call_succeeded:
            # print(f"[Engine] Pipe call for action '{action_type}' succeeded. Triggering GCD timer.", file=sys.stderr)
            self.last_action_time = time.time() # Record time for GCD
            # Also update internal cooldown tracking if the pipe call worked
            internal_cd = rule.get("cooldown", 0)
            if spell_id and internal_cd >= 0: # Check spell_id exists for spell actions
                 self.last_rule_executed_time[spell_id] = self.last_action_time
        # else:
             # print(f"[Engine] Pipe call for action '{action_type}' FAILED. Not triggering GCD timer.", file=sys.stderr)

        # Return the success status reported by the game/DLL (True if cast worked, False otherwise)
        # This determines if the rotation engine should break and consider the rule fulfilled.
        return action_succeeded_ingame

    