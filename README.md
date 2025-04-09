# PyWoW Bot - WoW 3.3.5a Interaction Framework

A Python and C++ experimental framework for interacting with World of Warcraft (specifically 3.3.5a - client build 12340) to monitor game state, execute Lua, and potentially implement combat rotations or other automation.

**Disclaimer:** This project involves reading game memory, injecting DLLs, and potentially automating actions. Use entirely at your own risk. Modifying game clients or using automation tools typically violates the game's Terms of Service and could lead to account suspension. This tool is intended for educational and research purposes on private servers or sandboxed environments.

## Architecture

This project uses a two-part architecture:

1.  **Python Frontend & Core Logic:**
    *   **GUI (`gui.py`):** A `tkinter`-based graphical user interface to display game information (player/target status, nearby objects, logs) and control the rotation engine.
    *   **Memory Handler (`memory.py`):** Uses `pymem` to attach to the WoW process and read/write memory.
    *   **Object Manager (`object_manager.py`):** Reads the WoW object list, manages a cache of `WowObject` instances, and identifies the local player and target.
    *   **WoW Object (`wow_object.py`):** Represents game objects (players, units) and reads their properties from memory using offsets defined in `offsets.py`.
    *   **Game Interface (`gameinterface.py`):** Manages communication with the injected C++ DLL via **Named Pipes**. Sends commands (like `EXEC_LUA`, `GET_TIME`) and receives responses.
    *   **Combat Rotation (`combat_rotation.py`):** Engine capable of executing rotations based on loaded Lua scripts or prioritized rules defined in the GUI editor (`rules.py`).
    *   **Target Selector (`targetselector.py`):** Basic framework for target selection logic.
    *   **Offsets (`offsets.py`):** Contains memory addresses and structure offsets specific to WoW 3.3.5a (12340).

2.  **C++ Injected DLL (`WowInjectDLL/`):**
    *   **Core Logic (`dllmain.cpp`):** Written in C++, compiled into `WowInjectDLL.dll`.
    *   **Detours Hooking:** Uses Microsoft Detours (included in `vendor/Detours`) to hook the game's `EndScene` function (DirectX 9). This provides a reliable execution context within the main game thread.
    *   **Named Pipe Server:** Creates and manages a named pipe (`\\.\pipe\WowInjectPipe`) to receive commands from the Python process.
    *   **Command Handling:** Parses commands received over the pipe (e.g., `ping`, `EXEC_LUA:<code>`, `GET_TIME`).
    *   **Main Thread Execution:** Queues requests that require interaction with the game's main thread (like executing Lua) and processes them within the hooked `EndScene` function.
    *   **Lua Interaction:** Uses known function pointers (`offsets.py`) to execute Lua code (`FrameScript_Execute`) or interact with the Lua C API (e.g., `lua_loadbuffer`, `lua_pcall` for `GetTime`).
    *   **Build System (`CMakeLists.txt`):** Uses CMake to manage the C++ build process, including finding Detours and linking necessary libraries.

## Current Features

*   **Process Attachment & Memory Reading:** Connects to `Wow.exe` and reads memory addresses.
*   **Object Management:** Iterates the game's object list, identifies player/target, caches objects.
*   **Game State Monitoring:** GUI displays real-time information about the player, target, and nearby units (Health, Power, Position, Status).
*   **Named Pipe IPC:** Robust communication channel between the Python GUI and the injected C++ DLL.
*   **Lua Execution:** Send arbitrary Lua code strings from Python to be executed within the game's main thread via the DLL (`EXEC_LUA` command).
*   **Game Time Retrieval:** Get the current in-game time via the DLL (`GET_TIME` command).
*   **Rotation Engine:**
    *   Load and run simple Lua rotation scripts (`Scripts/` folder).
    *   Define and run prioritized, condition-based rotation rules via the GUI Editor tab.
*   **Logging:** GUI Log tab captures output from Python scripts. DLL uses `OutputDebugStringA` (viewable with DebugView).

## Dependencies

*   **Python 3.x**
*   **`pymem`:** Python library for memory access (`pip install pymem`). Listed in `requirements.txt`.
*   **CMake:** Build system generator (Download from [cmake.org](https://cmake.org/download/)). Required to build the C++ DLL.
*   **C++ Compiler:** A compiler that supports C++17 (e.g., Visual Studio Community Edition with "Desktop development with C++" workload, including the MSVC compiler and Windows SDK).
*   **Microsoft Detours:** Included in the `vendor/Detours` directory. No separate installation needed, but requires the C++ compiler to build the DLL which uses it.
*   **WoW Client:** Specifically version 3.3.5a (build 12340). Offsets are hardcoded for this version.
*   **DLL Injector:** A standard DLL injection tool (e.g., Process Hacker, Xenos Injector, etc.) to load `WowInjectDLL.dll` into the `Wow.exe` process.

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
    *   Use the Monitor tab to view game state, the Rotation Control tab to load/run scripts/rules, and the Rotation Editor to define rules.

## Development Notes & Known Issues

*   Offsets in `offsets.py` are critical and specific to WoW 3.3.5a (12340).
*   Error handling can be improved in both Python and C++ components.
*   The C++ DLL relies on Detours for hooking; ensure the build process correctly links it.
*   Reading certain dynamic values directly from memory can sometimes be inconsistent; the DLL aims to provide more reliable access via Lua or specific functions where possible.
*   Rotation logic is currently basic; complex conditions and actions may require more sophisticated Lua interaction or direct memory manipulation within the DLL.

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