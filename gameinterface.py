import ctypes
from ctypes import wintypes # For pointer types like DWORD
import time
import pymem
import offsets
from memory import MemoryHandler
from object_manager import ObjectManager
from typing import Union, Any, List, Optional, Tuple
import struct # For packing/unpacking float/double

# Constants for remote thread shellcode generation
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40 # Allows execution, reading, and writing
MEM_RELEASE = 0x8000

# Kernel32 functions
kernel32 = ctypes.windll.kernel32
CreateRemoteThread = kernel32.CreateRemoteThread
VirtualAllocEx = kernel32.VirtualAllocEx
WriteProcessMemory = kernel32.WriteProcessMemory
ReadProcessMemory = kernel32.ReadProcessMemory
VirtualFreeEx = kernel32.VirtualFreeEx
WaitForSingleObject = kernel32.WaitForSingleObject
GetExitCodeThread = kernel32.GetExitCodeThread # Can still be useful for thread status checks
CloseHandle = kernel32.CloseHandle

class GameInterface:
    """Handles interaction with the WoW Lua engine and direct memory functions."""

    def __init__(self, mem_handler: MemoryHandler, om: ObjectManager):
        self.mem = mem_handler
        self.om = om
        # LUA_STATE offset holds the ADDRESS where the lua_State* pointer is stored
        self.lua_state_ptr_addr = offsets.LUA_STATE
        self.lua_state = 0 # The actual lua_State* value

        if not self.mem or not self.mem.is_attached():
            print("GameInterface Error: Memory Handler not attached.")
            return

        # Read the lua_State* pointer value from the static address
        self.lua_state = self.mem.read_uint(self.lua_state_ptr_addr)
        if not self.lua_state:
             print(f"GameInterface Error: Could not read Lua State pointer value from address {hex(self.lua_state_ptr_addr)}. Lua C API calls will fail.")
        else:
            print(f"Lua State Pointer Value Found: {hex(self.lua_state)}")

    def is_ready(self) -> bool:
        """Check if the Game Interface can interact (Memory attached and Lua State pointer read)."""
        # We only need memory attached now, as lua_state isn't used by FrameScript_Execute
        # return bool(self.mem and self.mem.is_attached() and self.lua_state)
        return bool(self.mem and self.mem.is_attached())

    def _allocate_memory(self, size: int, permissions: int = PAGE_EXECUTE_READWRITE) -> Optional[int]:
        """Helper to allocate memory in the target process."""
        if not self.is_ready(): return None
        process_handle = self.mem.pm.process_handle
        address = VirtualAllocEx(process_handle, 0, size, MEM_COMMIT | MEM_RESERVE, permissions)
        if not address:
             print(f"Error: Failed to allocate {size} bytes. Error code: {kernel32.GetLastError()}")
             return None
        return int(address)

    def _free_memory(self, address: int):
        """Helper to free memory allocated with _allocate_memory."""
        if not self.is_ready() or not address: return
        process_handle = self.mem.pm.process_handle
        VirtualFreeEx(process_handle, address, 0, MEM_RELEASE)

    def _write_memory(self, address: int, data: bytes) -> bool:
         """Helper to write bytes to the target process."""
         if not self.is_ready() or not address: return False
         process_handle = self.mem.pm.process_handle
         bytes_written = ctypes.c_size_t(0)
         success = WriteProcessMemory(process_handle, address, data, len(data), ctypes.byref(bytes_written))
         if not success or bytes_written.value != len(data):
              print(f"Error: Failed to write {len(data)} bytes to {hex(address)}. Wrote {bytes_written.value}. Error code: {kernel32.GetLastError()}")
              return False
         return True

    def _read_memory(self, address: int, size: int) -> Optional[bytes]:
         """Helper to read bytes from the target process."""
         if not self.is_ready() or not address: return None
         process_handle = self.mem.pm.process_handle
         buffer = ctypes.create_string_buffer(size)
         bytes_read = ctypes.c_size_t(0)
         success = ReadProcessMemory(process_handle, address, buffer, size, ctypes.byref(bytes_read))
         if not success or bytes_read.value != size:
              print(f"Error: Failed to read {size} bytes from {hex(address)}. Read {bytes_read.value}. Error code: {kernel32.GetLastError()}")
              return None
         return buffer.raw

    def _execute_shellcode(self, shellcode: bytes, output_specs: Optional[List[Tuple[int, int]]] = None) -> Optional[Union[bytes, List[bytes]]]:
        """
        Executes shellcode in the target process using CreateRemoteThread.
        Can optionally read back data from specified memory locations after execution.

        Args:
            shellcode: The base machine code to execute (must end in RET 0xC3).
            output_specs: Optional list of tuples (address, size) specifying memory regions
                          to read back *after* the thread completes. Read data is returned
                          as a list of bytes objects corresponding to the specs.
                          If None or empty, returns b'' on successful execution attempt.

        Returns:
            - If output_specs is provided: A list of bytes objects containing the data read
              from the specified locations, or None on failure.
            - If output_specs is None/empty: Returns b'' on successful execution attempt,
              None on failure.
        """
        if not self.is_ready():
             print("Error: Cannot execute shellcode, GameInterface not ready.")
             return None

        shellcode_alloc = None
        thread_handle = None
        process_handle = self.mem.pm.process_handle
        final_shellcode = b""

        try:
            # 1. Construct final shellcode (Save Regs + Base + Restore Regs + RET)
            # No need to store results as result_size is always 0 for FrameScript_Execute
            # --- Save volatile registers --- (EAX, EBX, ECX, EDX, ESI, EDI)
            save_regs = b'\x50\x53\x51\x52\x56\x57' # PUSH EAX, PUSH EBX, PUSH ECX, PUSH EDX, PUSH ESI, PUSH EDI
            # --- Restore volatile registers --- (in reverse order)
            restore_regs = b'\x5F\x5E\x5A\x59\x5B\x58' # POP EDI, POP ESI, POP EDX, POP ECX, POP EBX, POP EAX

            # Ensure base shellcode ends with RET
            if not shellcode.endswith(b'\xC3'):
                print("CRITICAL WARNING: Base shellcode missing final RET (0xC3). Execution unreliable.")
                # Attempt to append it anyway, hoping stack is balanced
                base_with_ret = shellcode + b'\xC3'
            else:
                 base_with_ret = shellcode

            # --- New structure with register saving --- #
            base_without_ret = base_with_ret[:-1] # Remove the original RET
            final_shellcode = save_regs + base_without_ret + restore_regs + b'\xC3' # Add safe call wrapper

            # 2. Allocate memory for the final shellcode
            shellcode_alloc = self._allocate_memory(len(final_shellcode), PAGE_EXECUTE_READWRITE)
            if not shellcode_alloc: raise OSError("Failed to allocate shellcode memory")

            # 3. Write the final shellcode
            if not self._write_memory(shellcode_alloc, final_shellcode):
                 raise OSError("Failed to write final shellcode")

            # 4. Create and run the remote thread
            thread_handle = CreateRemoteThread(process_handle, None, 0, shellcode_alloc, None, 0, None)
            if not thread_handle:
                 raise OSError(f"Failed to create remote thread. Error: {kernel32.GetLastError()}")

            # 5. Wait for thread completion (with timeout)
            wait_result = WaitForSingleObject(thread_handle, 5000) # 5 second timeout
            if wait_result == 0x102: # WAIT_TIMEOUT
                 print("Warning: Remote thread timed out execution.")
                 # Attempt cleanup, but result reading might fail or be partial
            elif wait_result != 0x0: # WAIT_OBJECT_0
                 print(f"Warning: WaitForSingleObject returned code {wait_result}")
                 # Proceed with cleanup and result reading, but might be unexpected state

            # 6. Read output results if requested
            if output_specs:
                read_results = []
                for addr, size in output_specs:
                    data = self._read_memory(addr, size)
                    if data is None:
                        print(f"Warning: Failed to read output data ({size} bytes) from {hex(addr)} after shellcode execution.")
                        # Append None or raise error? Append None for now.
                        read_results.append(None)
                    else:
                        read_results.append(data)
                # Check if any read failed
                if any(r is None for r in read_results):
                    return None # Indicate overall failure if any part failed
                return read_results
            else:
                 # No output specs, just indicate success if thread didn't obviously fail early
                 return b''

        except pymem.exception.PymemError as e:
            print(f"GameInterface Shellcode PymemError: {e}")
            return None
        except OSError as e:
            print(f"GameInterface Shellcode OSError: {e}")
            return None
        except Exception as e:
            print(f"GameInterface Shellcode Unexpected Error: {type(e).__name__}: {e}")
            import traceback
            # traceback.print_exc() # Uncomment for full traceback during debugging
            return None
        finally:
            # Cleanup
            if thread_handle: CloseHandle(thread_handle)
            if shellcode_alloc: self._free_memory(shellcode_alloc)

    # --- Higher Level Lua Interaction ---

    def execute(self, lua_code: str, source_name: str = "PyWoWExec") -> bool:
        """
        Executes a string of Lua code using FrameScript_Execute (fire and forget).
        Best for actions like casting, using items, running macros.
        Returns True if execution was attempted, False on memory/allocation error.
        """
        if not self.is_ready():
            print("GameInterface Error: Not ready to execute (FrameScript).")
            return False
        if not lua_code:
            print("GameInterface Warning: Empty Lua code provided to execute().")
            return False

        alloc_lua_code = 0
        alloc_source_name = 0

        try:
            # 1. Prepare arguments in WoW's memory
            lua_code_bytes = lua_code.encode('utf-8') + b'\0'
            source_name_bytes = source_name.encode('utf-8') + b'\0'

            alloc_lua_code = self._allocate_memory(len(lua_code_bytes))
            if not alloc_lua_code: raise OSError("execute: Failed to allocate memory for lua_code")
            if not self._write_memory(alloc_lua_code, lua_code_bytes): raise OSError("execute: Failed to write lua_code")

            alloc_source_name = self._allocate_memory(len(source_name_bytes))
            if not alloc_source_name: raise OSError("execute: Failed to allocate memory for source_name")
            if not self._write_memory(alloc_source_name, source_name_bytes): raise OSError("execute: Failed to write source_name")

            # 2. Prepare the shellcode for FrameScript_Execute
            func_addr = offsets.LUA_FRAMESCRIPT_EXECUTE
            # __cdecl: FrameScript_Execute(char* luaCode, char* executionSource = "", int a3 = 0) -> void
            shellcode = bytes([
                0x6A, 0x00,                                # push 0x00 (arg3: a3)
                0x68, *alloc_source_name.to_bytes(4, 'little'), # push alloc_source_name (arg2)
                0x68, *alloc_lua_code.to_bytes(4, 'little'),    # push alloc_lua_code (arg1)
                0xB8, *func_addr.to_bytes(4, 'little'),         # mov eax, func_addr
                0xFF, 0xD0,                                     # call eax
                0x83, 0xC4, 0x0C,                              # add esp, 0xC (cleanup 3 args)
                0xC3                                           # ret
            ])

            # 3. Execute (no return value expected from function)
            result = self._execute_shellcode(shellcode, result_size=0)
            if result is None:
                 print(f"Error: execute('{lua_code[:50]}...') failed during shellcode execution.")
                 return False # Indicate failure if shellcode exec itself fails
            return True # Indicate successful execution attempt

        except pymem.exception.PymemError as e:
            print(f"GameInterface Error (Pymem) in execute: {e}")
            return False
        except OSError as e:
             print(f"GameInterface Error (OS) in execute: {e}")
             return False
        except Exception as e:
            print(f"GameInterface Error: Unexpected error during execute - {type(e).__name__}: {e}")
            return False
        finally:
            # Cleanup allocated strings
            if alloc_lua_code: self._free_memory(alloc_lua_code)
            if alloc_source_name: self._free_memory(alloc_source_name)

    # --- Direct Memory Function Calls ---

    def _get_system_time_millis(self) -> int:
        """Returns the current system time in milliseconds."""
        # time.time() returns seconds as float, convert to millis
        return int(time.time() * 1000)

    def get_spell_cooldown_direct(self, spell_id: int, unknownA2: int = 0) -> Optional[dict]:
        """
        Calls the game's internal GetSpellCooldown_Proxy function (__cdecl) via shellcode.

        Address: 0x00809000 (GetSpellCooldown_Proxy)
        Signature: BOOL __cdecl GetSpellCooldown_Proxy(int spellId, int unknownA2, int *durationOut, int *startTimeOut, int *enabledOut)

        Args:
            spell_id: The ID of the spell to check.
            unknownA2: Unknown second integer argument (default 0).

        Returns:
            A dictionary with 'duration', 'startTime', 'enabled', 'remaining'
            or None if the call fails or memory isn't ready.
            - duration (ms)
            - startTime (ms, represents internal expiry time relative to game timer)
            - enabled (bool, True if usable/off cooldown)
            - remaining (float, seconds - currently always 0.0)
        """
        if not self.is_ready():
            print("GameInterface Error: Not ready for direct function call (GetSpellCooldown).")
            return None

        # --- Revert to calling the original __cdecl proxy --- #
        func_addr = 0x00809000 # GetSpellCooldown_Proxy

        # --- Remove 'this' pointer logic --- #
        # this_ptr = 0
        # if self.om and self.om.local_player:
        #     this_ptr = self.om.local_player.base_address
        # if this_ptr == 0:
        #      print("Error: Cannot call GetSpellCooldown - Local Player object not found.", "ERROR")
        #      return None

        alloc_results = None
        sizeof_int = 4
        num_results = 3
        results_size = sizeof_int * num_results

        try:
            # 1. Allocate memory for the output parameters
            alloc_results = self._allocate_memory(results_size)
            if not alloc_results:
                 raise MemoryError("Failed to allocate memory for cooldown results")

            addr_duration = alloc_results + 0 * sizeof_int
            addr_start_time = alloc_results + 1 * sizeof_int
            addr_enabled = alloc_results + 2 * sizeof_int

            # 2. Construct the shellcode (__cdecl call convention)
            # Args pushed right-to-left: enabled*, startTime*, duration*, unknownA2, spellId
            shellcode = bytes([
                # push enabledOut*
                0x68, *addr_enabled.to_bytes(4, 'little'),
                # push startTimeOut*
                0x68, *addr_start_time.to_bytes(4, 'little'),
                # push durationOut*
                0x68, *addr_duration.to_bytes(4, 'little'),
                # push unknownA2
                0x68, *unknownA2.to_bytes(4, 'little', signed=True),
                # push spellId
                0x68, *spell_id.to_bytes(4, 'little', signed=True),
                # mov eax, func_addr
                0xB8, *func_addr.to_bytes(4, 'little'),
                # call eax
                0xFF, 0xD0,
                # add esp, 20 (cleanup 5 args * 4 bytes)
                0x83, 0xC4, 0x14,
                # ret
                0xC3
            ])

            # 3. Execute shellcode and specify outputs to read
            output_specs = [
                (addr_duration, sizeof_int),
                (addr_start_time, sizeof_int),
                (addr_enabled, sizeof_int)
            ]
            print(f"Executing Cooldown shellcode (__cdecl proxy {hex(func_addr)}) for SpellID {spell_id} expecting results at {hex(alloc_results)}", "DEBUG")
            results_bytes = self._execute_shellcode(shellcode, output_specs)

            # 4. Process results
            if results_bytes is None or len(results_bytes) != num_results or any(b is None for b in results_bytes):
                 print(f"Failed to execute or read results for GetSpellCooldown_Proxy call.", "ERROR")
                 return None

            # Unpack the byte results into integers
            duration_out = struct.unpack('<i', results_bytes[0])[0]
            start_time_out = struct.unpack('<i', results_bytes[1])[0]
            enabled_out = struct.unpack('<i', results_bytes[2])[0] # Read as int
            # --- ADDED DEBUG --- #
            print(f"Cooldown Raw Results: duration={duration_out}, start={start_time_out}, enabled_INT={enabled_out}", "DEBUG")

            # --- Reinstate Time Calculation (Expiry Hypothesis) --- #
            duration = duration_out
            start_time = start_time_out # Potentially the expiry time
            enabled = bool(enabled_out) # True if spell CD ready (ignoring GCD)

            remaining = 0.0
            if not enabled: # Only calculate if spell's own CD is active (enabled_out == 0)
                now_game_ms = self.get_game_time_millis_direct()
                if now_game_ms is not None:
                    expiry_time = start_time # Assume start_time is when CD ends
                    remaining_units = expiry_time - now_game_ms
                    # ASSUMPTION: Units are milliseconds. Scale might be wrong.
                    remaining = max(0.0, remaining_units / 1000.0)
                    # print(f"Time Calc (Expiry): now={now_game_ms}, expiry={expiry_time}, remaining_units={remaining_units}, remaining_s={remaining}", "DEBUG")
                else:
                    print("Error getting game time for cooldown remaining calculation.", "ERROR")
                    # Cannot calculate remaining, leave as 0.0

            cooldown_info = {
                "start_time": start_time, # Keep original value
                "duration": duration,     # Original duration
                "enabled": enabled,       # True if Spell CD ready (ignores GCD)
                "remaining": remaining    # Calculated seconds, or 0.0 if enabled or time error
            }
            # print(f"Cooldown Info (Expiry Calc Reinstated) for {spell_id}: {cooldown_info}", "DEBUG")
            return cooldown_info

        except (MemoryError, OSError, struct.error) as e:
            print(f"GameInterface Error (Cooldown): {type(e).__name__} - {e}")
            return None
        except Exception as e:
            print(f"GameInterface Error: Unexpected error during GetSpellCooldown - {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # Cleanup allocated memory for results
            if alloc_results: self._free_memory(alloc_results)

    def get_spell_range_direct(self, spell_id: int, context_ptr: int = 0, unknownA5: float = 0.0) -> Optional[dict]:
        """
        Calls the game's internal GetSpellRange function (__cdecl) via shellcode.

        Address: 0x00802C30 (GetSpellRange wrapper)
        Signature: void __cdecl GetSpellRange(_DWORD *a1, int spellId, float *minRangeOut, float *maxRangeOut, float unknownA5)

        Args:
            spell_id: The ID of the spell to check.
            context_ptr: Pointer argument a1 (purpose unknown, default 0). Maybe player object ptr?
            unknownA5: Unknown float argument (default 0.0).

        Returns:
            A dictionary with 'minRange', 'maxRange' or None if the call fails.
        """
        if not self.is_ready():
            print("GameInterface Error: Not ready for direct function call (GetSpellRange).")
            return None

        func_addr = 0x00802C30
        alloc_results = None
        sizeof_float = 4
        num_results = 2
        results_size = sizeof_float * num_results

        try:
            # 1. Allocate memory for float outputs
            alloc_results = self._allocate_memory(results_size)
            if not alloc_results:
                 raise MemoryError("Failed to allocate memory for range results")

            addr_min_range = alloc_results + 0 * sizeof_float
            addr_max_range = alloc_results + 1 * sizeof_float

            # 2. Pack float argument unknownA5 for pushing onto stack
            unknownA5_bytes = struct.pack('<f', unknownA5)

            # 3. Construct shellcode (__cdecl call convention)
            # Args pushed right-to-left: unknownA5(float), maxRange*, minRange*, spellId, context_ptr*
            shellcode = bytes([
                # push unknownA5 (as packed float bytes)
                # Note: Pushing immediate floats isn't direct, push the bytes
                0x68, *unknownA5_bytes,
                # push maxRangeOut*
                0x68, *addr_max_range.to_bytes(4, 'little'),
                # push minRangeOut*
                0x68, *addr_min_range.to_bytes(4, 'little'),
                # push spellId
                0x68, *spell_id.to_bytes(4, 'little', signed=True),
                # push context_ptr (treating as void*)
                0x68, *context_ptr.to_bytes(4, 'little'),
                # mov eax, func_addr
                0xB8, *func_addr.to_bytes(4, 'little'),
                # call eax
                0xFF, 0xD0,
                # add esp, 20 (cleanup 5 args * 4 bytes)
                0x83, 0xC4, 0x14,
                # ret
                0xC3
            ])

            # 4. Execute shellcode and specify outputs
            output_specs = [
                (addr_min_range, sizeof_float),
                (addr_max_range, sizeof_float)
            ]
            print(f"Executing Range shellcode for SpellID {spell_id} expecting results at {hex(alloc_results)}", "DEBUG")
            results_bytes = self._execute_shellcode(shellcode, output_specs)

            # 5. Process results
            if results_bytes is None or len(results_bytes) != num_results or any(b is None for b in results_bytes):
                 print(f"Failed to execute or read results for GetSpellRange call.", "ERROR")
                 return None

            # Unpack the byte results into floats
            min_range_out = struct.unpack('<f', results_bytes[0])[0]
            max_range_out = struct.unpack('<f', results_bytes[1])[0]
            print(f"Range Raw Results: min={min_range_out:.2f}, max={max_range_out:.2f}", "DEBUG")

            return {
                "minRange": min_range_out,
                "maxRange": max_range_out
            }

        except (MemoryError, OSError, struct.error) as e:
            print(f"GameInterface Error (Range): {type(e).__name__} - {e}")
            return None
        except Exception as e:
            print(f"GameInterface Error: Unexpected error during GetSpellRange - {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
             # Cleanup allocated memory for results
             if alloc_results: self._free_memory(alloc_results)

    def get_game_time_millis_direct(self) -> Optional[int]:
        """Reads the game's internal millisecond timer directly from memory.

        Static Address: 0xD4159C (presumed timer value)

        Returns:
            Current game time in milliseconds (int), or None on failure.
        """
        if not self.is_ready():
            return None

        # Revert: Read directly from the static address, not treating it as a pointer
        timer_addr = 0xD4159C
        try:
            game_time_ms = self.mem.read_uint(timer_addr)

            if game_time_ms is None or game_time_ms < 0: # Check for read error or potential negative value
                 print(f"Error reading game time from {hex(timer_addr)}. Read: {game_time_ms}","ERROR")
                 return None
            # print(f"Direct Game Time Read: {game_time_ms}", "DEBUG")
            return int(game_time_ms)
        except Exception as e:
            print(f"GameInterface Error: Exception reading game time from {hex(timer_addr)} - {type(e).__name__}: {e}")
            return None

# --- Example Usage ---
if __name__ == "__main__":
    print("Attempting to initialize Game Interface...")
    mem = MemoryHandler()
    if mem.is_attached():
        game = GameInterface(mem)
        if game.is_ready():
            print("Game Interface Initialized.")

            # --- Test Direct Function Calls ---
            test_spell_id = 1752 # Example: Holy Light Rank 1
            print(f"\n--- Testing Direct Cooldown Call (SpellID: {test_spell_id}) ---")
            cooldown_info = game.get_spell_cooldown_direct(test_spell_id)
            if cooldown_info:
                 print(f"Cooldown Info: Duration={cooldown_info['duration']}ms, Start={cooldown_info['startTime']}, Enabled={cooldown_info['enabled']}, Remaining={cooldown_info['remaining']}s")
            else:
                 print("Failed to get cooldown info.")

            print(f"\n--- Testing Direct Range Call (SpellID: {test_spell_id}) ---")
            # Try getting player object pointer if ObjectManager exists and is populated
            # context = 0
            # if game.mem.om and game.mem.om.local_player:
            #      context = game.mem.om.local_player.base_address # Example context
            # print(f"Using context pointer: {hex(context)}")
            range_info = game.get_spell_range_direct(test_spell_id) # Using default context=0 for now
            if range_info:
                 print(f"Range Info: Min={range_info['minRange']:.2f}yd, Max={range_info['maxRange']:.2f}yd")
            else:
                 print("Failed to get range info.")

            # --- Test FrameScript Execute ---
            print("\n--- Testing FrameScript Execute ---")
            print("Executing: print('Hello from Python FrameScript!')")
            success = game.execute("print('Hello from Python FrameScript!')")
            print(f"FrameScript Execute successful: {success}")

        else:
            print("Game Interface initialization failed (not ready).")
    else:
        print("Memory Handler failed to attach.")