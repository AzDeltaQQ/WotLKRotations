# PyWoW Bot - WoW 3.3.5a Interaction Framework

A Python and C++ experimental framework for interacting with World of Warcraft (specifically 3.3.5a - client build 12340) to monitor game state, execute Lua, and potentially implement combat rotations or other automation.

**Disclaimer:** This project involves reading game memory, injecting DLLs, and potentially automating actions. Use entirely at your own risk. Modifying game clients or using automation tools typically violates the game's Terms of Service and could lead to account suspension. This tool is intended for educational and research purposes on private servers or sandboxed environments.

## Architecture

This project uses a two-part architecture:

1.  **Python Frontend & Core Logic:**
    *   **GUI (`gui.py`):** A `tkinter`-based graphical user interface to display game information (player/target status, nearby objects, logs) and control the rotation engine.
    *   **Memory Handler (`memory.py`):** Uses `pymem` to attach to the WoW process and read/write memory (primarily for object manager and static data).
    *   **Object Manager (`object_manager.py`):** Reads the WoW object list, manages a cache of `WowObject` instances, and identifies the local player and target. Reads dynamic object data like health, power, position, status flags, and known spell IDs directly from memory.
    *   **WoW Object (`wow_object.py`):** Represents game objects (players, units) and reads their properties from memory using offsets defined in `offsets.py`.
    *   **Game Interface (`gameinterface.py`):** Manages communication with the injected C++ DLL via **Named Pipes**. Sends commands (like `EXEC_LUA`, `GET_TIME_MS`, `GET_CD`, `IS_IN_RANGE`, `GET_SPELL_INFO`, `CAST_SPELL`) and receives responses. Implements logic to handle asynchronous responses and ensure correct command-response pairing.
    *   **Combat Rotation (`combat_rotation.py`):** Engine capable of executing rotations based on loaded Lua scripts or prioritized rules defined in the GUI editor (`rules.py`).
    *   **Target Selector (`targetselector.py`):** Basic framework for target selection logic.
    *   **Offsets (`offsets.py`):** Contains memory addresses and structure offsets specific to WoW 3.3.5a (12340).
    *   **Rules (`rules.py`):** Defines the structure for rotation rules used by the editor.

2.  **C++ Injected DLL (`WowInjectDLL/`):**
    *   **Core Logic (`dllmain.cpp`):** Written in C++, compiled into `WowInjectDLL.dll`.
    *   **Detours Hooking:** Uses Microsoft Detours (included in `vendor/Detours`) to hook the game's `EndScene` function (DirectX 9). This provides a reliable execution context within the main game thread.
    *   **Persistent Named Pipe Server:** Creates and manages a named pipe (`\\.\pipe\WowInjectPipe`) that **persists** after client disconnects, allowing the Python GUI to reconnect without reinjecting the DLL.
    *   **Command Handling:** Parses commands received over the pipe (e.g., `ping`, `EXEC_LUA:<code>`, `GET_TIME_MS`, `GET_CD:<id>`, `IS_IN_RANGE:<id>,<unit>`, `GET_SPELL_INFO:<id>`, `CAST_SPELL:<id>[,guid]`).
    *   **Main Thread Execution:** Queues requests that require interaction with the game's main thread (like executing Lua or calling game functions) and processes them within the hooked `EndScene` function.
    *   **Lua Interaction:** Uses known function pointers (`offsets.py`/hardcoded in DLL) to execute Lua code or interact with the Lua C API (e.g., `GetTime()`, `GetSpellCooldown()`, `IsSpellInRange()`, `GetSpellInfo()`).
    *   **Internal Function Calls:** Uses known function pointers to directly call internal game C functions (e.g., `CastLocalPlayerSpell`).
    *   **Build System (`CMakeLists.txt`):** Uses CMake to manage the C++ build process, including finding Detours and linking necessary libraries.

## Current Features

*   **Process Attachment & Memory Reading:** Connects to `Wow.exe` and reads memory addresses.
*   **Object Management:** Iterates the game's object list, identifies player/target, caches objects, reads known spell IDs. Specifically handles name reading for Players, Units, and GameObjects.
*   **Game State Monitoring:** GUI displays real-time information about the player, target, and nearby units/objects (Health, Power, Position, Status) within 100 yards.
*   **Object List Filtering:** GUI filter button allows selecting which object types (Players, Units, GameObjects, DynamicObjects, Corpses) are displayed. Items and Containers are now excluded.
*   **Persistent Named Pipe IPC:** Robust, asynchronous communication channel between the Python GUI and the injected C++ DLL, allowing GUI reconnection without reinjecting the DLL. Handles out-of-order responses.
*   **Lua Execution:** Send arbitrary Lua code strings from Python to be executed within the game's main thread via the DLL (`EXEC_LUA` command).
*   **Game Time Retrieval:** Get the current in-game time (in milliseconds) via the DLL (`GET_TIME_MS` command).
*   **Spell Cooldown Check:** Get spell cooldown status (start, duration, calculated readiness, remaining time) via the DLL (`GET_CD` command) using the game's `GetSpellCooldown` function.
*   **Spell Range Check:** Check if a spell is in range of a specific unit (e.g., "target") via the DLL (`IS_IN_RANGE` command) using the game's `IsSpellInRange` function (via `GetSpellInfo` lookup).
*   **Spell Info Lookup:** Retrieve spell details (Name, Rank, Cast Time, Cost, Power Type, Min Range, Icon) via the DLL (`GET_SPELL_INFO` command) using the game's `GetSpellInfo` function.
*   **Spell Casting:** Cast spells using the internal C function `CastLocalPlayerSpell` via the DLL (`CAST_SPELL` command), optionally targeting a specific GUID.
*   **Rotation Engine:**
    *   Load and run simple Lua rotation scripts (`Scripts/` folder).
    *   Define, save, load, and run prioritized, condition-based rotation rules via the GUI Editor tab.
