# PyWoW Bot - WoW 3.3.5a Interaction Framework

A Python and C++ experimental framework for interacting with World of Warcraft (specifically 3.3.5a - client build 12340) to monitor game state, execute Lua, call internal game functions, and implement combat rotations using a rule-based engine.

**Disclaimer:** This project involves reading game memory, injecting DLLs, and potentially automating actions. Use entirely at your own risk. Modifying game clients or using automation tools typically violates the game's Terms of Service and could lead to account suspension. This tool is intended for educational and research purposes on private servers or sandboxed environments.

## Architecture

This project uses a two-part architecture:

1.  **Python Frontend & Core Logic:**
    *   **GUI (`gui.py` & `gui/` directory):**
        *   The main application logic resides in `gui.py` (`WowMonitorApp` class). It handles window creation, core component initialization (memory, objects, game interface, rotation engine), the main update loop, status bar, configuration, and shared state/variables.
        *   The UI for each tab (Monitor, Rotation Control, Rotation Editor, Lua Runner, Log) is managed by separate handler classes within the `gui/` subdirectory (e.g., `gui/monitor_tab.py` contains `MonitorTab`).
        *   These tab handlers create their specific widgets and handle tab-local logic, interacting with the main `WowMonitorApp` instance for shared data and core functionalities.
        *   Uses `tkinter` with the `sv-ttk` theme.
    *   **Memory Handler (`memory.py`):** Uses `pymem` to attach to the WoW process and read memory (primarily for Object Manager).
    *   **Object Manager (`object_manager.py`):** Reads the WoW object list, manages a cache of `WowObject` instances, and identifies the local player and target. Reads dynamic object data like health, power, position, status flags, and known spell IDs directly from memory.
    *   **WoW Object (`wow_object.py`):** Represents game objects (players, units) and reads their properties from memory using offsets defined in `offsets.py`.
    *   **Game Interface (`gameinterface.py`):** Manages communication with the injected C++ DLL via **Named Pipes**. Sends commands (see DLL features below) and receives responses. Handles connection, disconnection, and command/response formatting.
    *   **Combat Rotation (`combat_rotation.py`):** Engine capable of executing rotations based on prioritized rules defined in the GUI editor. Evaluates conditions using data from Object Manager and Game Interface.
    *   **Target Selector (`targetselector.py`):** Basic framework for target selection logic.
    *   **Offsets (`offsets.py`):** Contains memory addresses and structure offsets specific to WoW 3.3.5a (12340).
    *   **Rules (`rules.py`):** Defines the structure for rotation rules used by the editor. Rules are saved/loaded as `.json` files in the `Rules/` directory.

2.  **C++ Injected DLL (`WowInjectDLL/`):**
    *   **Modular Design:** Code is organized into logical units:
        *   `dllmain.cpp`: Entry point, thread initialization, basic setup/shutdown.
        *   `globals.h`/`.cpp`: Shared variables, constants, typedefs, queues, mutex.
        *   `pch.h`/`.cpp`: Precompiled header setup.
        *   `offsets.h`: C++ offsets corresponding to `offsets.py`.
        *   `ipc_manager.h`/`.cpp`: Handles the Named Pipe server thread, reads incoming commands, sends responses back to Python. Uses message-based pipe communication.
        *   `hook_manager.h`/`.cpp`: Manages the DirectX `EndScene` hook using Detours. Dequeues requests from the IPC thread.
        *   `command_processor.h`/`.cpp`: Contains the `ProcessCommand` function which acts as a central dispatcher based on request type. Calls appropriate functions from `game_state` or `game_actions`. Queues responses.
        *   `lua_interface.h`/`.cpp`: Wraps interaction with WoW's Lua C API (state retrieval, pcall execution, stack manipulation).
        *   `game_state.h`/`.cpp`: Functions for querying game state (e.g., `GetTargetGUID`, `GetComboPoints`, `IsBehindTarget`, Lua-based checks like `GetSpellCooldown`, `IsSpellInRange`).
        *   `game_actions.h`/`.cpp`: Functions for performing actions (e.g., `CastSpell`).
    *   **IPC Mechanism:** Uses a named pipe (`\\.\\pipe\WowInjectPipe`) for two-way communication with Python.
        *   Python sends command strings (e.g., `EXEC_LUA:<code>`, `CAST_SPELL:<id>,<guid>`).
        *   The DLL's `IPCThread` reads commands, uses `HandleIPCCommand` to parse and queue a `Request` struct.
        *   The hooked `hkEndScene` function dequeues `Request` structs.
        *   `ProcessCommand` executes the request and queues a response string (e.g., `LUA_RESULT:value`, `CAST_RESULT:<id>,<success_flag>`).
        *   The `IPCThread` polls the response queue and sends the response string back to Python.
    *   **Threading Model:**
        *   **IPC Thread:** Dedicated thread for handling pipe connections, reading requests, and sending responses.
        *   **Hook Thread (`hkEndScene`):** Runs in the game's main rendering thread. Dequeues and processes commands via `ProcessCommand`, ensuring game-related functions (Lua execution, internal calls) happen in the correct context.
    *   **Game Interaction:**
        *   Executes Lua code via `lua_pcall`.
        *   Calls internal game C functions directly (`CastLocalPlayerSpell`, `findObjectByGuidAndFlags`, `isUnitVectorDifferenceWithinHemisphere`).
        *   Reads game memory for specific static data (Target GUID, Combo Points).
    *   **Build System (`CMakeLists.txt`):** Uses CMake to manage the C++ build process.

## Current Features

