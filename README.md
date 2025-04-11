# PyWoW Bot - WoW 3.3.5a Interaction Framework

A Python and C++ experimental framework for interacting with World of Warcraft (specifically 3.3.5a - client build 12340) to monitor game state, execute Lua, and implement combat rotations using a rule-based engine.

**Disclaimer:** This project involves reading game memory, injecting DLLs, and potentially automating actions. Use entirely at your own risk. Modifying game clients or using automation tools typically violates the game's Terms of Service and could lead to account suspension. This tool is intended for educational and research purposes on private servers or sandboxed environments.

## Architecture

This project uses a two-part architecture:

1.  **Python Frontend & Core Logic:**
    *   **GUI (`gui.py` & `gui/` directory):**
        *   The main application logic resides in `gui.py` (`WowMonitorApp` class). It handles window creation, core component initialization (memory, objects, game interface, rotation engine), the main update loop, status bar, configuration, and shared state/variables.
        *   The UI for each tab (Monitor, Rotation Control, Rotation Editor, Lua Runner, Log) is managed by separate handler classes within the `gui/` subdirectory (e.g., `gui/monitor_tab.py` contains `MonitorTab`).
        *   These tab handlers create their specific widgets and handle tab-local logic, interacting with the main `WowMonitorApp` instance for shared data and core functionalities.
        *   Uses `tkinter` with the `sv-ttk` theme.
    *   **Memory Handler (`memory.py`):** Uses `pymem` to attach to the WoW process and read/write memory.
    *   **Object Manager (`object_manager.py`):** Reads the WoW object list, manages a cache of `WowObject` instances, and identifies the local player and target. Reads dynamic object data like health, power, position, status flags, and known spell IDs directly from memory.
    *   **WoW Object (`wow_object.py`):** Represents game objects (players, units) and reads their properties from memory using offsets defined in `offsets.py`.
    *   **Game Interface (`gameinterface.py`):** Manages communication with the injected C++ DLL via **Named Pipes**. Sends commands (like `EXEC_LUA`, `GET_TIME_MS`, `GET_CD`, `IS_IN_RANGE`, `GET_SPELL_INFO`, `CAST_SPELL`, `GET_TARGET_GUID`, `GET_COMBO_POINTS`, `CHECK_BACKSTAB_POS`) and receives responses. Handles asynchronous communication.
    *   **Combat Rotation (`combat_rotation.py`):** Engine capable of executing rotations based on prioritized rules defined in the GUI editor. Includes a `ConditionChecker` for evaluating rule conditions.
    *   **Target Selector (`targetselector.py`):** Basic framework for target selection logic.
    *   **Offsets (`offsets.py`):** Contains memory addresses and structure offsets specific to WoW 3.3.5a (12340).
    *   **Rules (`rules.py`):** Defines the structure for rotation rules used by the editor. Rules are saved/loaded as `.json` files in the `Rules/` directory.

2.  **C++ Injected DLL (`WowInjectDLL/`):**
    *   **Core Logic (`dllmain.cpp`):** Written in C++, compiled into `WowInjectDLL.dll`.
    *   **Detours Hooking:** Uses Microsoft Detours (included in `vendor/Detours`) to hook the game's `EndScene` function (DirectX 9).
    *   **Persistent Named Pipe Server:** Creates and manages a named pipe (`\\.\\pipe\\WowInjectPipe`) allowing the Python GUI to reconnect without reinjecting the DLL.
    *   **Command Handling:** Parses commands received over the pipe (e.g., `ping`, `EXEC_LUA:<code>`, `GET_TIME_MS`, `GET_CD:<id>`, `IS_IN_RANGE:<id>,<unit>`, `GET_SPELL_INFO:<id>`, `CAST_SPELL:<id>[,guid]`, `GET_TARGET_GUID`, `GET_COMBO_POINTS`, `CHECK_BACKSTAB_POS:<guid>`).
    *   **Main Thread Execution:** Queues requests and processes them within the hooked `EndScene` function.
    *   **Lua Interaction:** Uses known function pointers to execute Lua code or interact with the Lua C API (e.g., `GetTime()`, `GetSpellCooldown()`, `IsSpellInRange()`, `GetSpellInfo()`).
    *   **Internal Function Calls:** Uses known function pointers to directly call game C functions (e.g., `CastLocalPlayerSpell`, `findObjectByGuidAndFlags`, `isUnitVectorDifferenceWithinHemisphere`).
    *   **Memory Reads:** Directly reads specific game data like Target GUID (static address), Combo Points (static address), and Player GUID (via OM structure) upon request from Python via pipe commands.
    *   **Build System (`CMakeLists.txt`):** Uses CMake to manage the C++ build process.

## Current Features

