import os # Needed for checking file existence
import time # May be needed for delays or GCD tracking
import json # For handling potential rule files
import sys # Added sys import
from memory import MemoryHandler
from object_manager import ObjectManager
# from luainterface import LuaInterface # Old
from gameinterface import GameInterface # New
# from rules import Rule, ConditionChecker # Import rule processing - ConditionChecker removed
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
        # Removed self.condition_checker - logic moved into _check_rule_conditions
        # self.rules: List[Rule] = [] # This wasn't used, app holds editor rules
        self.last_rule_execution_time: Dict[int, float] = {} # Store last time a rule (by index) was executed
        # For Script based rotations (Keep for potential future use)
        self.rotation_script_content: Optional[str] = None
        self.script_execution_interval = 1.0 # Default: execute script every 1 second
        self.last_script_execution_time = 0.0

        # Rotation State
        self.current_rotation_script_path = None # Path if using a Lua script file
        self.lua_script_content = None         # Content if using a Lua script file
        self.rotation_rules: List[Dict[str, Any]] = [] # Holds the RULES LOADED INTO THE ENGINE
        self.last_action_time = 0.0            # Timestamp of the last action taken
        self.gcd_duration = 1.5                # Default GCD in seconds (Needs dynamic update later)
        # Use spell ID as key for internal cooldown tracking
        self.last_spell_executed_time: dict[int, float] = {}


    def load_rotation_script(self, script_path: str) -> bool:
        """Reads the content of a Lua script file. Clears any existing rules in the ENGINE."""
        try:
            if os.path.exists(script_path):
                with open(script_path, 'r', encoding='utf-8') as f:
                    self.lua_script_content = f.read()
                self.current_rotation_script_path = script_path
                self._clear_engine_rules() # Clear engine rules when loading a script
                print(f"Successfully read Lua script: {script_path}", file=sys.stderr)
                return True
            else:
                print(f"Error: Rotation script not found at {script_path}", file=sys.stderr)
                self._clear_engine_rotation() # Clear engine state
                return False
        except Exception as e:
            print(f"Error reading rotation script {script_path}: {e}", file=sys.stderr)
            self._clear_engine_rotation() # Clear engine state
            return False

    def load_rotation_rules(self, rules: List[Dict[str, Any]]):
        """Loads rules (list of dicts) INTO THE ENGINE. Clears any existing script in the engine."""
        # Perform a deep copy or ensure the list is new if needed, but direct assign is usually fine
        self.rotation_rules = rules
        self._clear_engine_script() # Clear script in engine when loading rules
        self.last_spell_executed_time.clear() # Reset internal cooldown tracking
        print(f"Loaded {len(rules)} rotation rules into engine.", file=sys.stderr)

    def _clear_engine_script(self):
        """Clears loaded script data FROM THE ENGINE."""
        self.current_rotation_script_path = None
        self.lua_script_content = None

    def _clear_engine_rules(self):
         """Clears loaded rule data FROM THE ENGINE."""
         self.rotation_rules = []
         self.last_spell_executed_time.clear()

    def _clear_engine_rotation(self):
        """Clears both script and rule data FROM THE ENGINE."""
        self._clear_engine_script()
        self._clear_engine_rules()

    def run(self):
        """Executes the loaded rotation logic (prioritizes rules over script)."""
        # print("[Run] Entering run method", file=sys.stderr) # Debug Entry

        player = self.om.local_player
        # print(f"[Run] Player object: {'Exists' if player else 'None'}", file=sys.stderr) # Debug Player Check 1
        if not player:
            # print("[Run] Exiting: No local player found.", file=sys.stderr) # DEBUG
            return

        is_dead = player.is_dead
        # print(f"[Run] Player is_dead: {is_dead}", file=sys.stderr) # Debug Player Check 2
        if is_dead:
            # print("[Run] Exiting: Player is dead.", file=sys.stderr) # DEBUG
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
            # print("[Run] Exiting: No rules, attempting Lua script (Not fully implemented).", file=sys.stderr) # DEBUG
            if not self.game.is_ready(): return # Need Lua for script execution
            # Execute the entire loaded script content
            source_name = os.path.basename(self.current_rotation_script_path or "RotationScript")
            self.game.execute(self.lua_script_content, source_name=source_name)
            # Note: Timing/GCD for monolithic scripts must be handled *within* the script itself.
        # --- No rotation loaded --- 
        else:
            # print("[Run] Exiting: No rules or script loaded.", file=sys.stderr) # DEBUG
            pass # No rotation active


    def _execute_rule_engine(self):
        """Runs the rule-based rotation logic."""
        # print("[Engine] Entering _execute_rule_engine", file=sys.stderr) # Debug Entry
        if not self.game or not self.game.is_ready():
            # print("[Engine] Exiting: Game interface not ready.", file=sys.stderr) # DEBUG
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
            spell_id = rule.get("detail") if rule.get("action") == "Spell" else None
            internal_cd = rule.get("cooldown", 0.0)
            action_type = rule.get("action", "Spell")

            # --- Check Conditions FIRST --- # 
            # Pass the entire rule dictionary to the condition checker
            if not self._check_rule_conditions(rule):
                # print(f"[Engine] Conditions failed for rule: {rule}", file=sys.stderr)
                continue # Move to the next rule if conditions aren't met
            # else:
            #    print(f"[Engine] Conditions PASSED for rule: {rule}", file=sys.stderr)

            # --- ADDED: Check if rule targets "target" and target actually exists (if needed by action/conditions) --- #
            # This check might be implicitly handled by condition checks now, but keep as safety?
            target_unit_str = rule.get("target", "target").lower()
            needs_om_target = target_unit_str == "target" # Does rule explicitly target "target"?
            # Does any condition require the target?
            # conditions_require_target = any(c.get("condition", "").startswith("Target") for c in rule.get("conditions", []))
            # if (needs_om_target or conditions_require_target) and self.om.target is None:
            if needs_om_target and self.om.target is None: # Simplified: Only check if rule targets 'target' explicitly
                 # print(f"[Engine] Skipping rule for {action_type}:{spell_id} - Rule targets 'target', but no target selected.", file=sys.stderr)
                 continue # Skip this rule if it needs a target and none exists
            # ------------------------------------------------------------------------ #

            # --- Check Cooldowns (Global and Internal) only if conditions passed --- #
            # Pass rule for internal CD check, spell_id for game CD check
            if not self._check_rule_cooldowns(rule, spell_id):
                # print(f"[Engine] Cooldown failed for rule action: {action_type}:{spell_id}", file=sys.stderr)
                continue # Move to the next rule if on cooldown
            # else:
            #    print(f"[Engine] Cooldown PASSED for rule action: {action_type}:{spell_id}", file=sys.stderr)

            # --- Execute Action if Conditions and Cooldowns Pass --- # 
            # print(f"[Engine] Attempting action for rule...", file=sys.stderr)
            action_succeeded_ingame = self._execute_rule_action(rule)

            if action_succeeded_ingame:
                # print(f"[Engine] Action SUCCEEDED in-game, breaking loop for this tick.", file=sys.stderr)
                # Update internal cooldown ONLY on successful execution
                if spell_id and internal_cd >= 0:
                    self.last_spell_executed_time[spell_id] = now
                break # Action successful, exit the loop for this tick
            # else:
                 # print(f"[Engine] Action FAILED in-game (or pipe failed), continuing to next rule.", file=sys.stderr)
                 # Continue to the next rule if the action failed in-game
                 # pass


    def _check_rule_conditions(self, rule: Dict[str, Any]) -> bool:
        """
        Evaluates ALL conditions defined in the rule's 'conditions' list.
        Returns True if ALL conditions pass, False otherwise (AND logic).
        """
        conditions: List[Dict[str, Any]] = rule.get("conditions", [])
        target_unit_str = rule.get("target", "target").lower() # Target defined for the whole rule

        # If no conditions, the rule passes automatically
        if not conditions:
            return True

        # Resolve target object ONCE for all conditions in this rule
        player = self.om.local_player # Get local player ref
        if not player: return False # Need player for player-based checks

        target_obj = None
        if target_unit_str == "target":
            target_obj = self.om.target # Fetch current target from OM
        elif target_unit_str == "player":
            target_obj = player
        # TODO: Add focus, pet, mouseover later
        # elif target_unit_str == "focus": target_obj = self.om.get_object_by_guid(self.om.focus_guid)

        # Iterate through each condition dictionary in the list
        for condition_data in conditions:
            condition_str = condition_data.get("condition", "None").strip()
            value_x = condition_data.get("value_x") # Can be None
            value_y = condition_data.get("value_y") # Can be None
            value_text = condition_data.get("text") # Can be None

            # --- Evaluate the single condition --- 
            # If ANY condition fails, the whole rule fails (return False)
            if not self._evaluate_single_condition(condition_str, value_x, value_y, value_text, player, target_obj):
                # print(f"[Condition] FAILED: {condition_str} (Values: x={value_x}, y={value_y}, text={value_text})", file=sys.stderr)
                return False # Exit early
            # else: print(f"[Condition] PASSED: {condition_str}", file=sys.stderr)

        # If loop completes without returning False, all conditions passed
        return True

    def _evaluate_single_condition(
        self,
        condition_str: str,
        value_x: Optional[Any],
        value_y: Optional[Any],
        value_text: Optional[str],
        player: WowObject, # Pass player directly
        target_obj: Optional[WowObject] # Pass resolved target object
        ) -> bool:
        """Evaluates a single condition string with its associated values."""

        # --- Basic Checks (Don't need target_obj) --- 
        if condition_str == "None": return True
        if condition_str == "Player Is Casting": return player.is_casting or player.is_channeling
        if condition_str == "Player Is Moving": return False # Placeholder - requires velocity check
        if condition_str == "Player Is Stealthed": return False # Placeholder - requires Aura check

        # --- Target Presence/Validity Checks --- 
        if condition_str == "Target Exists":
             is_valid_target = target_obj and not target_obj.is_dead
             return is_valid_target
        if condition_str == "Target Attackable": # Basic check
             return target_obj and not target_obj.is_dead and target_obj.is_attackable

        # --- Prerequisite: Check if target_obj is needed AND exists --- 
        # Determine if the condition string implies a target is needed
        needs_target = condition_str.startswith("Target") or condition_str == "Is Spell Ready" # Spell readiness often depends on target
        if needs_target and not target_obj:
            # print(f"[Condition] Prerequisite FAILED - Condition '{condition_str}' needs target, but it is None", file=sys.stderr)
            return False # Cannot evaluate target conditions without a target

        # --- Player Resource/State Checks (May need value_x) --- 
        try:
            if condition_str == "Player HP % < X":
                if value_x is None: return False
                return player.max_health > 0 and (player.health / player.max_health * 100) < float(value_x)
            if condition_str == "Player HP % > X":
                if value_x is None: return False
                return player.max_health > 0 and (player.health / player.max_health * 100) > float(value_x)
            if condition_str == "Player Rage >= X":
                if value_x is None: return False
                return player.power_type == WowObject.POWER_RAGE and player.energy >= int(value_x)
            if condition_str == "Player Energy >= X":
                if value_x is None: return False
                return player.power_type == WowObject.POWER_ENERGY and player.energy >= int(value_x)
            if condition_str == "Player Mana % < X":
                if value_x is None: return False
                return player.power_type == WowObject.POWER_MANA and player.max_energy > 0 and \
                       (player.energy / player.max_energy * 100) < float(value_x)
            if condition_str == "Player Mana % > X":
                 if value_x is None: return False
                 return player.power_type == WowObject.POWER_MANA and player.max_energy > 0 and \
                        (player.energy / player.max_energy * 100) > float(value_x)
            if condition_str == "Player Combo Points >= X":
                 # Use GameInterface IPC call to get combo points
                 cp = self.game.get_combo_points() if self.game else None
                 if cp is None: return False # Cannot evaluate if unknown
                 return cp >= value_x

        except (ValueError, TypeError, ZeroDivisionError) as e:
            print(f"[Condition] Error evaluating player condition '{condition_str}' with value '{value_x}': {e}", file=sys.stderr)
            return False

        # --- Target State Checks (Requires target_obj and possibly value_x/y/text) --- 
        # These only run if target_obj exists (checked above)
        if target_obj:
            try:
                if condition_str == "Target Is Casting":
                    return target_obj.is_casting or target_obj.is_channeling
                if condition_str == "Target HP % < X":
                    if value_x is None: return False
                    return target_obj.max_health > 0 and (target_obj.health / target_obj.max_health * 100) < float(value_x)
                if condition_str == "Target HP % > X":
                    if value_x is None: return False
                    return target_obj.max_health > 0 and (target_obj.health / target_obj.max_health * 100) > float(value_x)
                if condition_str == "Target HP % Between X-Y":
                    if value_x is None or value_y is None: return False
                    if target_obj.max_health <= 0: return False
                    current_pct = (target_obj.health / target_obj.max_health * 100)
                    return float(value_x) <= current_pct <= float(value_y)
                if condition_str == "Target Distance < X":
                    if value_x is None: return False
                    dist = player.distance_to(target_obj) # Assumes WowObject has distance_to method
                    return dist >= 0 and dist < float(value_x)
                if condition_str == "Target Distance > X":
                    if value_x is None: return False
                    dist = player.distance_to(target_obj) # Assumes WowObject has distance_to method
                    return dist >= 0 and dist > float(value_x)
                # --- Aura Checks (Placeholders - Need Lua/DLL implementation) --- 
                if condition_str == "Target Has Aura":
                    if value_text is None: return False
                    # Placeholder: return self.game.has_aura(target_obj.guid, value_text)
                    print(f"[Condition] Placeholder Check: Target Has Aura '{value_text}'", file=sys.stderr)
                    return False # Assume false until implemented
                if condition_str == "Target Missing Aura":
                    if value_text is None: return False
                    # Placeholder: return not self.game.has_aura(target_obj.guid, value_text)
                    print(f"[Condition] Placeholder Check: Target Missing Aura '{value_text}'", file=sys.stderr)
                    return True # Assume true until implemented

            except (ValueError, TypeError, ZeroDivisionError) as e:
                 print(f"[Condition] Error evaluating target condition '{condition_str}' with values x={value_x},y={value_y},text={value_text}: {e}", file=sys.stderr)
                 return False

        # --- Player Aura Checks (Placeholders - Need Lua/DLL implementation) --- 
        if condition_str == "Player Has Aura":
             if value_text is None: return False
             # Placeholder: return self.game.has_aura(player.guid, value_text)
             print(f"[Condition] Placeholder Check: Player Has Aura '{value_text}'", file=sys.stderr)
             return False # Assume false until implemented
        if condition_str == "Player Missing Aura":
             if not target_obj or not value_text: return False # Requires target and text
             return not self.game.has_aura(target_obj.guid, value_text)
        if condition_str == "Player Is Behind Target":
            if not target_obj: return False # Requires target
            result = self.game.is_behind_target(target_obj.guid)
            self.logger(f"Check Condition: {condition_str} on {target_obj.guid:X} -> {result}", "DEBUG")
            return result if result is not None else False # Treat None as False

        # --- Spell Readiness Check (Needs game interaction) --- 
        if condition_str == "Is Spell Ready":
            # This check might need the *rule* context if spell ID isn't in the condition data
            # For now, assume spell ID needs to be passed or found elsewhere
            print(f"[Condition] Placeholder Check: Is Spell Ready (Needs Spell ID)", file=sys.stderr)
            return True # Assume true until implemented


        # Fallback: Condition not recognized or target was required but None
        print(f"Warning: Unrecognized or inapplicable condition: '{condition_str}'", file=sys.stderr)
        return False

    def _check_rule_cooldowns(self, rule: dict, spell_id: Optional[int]) -> bool:
        """Checks internal and game cooldowns. Returns True if ready, False if on cooldown."""
        now = time.time()
        internal_cd = rule.get("cooldown", 0.0)
        action_type = rule.get("action", "Spell")

        # --- Check 1: Internal Cooldown (Defined in Rule) --- 
        # Use spell_id as key if available for spell actions
        if spell_id and internal_cd > 0:
            last_exec = self.last_spell_executed_time.get(spell_id, 0)
            if now < last_exec + internal_cd:
                 # print(f"[CooldownCheck] Rule for {spell_id} on internal CD", file=sys.stderr)
                 return False # Rule is on internal cooldown
        # Add similar check for non-spell actions if needed, maybe using rule index or action detail?

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

        # --- Check 3: Global Cooldown (redundant check at start of _execute_rule_engine is primary) ---
        # gcd_remaining = (self.last_action_time + self.gcd_duration) - now
        # if gcd_remaining > 0:
        #      # print(f"[CooldownCheck] On GCD ({gcd_remaining:.2f}s remaining)", file=sys.stderr)
        #      return False # Still on GCD

        # If we passed all checks, the rule is ready regarding cooldowns
        return True

    def _execute_rule_action(self, rule: dict) -> bool:
        """Executes the action associated with a rule (e.g., cast spell)."""
        action_type = rule.get("action", "Spell")
        detail = rule.get("detail") # Spell ID, Macro Text, Lua Code
        target_unit_str = rule.get("target", "target").lower() # Get target type string
        action_succeeded_ingame = False # Track success based on C func/Lua result
        pipe_call_succeeded = False   # Track if the pipe communication worked

        if not detail:
             print(f"[Action] Skipping rule: Action '{action_type}' has no detail.", file=sys.stderr)
             return False # Cannot execute without detail

        # --- Resolve Target GUID (Only needed for Cast Spell action) --- 
        target_guid = 0 # Default to 0
        if action_type == "Spell":
            # Resolve target object just before the action
            target_obj = None
            player = self.om.local_player
            if target_unit_str == "target":
                target_obj = self.om.target # Fetch current target from OM
            elif target_unit_str == "player":
                target_obj = player
            # TODO: Add focus, pet, mouseover later
            # elif target_unit_str == "focus": target_obj = self.om.get_object_by_guid(self.om.focus_guid)

            # Determine target GUID based on resolved object
            if target_obj and target_obj.guid: # Check if we found a valid object
                 target_guid = target_obj.guid
            # else:
                 # If rule specified a target that doesn't resolve (e.g., 'target' but none selected),
                 # we default to GUID 0. The C function should handle this (e.g., cast on self or fail).
                 # print(f"[Action] Warning: Rule target '{target_unit_str}' resolved to None just before action. Using Target GUID 0.", file=sys.stderr)

        # --- Perform Action --- 
        try:
            if action_type == "Spell":
                spell_id = int(detail) # Detail is spell ID
                # print(f"[Action] Attempting C Cast: Spell {spell_id} on GUID 0x{target_guid:X}", file=sys.stderr)
                action_succeeded_ingame = self.game.cast_spell(spell_id, target_guid)
                pipe_call_succeeded = True # cast_spell returns bool, no exception means pipe worked

            elif action_type == "Macro":
                macro_text = str(detail) # Detail is macro text
                print(f"[Action] Macro execution via Lua for: {macro_text}", file=sys.stderr)
                # Use Lua to run the macro
                lua_command = f'RunMacroText("{macro_text}")'
                response = self.game.execute(lua_command)
                pipe_call_succeeded = True # Assume pipe worked if execute returned
                action_succeeded_ingame = response is not None # Basic check: assume success if Lua didn't error explicitly

            elif action_type == "Lua":
                lua_code_direct = str(detail) # Detail is Lua code
                # print(f"[Action] Executing direct Lua from rule: {lua_code_direct}", file=sys.stderr)
                response = self.game.execute(lua_code_direct)
                pipe_call_succeeded = True
                # Assume success if response isn't explicitly an error
                action_succeeded_ingame = response is not None and "ERROR" not in str(response).upper()

        except ValueError:
             print(f"[Action] Error: Invalid detail format for action '{action_type}'. Detail: '{detail}'", file=sys.stderr)
             action_succeeded_ingame = False
             pipe_call_succeeded = False
        except Exception as e:
            print(f"[Action] Error during game interaction for action '{action_type}' ({detail}): {e}", file=sys.stderr)
            action_succeeded_ingame = False
            pipe_call_succeeded = False

        # --- Post-Action Logic --- 
        # Update GCD timer if the PIPE CALL was successful, regardless of in-game success.
        # This prevents spamming actions that fail in-game but might still trigger GCD.
        if pipe_call_succeeded:
            # print(f"[Engine] Pipe call for action '{action_type}' succeeded. Triggering GCD timer.", file=sys.stderr)
            self.last_action_time = time.time() # Record time for GCD
            # Internal CD update moved to main loop, only happens on action_succeeded_ingame=True
        # else:
             # print(f"[Engine] Pipe call for action '{action_type}' FAILED. Not triggering GCD timer.", file=sys.stderr)

        # Return the success status reported by the game/DLL (True if cast worked, False otherwise)
        # This determines if the rotation engine should break and consider the rule fulfilled.
        return action_succeeded_ingame

    