*   **Process Attachment & Memory Reading:** Connects to `Wow.exe`.
*   **Object Management:** Iterates object list, identifies player/target, caches objects, reads known spell IDs.
*   **Game State Monitoring:** GUI displays real-time player/target/nearby unit info (HP, Power, Pos, Status, Dist).
*   **Object List Filtering:** GUI filter for displayed object types (Players, Units).
*   **Named Pipe IPC:** Robust, persistent communication between Python and DLL.
*   **DLL Command Handling:**
    *   `ping`: Simple check.
    *   `EXEC_LUA:<code>`: Executes Lua code, returns results.
    *   `GET_TIME_MS`: Gets game time via Lua.
    *   `GET_CD:<id>`: Gets spell cooldown via Lua.
    *   `IS_IN_RANGE:<id>,<unit>`: Checks spell range via Lua.
    *   `GET_SPELL_INFO:<id>`: Gets spell details via Lua.
    *   `CAST_SPELL:<id>,<guid>`: Casts spell using internal C function.
    *   `GET_TARGET_GUID`: Gets target GUID via static memory read.
    *   `GET_COMBO_POINTS`: Gets combo points via static memory read.
    *   `IS_BEHIND_TARGET:<guid>`: Checks positional using internal C functions.
*   **Rule-Based Rotation Engine:**
    *   GUI editor (`Rotation Editor` tab) to define prioritized rules.
    *   Available Actions: `Spell`, `Macro` (via Lua), `Lua`.
    *   Available Targets: `target`, `player` (focus, pet, mouseover placeholders).
    *   Available Conditions:
        *   Simple: `None`, `Target Exists`, `Target Attackable` (basic), `Player Is Casting`, `Target Is Casting`, `Player Is Moving`, `Player Is Stealthed` (via Aura ID).
        *   Health/Resource: `Target HP % < X`, `Target HP % > X`, `Target HP % Between X-Y`, `Player HP % < X`, `Player HP % > X`, `Player Rage >= X`, `Player Energy >= X`, `Player Mana % < X`, `Player Mana % > X`, `Player Combo Points >= X` (via IPC).
        *   Distance: `Target Distance < X`, `Target Distance > X`.
        *   Spell/Aura: `Is Spell Ready` (via IPC), `Target Has Aura` (via Memory), `Target Missing Aura` (via Memory), `Player Has Aura` (via Memory), `Player Missing Aura` (via Memory).
        *   Position: `Player Is Behind Target` (via IPC).
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
*   **`sv-ttk`:** (`pip install sv-ttk`)
*   **(Optional but Recommended) `requirements.txt`:** (`pip install -r requirements.txt`)
*   **CMake:** Build system generator (Download from [cmake.org](https://cmake.org/download/)).
*   **C++ Compiler:** Supports C++17 (e.g., Visual Studio Community Edition 2019+ with "Desktop development with C++" workload).
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
    *(Or install `pymem` and `sv-ttk` manually)*

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
    *   **Inject the DLL:** Use your injector to load `build/Release/WowInjectDLL.dll` into `Wow.exe`. The DLL will establish the pipe server.
    *   **(Optional):** Run DebugView++ (or similar) as Administrator to see DLL logs via `OutputDebugStringA`.
    *   **Run the Python GUI:**
        ```bash
        python gui.py
        ```
    *   The GUI connects to WoW and the DLL pipe. Use the tabs to monitor, edit rules, load rules, and start/stop the rotation.
    *   Rules are saved/loaded to/from the `Rules/` directory (created automatically if needed).

## Development Notes & Known Issues

*   Offsets are specific to WoW 3.3.5a (12340).
*   **Major Refactor Complete:** The DLL has been refactored into multiple C++ files (`ipc_manager`, `command_processor`, `hook_manager`, etc.). Direct Python memory access for game functions/state has been replaced by Named Pipe IPC calls handled by the DLL.
*   **Aura/Stealth Checks Implemented:** Conditions `Player Has Aura`, `Player Missing Aura`, `Target Has Aura`, `Target Missing Aura`, and `Player Is Stealthed` are now implemented using direct memory reads in Python.
*   Rotation engine condition checking for Spell Readiness (resource cost) is still needed.
*   The `is_attackable` check logic may need refinement based on specific unit flags.
*   Macro execution (`RunMacroText`) is implemented via Lua.

## Deprecated Features (Replaced by DLL/IPC)

*   Direct Python shellcode injection.
*   Direct Python memory reads/writes for calling game functions or getting state like cooldowns, time, range (replaced by DLL IPC commands).

## Next Steps (Potential):

1.  Implement resource checks (Mana/Energy/Rage) to `Is Spell Ready` condition.
2.  Add more game interaction functions to the DLL (TargetUnit, Interact, etc.).
3.  Implement reliable GCD tracking (e.g., via Lua `GetSpellCooldown`).
4.  Refine `is_attackable` logic.

### Rotation Editor Tab

The Rotation Editor allows you to define sequences of actions (casting spells, running macros via Lua, running Lua) based on specific conditions. Rules are evaluated top-down, and the first rule whose conditions are met will have its action executed.

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

The Lua Runner tab allows you to execute arbitrary Lua code directly from the GUI via the DLL. This is useful for testing Lua scripts or running custom Lua code without needing to create a rule.

*   **Lua Code Input:** Enter the Lua code you want to execute in the text area.
*   **Execute:** Click the 'Run Lua Code' button to send the code to the DLL for execution.
*   **Output:** The result(s) returned by the Lua execution (via the DLL) will be displayed in the output area. 