*   **Process Attachment & Memory Reading:** Connects to `Wow.exe`.
*   **Object Management:** Iterates object list, identifies player/target, caches objects, reads known spell IDs.
*   **Game State Monitoring:** GUI displays real-time player/target/nearby unit info (HP, Power, Pos, Status, Dist).
*   **Object List Filtering:** GUI filter for displayed object types (Players, Units).
*   **Persistent Named Pipe IPC:** Robust communication between Python and DLL.
*   **Lua Execution:** Execute arbitrary Lua code via DLL (`Lua Runner` tab and rule actions).
*   **Game State via DLL:** Get time, spell cooldowns, spell range, spell info, target GUID (static read), combo points (static read), backstab position check (internal funcs) via pipe commands.
*   **Spell Casting:** Cast spells via DLL (`CAST_SPELL` command or `CastSpellByID` Lua call).
*   **Combo Points Retrieval:** Get combo points via DLL (`GET_COMBO_POINTS` command).
*   **Target GUID Retrieval:** Get target GUID via DLL (`GET_TARGET_GUID` command).
*   **Backstab Position Check:** Check if player is behind target via DLL (`CHECK_BACKSTAB_POS` command).
*   **Rule-Based Rotation Engine:**
    *   GUI editor (`Rotation Editor` tab) to define prioritized rules.
    *   Available Actions: `Spell`, `Macro` (not implemented), `Lua`.
    *   Available Targets: `target`, `player`, `focus`, `pet`, `mouseover`.
    *   Available Conditions:
        *   Simple: `None`, `Target Exists`, `Target Attackable` (basic), `Player Is Casting`, `Target Is Casting`, `Player Is Moving`, `Player Is Stealthed`.
        *   Health/Resource: `Target HP % < X`, `Target HP % > X`, `Target HP % Between X-Y`, `Player HP % < X`, `Player HP % > X`, `Player Rage >= X`, `Player Energy >= X`, `Player Mana % < X`, `Player Mana % > X`, `Player Combo Points >= X` (Requires `Condition Value (X/Y)` input).
        *   Distance: `Target Distance < X`, `Target Distance > X`.
        *   Spell/Aura: `Is Spell Ready`, `Target Has Aura`, `Target Missing Aura`, `Player Has Aura`, `Player Missing Aura` (Requires `Name/ID` input).
    *   Condition checks happen *before* cooldown checks for efficiency.
    *   Rules targeting "target" automatically check if a target exists before proceeding.
    *   GUI supports inputting the `X/Y` or `Name/ID` values for relevant conditions.
    *   Save/Load rules to/from `.json` files in the `Rules/` directory.
    *   Activate rules from editor or loaded files via the `Rotation Control / Test` tab.
*   **GUI Controls:** Test buttons for key DLL functions.
*   **Logging:** GUI Log tab captures output. DLL uses `OutputDebugStringA`.
*   **Spellbook Scanner & Lookup:** GUI utilities.

## Dependencies