*   **GUI Controls:** Test buttons for all major DLL interaction functions (GetTime, GetCooldown, IsInRange, CastSpell).
*   **Logging:** GUI Log tab captures output from Python scripts. DLL uses `OutputDebugStringA` (viewable with DebugView).
*   **Spellbook Scanner:** GUI utility to read and display known spell IDs from memory.
*   **Combo Points Retrieval:** Retrieves current combo points via direct memory read.

## Dependencies

*   **Python 3.x**
*   **`pymem`:** Python library for memory access (`pip install pymem`). Listed in `requirements.txt`.
*   **CMake:** Build system generator (Download from [cmake.org](https://cmake.org/download/)). Required to build the C++ DLL.
*   **C++ Compiler:** A compiler that supports C++17 (e.g., Visual Studio Community Edition with "Desktop development with C++" workload, including the MSVC compiler and Windows SDK).
*   **Microsoft Detours:** Included in the `vendor/Detours` directory. No separate installation needed, but requires the C++ compiler to build the DLL which uses it.
*   **WoW Client:** Specifically version 3.3.5a (build 12340). Offsets are hardcoded for this version.
*   **DLL Injector:** A standard DLL injection tool (e.g., Process Hacker, Xenos Injector, Extreme Injector, Cheat Engine, etc.) to load `WowInjectDLL.dll` into the `Wow.exe` process.

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
    *   Ensure CMake and a C++ Compiler (like Visual Studio Build Tools or Community Edition with C++ workload) are installed and accessible in your system's PATH.
    *   Open a command prompt or terminal in the project's root directory.
    *   **Configure CMake:**
        ```bash
        # Create a build directory and configure for Release build (adjust generator if needed)
        cmake -S WowInjectDLL -B build -A Win32
        # For Visual Studio: cmake -S WowInjectDLL -B build -G "Visual Studio 17 2022" -A Win32
        # Use Win32 architecture for the 32-bit WoW client.
        ```
    *   **Build the DLL:**
        ```bash
        # Build using CMake for the Release configuration
        cmake --build build --config Release
        ```
    *   The compiled DLL (`WowInjectDLL.dll`) will be located in the `build/Release/` directory.

4.  **Configure (Optional):**
    *   Create a `config.ini` file in the root directory (or modify the existing one if included, noting it's ignored by git by default).
    *   Set the `wowpath` under `[Settings]` if needed by any functionality (currently not critical).
    *   The GUI window size and position are saved automatically in `config.ini`.

5.  **Run:**
    *   Start World of Warcraft 3.3.5a (12340).
    *   **Inject the DLL:** Use your preferred DLL injector to inject the compiled `build/Release/WowInjectDLL.dll` into the running `Wow.exe` process.
    *   **(Optional but Recommended):** Run DebugView (Sysinternals) as Administrator to see log messages from the injected DLL.
    *   **Run the Python GUI:**
        ```bash
        python gui.py
        ```
    *   The GUI should launch. It will attempt to connect to the WoW process and the named pipe created by the DLL. Check the Log tab for status messages.
    *   Use the Monitor tab to view game state, the Rotation Control tab to load/run scripts/rules and test DLL functions, and the Rotation Editor to define rules.

## Development Notes & Known Issues

*   Offsets in `offsets.py` and hardcoded in the DLL are critical and specific to WoW 3.3.5a (12340).
*   The core logic file `WowInjectDLL/dllmain.cpp` has been recently refactored for better organization and readability, but the underlying functionality remains the same.
*   Fixed an issue where spell names/ranks containing commas were not parsed correctly by changing the `SPELL_INFO` IPC delimiter to `|`.
*   Error handling can be improved in both Python and C++ components.
*   The C++ DLL relies on Detours for hooking; ensure the build process correctly links it.
*   The DLL now handles interaction with core Lua/C functions like `GetSpellCooldown`, `IsSpellInRange`, `GetTime`, `GetSpellInfo`, and `CastLocalPlayerSpell` providing more reliable data and actions than direct memory manipulation for these cases.
*   Rotation logic is currently based on simple conditions; complex scenarios might need more Lua or DLL enhancements.
*   Item and Container object types are no longer processed or displayed.

## Deprecated Features (Replaced by DLL/IPC)

*   Direct Python shellcode injection for Lua execution.
*   Direct memory reads from Python for spell cooldowns, range, game time (less reliable than calling game functions).

## Next Steps (Potential):

1.  Implement more sophisticated rotation conditions (e.g., Aura checks, target casting checks) via Lua/DLL.
2.  Add more game interaction functions to the DLL interface (e.g., TargetUnit, GetAuraInfo, Interact).
3.  Improve stability and error reporting between Python and C++.
4.  Refine target selection logic.
5.  Add configuration options for offsets, settings, etc.

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