# PyWoW Bot - WoW 3.3.5a Interaction Framework

A Python and C++ experimental framework for interacting with World of Warcraft (specifically 3.3.5a - client build 12340) to monitor game state, execute Lua, and implement combat rotations using a rule-based engine.

**Disclaimer:** This project involves reading game memory, injecting DLLs, and potentially automating actions. Use entirely at your own risk. Modifying game clients or using automation tools typically violates the game's Terms of Service and could lead to account suspension. This tool is intended for educational and research purposes on private servers or sandboxed environments.

## Architecture

This project uses a two-part architecture:

1.  **Python Frontend & Core Logic:**
    *   **GUI (`gui.py`):** A `tkinter`-based graphical user interface (using the `sv-ttk` theme) to display game information (player/target status, nearby objects, logs), control the rotation engine, edit rotation rules, and execute Lua commands.
    *   **Memory Handler (`memory.py`):** Uses `pymem` to attach to the WoW process and read/write memory.
    *   **Object Manager (`object_manager.py`):** Reads the WoW object list, manages a cache of `WowObject` instances, and identifies the local player and target. Reads dynamic object data like health, power, position, status flags, and known spell IDs directly from memory.
    *   **WoW Object (`wow_object.py`):** Represents game objects (players, units) and reads their properties from memory using offsets defined in `offsets.py`.
    *   **Game Interface (`gameinterface.py`):** Manages communication with the injected C++ DLL via **Named Pipes**. Sends commands (like `EXEC_LUA`, `GET_TIME_MS`, `GET_CD`, `IS_IN_RANGE`, `GET_SPELL_INFO`, `CAST_SPELL`, `GET_TARGET_GUID`, `GET_COMBO_POINTS`) and receives responses. Handles asynchronous communication.
    *   **Combat Rotation (`combat_rotation.py`):** Engine capable of executing rotations based on prioritized rules defined in the GUI editor. Includes a `ConditionChecker` for evaluating rule conditions (currently basic checks, some placeholders require Lua).
    *   **Target Selector (`targetselector.py`):** Basic framework for target selection logic.
    *   **Offsets (`offsets.py`):** Contains memory addresses and structure offsets specific to WoW 3.3.5a (12340).
    *   **Rules (`rules.py`):** Defines the structure for rotation rules used by the editor. Rules are saved/loaded as `.json` files in the `Rules/` directory.

2.  **C++ Injected DLL (`WowInjectDLL/`):**
    *   **Core Logic (`dllmain.cpp`):** Written in C++, compiled into `WowInjectDLL.dll`.
    *   **Detours Hooking:** Uses Microsoft Detours (included in `vendor/Detours`) to hook the game's `EndScene` function (DirectX 9).
    *   **Persistent Named Pipe Server:** Creates and manages a named pipe (`\\.\pipe\WowInjectPipe`) allowing the Python GUI to reconnect without reinjecting the DLL.
    *   **Command Handling:** Parses commands received over the pipe (e.g., `ping`, `EXEC_LUA:<code>`, `GET_TIME_MS`, `GET_CD:<id>`, `IS_IN_RANGE:<id>,<unit>`, `GET_SPELL_INFO:<id>`, `CAST_SPELL:<id>[,guid]`, `GET_TARGET_GUID`, `GET_COMBO_POINTS`).
    *   **Main Thread Execution:** Queues requests and processes them within the hooked `EndScene` function.
    *   **Lua Interaction:** Uses known function pointers to execute Lua code or interact with the Lua C API (e.g., `GetTime()`, `GetSpellCooldown()`, `IsSpellInRange()`, `GetSpellInfo()`).
    *   **Internal Function Calls:** Uses known function pointers to directly call game C functions (e.g., `CastLocalPlayerSpell`).
    *   **Memory Reads:** Directly reads specific game data like Target GUID and Combo Points upon request from Python via pipe commands.
    *   **Build System (`CMakeLists.txt`):** Uses CMake to manage the C++ build process.

## Current Features

*   **Process Attachment & Memory Reading:** Connects to `Wow.exe`.
*   **Object Management:** Iterates object list, identifies player/target, caches objects, reads known spell IDs.
*   **Game State Monitoring:** GUI displays real-time player/target/nearby unit info (HP, Power, Pos, Status, Dist).
*   **Object List Filtering:** GUI filter for displayed object types (Players, Units).
*   **Persistent Named Pipe IPC:** Robust communication between Python and DLL.
*   **Lua Execution:** Execute arbitrary Lua code via DLL (`Lua Runner` tab and rule actions).
*   **Game State via DLL:** Get time, spell cooldowns, spell range, spell info, target GUID via pipe commands.
*   **Spell Casting:** Cast spells via DLL (`CAST_SPELL` command or `CastSpellByID` Lua call).
*   **Combo Points Retrieval:** Get combo points via DLL (`GET_COMBO_POINTS` command or direct memory read test button).
*   **Rule-Based Rotation Engine:**
    *   GUI editor (`Rotation Editor` tab) to define prioritized rules.
    *   Available Actions: `Spell`, `Macro` (not implemented), `Lua`.
    *   Available Targets: `target`, `player`, `focus`, `pet`, `mouseover`.
    *   Available Conditions: `None`, `Target Exists`, `Target Attackable`, `Player Is Casting`, `Target Is Casting`, `Player Is Moving`, `Player Is Stealthed`, `Is Spell Ready` (Placeholder), `Target HP % < X`, `Player HP % < X`, `Player Rage >= X`, `Player Energy >= X`, `Player Mana % < X`, `Player Combo Points >= X`, `Target Distance < X`, `Target Has Aura` (Placeholder), `Player Has Aura` (Placeholder).
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
*   Recent Fixes: Addressed issues with target checking via pipe vs direct memory, button state updates after loading rules, `AttributeError`s in GUI/rotation logic, and removed false GCD lockout after `CastSpellByID` calls.
*   Rotation engine condition checking is still basic; Aura/SpellReady/etc. checks are placeholders.
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