*   **Python 3.x**
*   **`pymem`:** (`pip install pymem`)
*   **`sv-ttk`:** (`pip install sv-ttk`) # For GUI theme
*   **CMake:** Build system generator (Download from [cmake.org](https://cmake.org/download/)).
*   **C++ Compiler:** Supports C++17 (e.g., Visual Studio Community Edition with "Desktop development with C++" workload).
*   **Microsoft Detours:** Included in the `vendor/Detours` directory (no separate install needed).
*   **WoW Client:** Specifically version 3.3.5a (build 12340).
*   **DLL Injector:** Tool to load `WowInjectDLL.dll` into `Wow.exe` (e.g., Process Hacker, Xenos Injector).

## Setup & Usage

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Install Python Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Build the C++ DLL (`WowInjectDLL.dll`):**
    *   Ensure CMake and a C++ Compiler are installed.
    *   Open a terminal in the project's root directory.
    *   **Configure CMake:**
        ```bash
        # Create build directory & configure (adjust generator if needed, use Win32 for 32-bit WoW)
        cmake -S WowInjectDLL -B build -A Win32
        # Example for VS 2022: cmake -S WowInjectDLL -B build -G "Visual Studio 17 2022" -A Win32
        ```
    *   **Build the DLL:**
        ```bash
        # Build the Release configuration
        cmake --build build --config Release
        ```
    *   The compiled `WowInjectDLL.dll` will be in `build/Release/`.

4.  **Run:**
    *   Start World of Warcraft 3.3.5a (12340).
    *   **Inject the DLL:** Use your injector to load `build/Release/WowInjectDLL.dll` into `Wow.exe`.
    *   **(Optional):** Run DebugView as Administrator to see DLL logs.
    *   **Run the Python GUI:**
        ```bash
        python gui.py
        ```
    *   The GUI connects to WoW and the DLL pipe. Use the tabs to monitor, edit rules, load rules/scripts, and start/stop the rotation.
    *   Rules are saved/loaded to/from the `Rules/` directory (created automatically if needed).

## Development Notes & Known Issues

*   Offsets are specific to WoW 3.3.5a (12340).
*   **Recent Changes:**
    *   Refactored GUI code into separate tab handler modules (`gui/` directory) for better organization.
    *   Fixed various initialization errors related to GUI state and attribute access.
    *   Improved IPC/DLL stability for cooldown/casting.
    *   Fixed GCD handling after spell casts.
    *   Implemented resource/distance conditions (e.g., `Player Energy >= X`) with GUI input.
    *   Fixed rotation engine logic to check conditions *before* cooldowns.
    *   Added check to ensure a target exists for rules specifying "target".
    *   Fixed `GET_TARGET_GUID` IPC command by using direct static memory read in DLL and correcting Python parsing.
    *   Implemented `CHECK_BACKSTAB_POS` IPC command using internal game functions (`findObjectByGuidAndFlags`, `isUnitVectorDifferenceWithinHemisphere`) and dynamic player GUID reading.
*   Rotation engine condition checking for Auras, Spell Readiness, etc., are still placeholders and need implementation (likely via Lua/DLL).
*   The `is_attackable` check logic may need refinement based on specific unit flags.
*   Macro execution via rules is not implemented.

## Deprecated Features (Replaced by DLL/IPC)

*   Direct Python shellcode injection.
*   Direct memory reads from Python for cooldowns, range, time (replaced by DLL calls).

## Next Steps (Potential):

1.  Implement Aura and Spell Readiness condition checks via Lua/DLL.
2.  Add more game interaction functions to the DLL (TargetUnit, GetAuraInfo, Interact, etc.).
3.  Implement reliable GCD tracking (e.g., via Lua `GetSpellCooldown`).
4.  Refine `is_attackable` logic.
5.  Add macro execution.

## Setup:

1.  Ensure Python 3 is installed.
2.  Install required library: `pip install pymem`
3.  Ensure WoW 3.3.5a (client build 12340) is running.
4.  Run the GUI: `python gui.py`

## Setup

1.  **Requirements:**
    *   Python 3.x
    *   `pywin32` (`pip install pywin32`)
    *   `psutil` (`pip install psutil`)
    *   `sv-ttk` (`pip install sv-ttk`) # For the GUI theme
    *   A C++ compiler supporting C++17 (e.g., Visual Studio with CMake integration).
    *   CMake.
    *   Detours library (submoduled or placed in a known location for CMake).

### Rotation Editor Tab

The Rotation Editor allows you to define sequences of actions (casting spells, using macros, running Lua) based on specific conditions. Rules are evaluated top-down, and the first rule whose conditions are met will have its action executed.

#### Multiple Conditions per Rule
*   **AND Logic:** You can now add multiple conditions to a single rule. The rule will only execute if *all* of its conditions evaluate to true.
*   **GUI:** Use the 'Condition' dropdown, value fields, and the 'Add Cond.' button to build up a list of conditions for the currently selected or new rule. These appear in the 'Current Rule Conditions' listbox. Use 'Remove Cond.' to remove a selected condition from this temporary list before adding/updating the rule.

#### Rule Structure (JSON Format)

Rules are saved in JSON format (e.g., in the `Rules/` directory). Here's an example structure:

```json
[
  {
    "action": "Spell", 
    "detail": 2098,      # Spell ID (e.g., Eviscerate)
    "target": "target", 
    "conditions": [     # List of conditions (AND logic)
      {
        "condition": "Player Energy >= X",
        "value_x": 35.0
      },
      {
        "condition": "Player Combo Points >= X",
        "value_x": 3.0
      }
    ],
    "cooldown": 0.0       # Internal cooldown (seconds) for this specific rule line
  },
  {
    "action": "Spell",
    "detail": 1752,      # Spell ID (e.g., Sinister Strike)
    "target": "target",
    "conditions": [     # Can have single or no conditions
      {
        "condition": "Player Energy >= X",
        "value_x": 45.0
      }
    ],
    "cooldown": 0.0
  }
  // ... more rules
]
```

*   **action**: Type of action ("Spell", "Macro", "Lua").
*   **detail**: Spell ID, Macro Text, or Lua code string.
*   **target**: Target unit ("target", "player", "focus", "pet", etc.).
*   **conditions**: A list of condition objects. The rule executes only if all conditions in the list are true.
    *   **condition**: The condition string (e.g., "Player Energy >= X").
    *   **value_x**, **value_y**, **text**: Optional values used by the specific condition string.
*   **cooldown**: An optional internal cooldown (in seconds) applied *only* to this specific rule line after it executes successfully. This is separate from the spell's actual game cooldown.

### Lua Runner Tab

The Lua Runner tab allows you to execute arbitrary Lua code directly from the GUI. This is useful for testing Lua scripts or running custom Lua code without needing to create a rule.

*   **Lua Code Input:** Enter the Lua code you want to execute in the text area.
*   **Execute:** Click the 'Execute' button to run the Lua code.
*   **Output:** The result of the Lua execution will be displayed in the output area below the text area.

## Setup:

1.  Ensure Python 3 is installed.
2.  Install required library: `pip install pymem`
3.  Ensure WoW 3.3.5a (client build 12340) is running.
4.  Run the GUI: `python gui.py`

## Setup

1.  **Requirements:**
    *   Python 3.x
    *   `pywin32` (`pip install pywin32`)
    *   `psutil` (`pip install psutil`)
    *   `sv-ttk` (`pip install sv-ttk`) # For the GUI theme
    *   A C++ compiler supporting C++17 (e.g., Visual Studio with CMake integration).
    *   CMake.
    *   Detours library (submoduled or placed in a known location for CMake). 