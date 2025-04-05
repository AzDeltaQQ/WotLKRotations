# WotLKRotations

A Python-based experimental framework for interacting with World of Warcraft (3.3.5a - 12340 client) memory to monitor game state and potentially execute combat rotations.

**Disclaimer:** This project involves reading game memory and potentially automating actions. Use at your own risk. Modifying game clients or using automation tools may violate the game's Terms of Service and could lead to account suspension.

## Current Features (as of initial commit):

*   **Memory Reading:** Establishes connection to the WoW 3.3.5a process using `pymem`.
*   **Object Manager:** 
    *   Finds the Object Manager pointer.
    *   Iterates through the object list.
    *   Identifies the local player and target.
*   **WoW Object Representation:**
    *   Reads core object data (GUID, Type, Position, Rotation).
    *   Reads Unit Fields data (Health, Max Health, Power Type, Flags, Level, Target GUID).
    *   Reads Player/Unit names (requires Name Cache reading).
    *   Reads Current/Max Health, Mana, and Energy for the player.
*   **Basic GUI (`gui.py`):
    *   Uses `tkinter` for the interface.
    *   Displays Player Name, HP, and Primary Resource (Mana/Energy).
    *   Displays Target Name, HP, and Primary Resource.
    *   Monitor tab showing nearby Player/Unit objects with basic details (GUID, Type, Name, HP, Power, Distance, Status).
    *   Log tab for debug output.
    *   Basic framework for Rotation Control and Editor tabs (not fully implemented).
*   **Lua Interface (`luainterface.py`):
    *   Finds the Lua state pointer.
    *   Basic functionality to execute Lua strings in the game (e.g., `RunString`).
    *   Framework for calling C functions within WoW's Lua environment (experimental, needs more testing).
*   **Combat Rotation (`combat_rotation.py`):**
    *   Placeholder class structure exists.
    *   Currently loads placeholder rules but does not execute complex logic.

## Current Status & Known Issues:

*   Core memory reading for player/target stats (HP, Mana, Energy) is functional.
*   Object monitoring tab displays nearby units.
*   Direct memory reads for certain power values (especially current values) seem inconsistent, potentially due to `pymem` limitations or timing issues. The current implementation uses offsets found through debugging that work within the `WowObject` class updates.
*   Reading unit names relies on finding and parsing the Name Cache, which can be complex.
*   Combat rotation logic is not implemented.
*   Lua C function calling needs thorough testing and likely refinement.
*   Error handling can be improved.
*   Offsets are hardcoded in `offsets.py` for client 12340.

## Next Steps (Potential):

1.  Implement and test combat rotation script loading and execution.
2.  Refine Lua interface for reliable spell casting, cooldown checks, and information retrieval.
3.  Improve stability and error handling.
4.  Investigate alternative memory reading methods if `pymem` inconsistencies persist.
5.  Add configuration options for offsets, settings, etc.

## Setup:

1.  Ensure Python 3 is installed.
2.  Install required library: `pip install pymem`
3.  Ensure WoW 3.3.5a (client build 12340) is running.
4.  Run the GUI: `python gui.py` 