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
PAGE_READWRITE = 0x04
PAGE_EXECUTE_READ = 0x20 # Added for VirtualProtectEx

# Timeout for remote thread execution (milliseconds)
REMOTE_THREAD_TIMEOUT_MS = 5000

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

    def _allocate_memory(self, size: int, protection: int = PAGE_EXECUTE_READWRITE) -> Optional[int]:
        """Allocate memory in the target process with specified protection."""
        if not self.is_ready(): return None
        process_handle = self.mem.pm.process_handle
        try:
            addr = VirtualAllocEx(process_handle, 0, size, MEM_COMMIT | MEM_RESERVE, protection)
            # print(f"Allocated {size} bytes at {hex(addr)} with protection {hex(protection)}", "DEBUG")
            return addr if addr else None
        except Exception as e:
            print(f"Memory allocation failed: {e}", "ERROR")
            return None

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

    def _execute_shellcode(self, shellcode: bytes, output_specs: Optional[List[Tuple[int, int]]] = None) -> Optional[List[bytes]]:
        """Executes shellcode in the target process via CreateRemoteThread.
           Uses Allocate(RW) -> Write -> Protect(RX) -> Execute pattern for DEP.
        """
        shellcode_alloc = None
        thread_handle = None
        process_handle = self.mem.pm.process_handle # Get handle

        try:
            # 1. Prepare final_shellcode (ensure it has a RET C3 at the end)
            if not shellcode.endswith(b'\xc3'):
                 print("CRITICAL WARNING: Base shellcode missing final RET (0xC3). Appending.")
                 shellcode += b'\xc3'

            # Add register saving wrapper
            save_regs = b'\x60' # pushad
            restore_regs = b'\x61' # popad
            base_without_ret = shellcode[:-1] # Remove the original RET
            final_shellcode = save_regs + base_without_ret + restore_regs + b'\xc3' # Wrapper adds its own RET
            shellcode_size = len(final_shellcode)

            # 2. Allocate memory with WRITE permissions first
            shellcode_alloc = self._allocate_memory(shellcode_size, protection=PAGE_READWRITE)
            if not shellcode_alloc:
                raise MemoryError("Failed to allocate memory for shellcode (RW)")

            # 3. Write the shellcode to the allocated memory
            if not self._write_memory(shellcode_alloc, final_shellcode):
                 self._free_memory(shellcode_alloc) # Cleanup on failure
                 raise MemoryError("Failed to write shellcode to process memory")

            # 4. Change memory protection to EXECUTE + READ
            old_protect = ctypes.c_ulong(0)
            success = kernel32.VirtualProtectEx(
                process_handle,
                shellcode_alloc,
                shellcode_size,
                PAGE_EXECUTE_READ, # New protection
                ctypes.byref(old_protect)
            )
            if not success:
                error_code = kernel32.GetLastError()
                self._free_memory(shellcode_alloc) # Cleanup on failure
                raise OSError(f"Failed to change memory protection to EXECUTE. Error: {error_code}")

            # 5. Create and run the remote thread
            thread_handle = kernel32.CreateRemoteThread(process_handle, None, 0, shellcode_alloc, None, 0, None)
            if not thread_handle:
                error_code = kernel32.GetLastError()
                self._free_memory(shellcode_alloc) # Cleanup on failure
                raise OSError(f"Failed to create remote thread. Error: {error_code}")

            # 6. Wait for the thread to finish
            wait_result = kernel32.WaitForSingleObject(thread_handle, REMOTE_THREAD_TIMEOUT_MS)
            if wait_result != 0x0: # 0x0 means WAIT_OBJECT_0 (signaled)
                timeout_reason = "timed out" if wait_result == 0x102 else f"failed (code {wait_result})"
                print(f"Warning: Remote thread {timeout_reason} execution.")
                # Continue to try and read results, but be aware they might be invalid

            # 7. Read output buffers if specified
            output_data_list = []
            if output_specs:
                for addr, size in output_specs:
                    output_data = self._read_memory(addr, size)
                    if output_data is None:
                        # Don't raise error here, allow partial results / status check
                        print(f"Warning: Failed to read output buffer at {hex(addr)} size {size}")
                        output_data_list.append(None) # Append None to indicate read failure for this buffer
                    else:
                        output_data_list.append(output_data)
                # Return list possibly containing None values
                return output_data_list
            else:
                return [] # Return empty list if no output expected and thread ran

        except (MemoryError, OSError) as e:
             print(f"GameInterface Shellcode {type(e).__name__}: {e}", "ERROR")
             # Ensure cleanup even if thread creation failed before finally block
             if shellcode_alloc and not thread_handle: # If alloc succeeded but thread failed
                 self._free_memory(shellcode_alloc)
             shellcode_alloc = None # Prevent finally block from freeing again
             return None # Indicate failure clearly
        except Exception as e:
             print(f"GameInterface Shellcode Unexpected Error: {type(e).__name__}: {e}", "ERROR")
             import traceback
             traceback.print_exc()
              # Ensure cleanup even if thread creation failed before finally block
             if shellcode_alloc and not thread_handle:
                 self._free_memory(shellcode_alloc)
             shellcode_alloc = None
             return None
        finally:
            # 8. Cleanup: Close thread handle and free shellcode memory
            if thread_handle:
                kernel32.CloseHandle(thread_handle)
            if shellcode_alloc:
                # Optional: Change protection back before freeing?
                # VirtualProtectEx(process_handle, shellcode_alloc, shellcode_size, PAGE_READWRITE, byref(old_protect))
                self._free_memory(shellcode_alloc)

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

    def _get_spell_cooldown_direct_legacy(self, spell_id: int, unknownA2: int = 0) -> Optional[dict]:
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
            # print(f"Cooldown Raw Results: duration={duration_out}, start={start_time_out}, enabled_INT={enabled_out}", "DEBUG")

            # --- REMOVE Time Calculation --- #
            duration = duration_out
            start_time = start_time_out
            enabled = bool(enabled_out) # True if spell CD ready (ignores GCD)

            # remaining = 0.0 # No longer calculated here

            cooldown_info = {
                "start_time": start_time, # Raw value from function
                "duration": duration,     # Raw value from function
                "enabled": enabled,       # True if Spell CD ready (ignores GCD)
                # "remaining": remaining    # Removed
            }
            # print(f"Cooldown Info (Raw) for {spell_id}: {cooldown_info}", "DEBUG")
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

    def _get_spell_range_direct_legacy(self, spell_id: int, context_ptr: int = 0, unknownA5: float = 0.0) -> Optional[dict]:
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

    def is_gcd_active(self) -> Optional[bool]:
        """
        Checks if the Global Cooldown (GCD) is currently active by mimicking
        the game's internal logic: iterating a linked list of active cooldowns
        for the GCD category and checking expiry times.

        Based on RE findings:
        - Cooldown nodes store startTime and gcdDuration.
        - Check is: startTime + gcdDuration > currentTime.
        - Assumes GCD Category ID is 0.
        - Uses game timer read from 0xD4159C via get_game_time_millis_direct().

        Returns:
            True if GCD is detected as active.
            False if GCD is not active.
            None if there was an error reading memory or getting game time.
        """
        if not self.is_ready():
            # print("GameInterface Error: Not ready for GCD check.")
            return None

        LIST_HEAD_BASE = 0x00D3F5AC  # Base address of the list head array/structure
        GCD_CATEGORY_ID = 1       # TRY CATEGORY 1 INSTEAD OF 0
        PTR_SIZE = 4 # Assuming 32-bit pointers

        OFFSET_NEXT_NODE = 0x04
        OFFSET_START_TIME = 0x10 # Using the first start time offset
        OFFSET_GCD_DURATION = 0x20
        OFFSET_FLAGS = 0x24 # Offset of the flags byte within the node

        try:
            # 1. Get current time
            current_time = kernel32.GetTickCount()
            # print(f"GCD_DEBUG: Current Time (GetTickCount) = {current_time}", "DEBUG") # Re-enable print

            # 2. Calculate address of the GCD category list head
            LIST_ENTRY_SIZE = 8
            gcd_list_head_addr = LIST_HEAD_BASE + GCD_CATEGORY_ID * LIST_ENTRY_SIZE
            # print(f"GCD_DEBUG: Reading list head for Category {GCD_CATEGORY_ID} from {hex(gcd_list_head_addr)} (using {LIST_ENTRY_SIZE}-byte stride)", "DEBUG") # Re-enable print

            # 3. Read the pointer to the first node
            current_node_ptr = self.mem.read_uint(gcd_list_head_addr)
            if current_node_ptr is None:
                # print(f"GCD_DEBUG: Error reading list head pointer from {hex(gcd_list_head_addr)}.", "ERROR") # Re-enable print
                return None
            # print(f"GCD_DEBUG: First node pointer = {hex(current_node_ptr)}", "DEBUG") # Re-enable print

            # 4. Iterate the linked list
            MAX_ITERATIONS = 50
            iterations = 0
            while current_node_ptr != 0 and current_node_ptr is not None and iterations < MAX_ITERATIONS:
                iterations += 1
                # print(f"GCD_DEBUG: Iter {iterations}, Node Addr = {hex(current_node_ptr)}", "DEBUG") # Re-enable print

                # Read relevant data
                start_time = self.mem.read_uint(current_node_ptr + OFFSET_START_TIME)
                gcd_duration = self.mem.read_uint(current_node_ptr + OFFSET_GCD_DURATION)
                flags = self.mem.read_uchar(current_node_ptr + OFFSET_FLAGS)

                if start_time is None or gcd_duration is None or flags is None: # Check all reads
                    # print(f"GCD_DEBUG: Error reading time/duration/flags from node {hex(current_node_ptr)}.", "ERROR")
                    return None # Indicate error

                # print(f"GCD_DEBUG:   Node({hex(current_node_ptr)}): start={start_time}, duration={gcd_duration}, flags={flags}", "DEBUG") # Re-enable print

                # --- Revert to Time Comparison Check with Duration Filter --- #
                # Only consider nodes with a duration likely corresponding to the GCD
                if 1000 <= gcd_duration <= 1600:
                    expiry_time = start_time + gcd_duration
                    # print(f"GCD_DEBUG:   Checking (duration match): expiry={expiry_time} > now={current_time} ?", "DEBUG") # Re-enable print
                    if expiry_time > current_time:
                        # We don't need to check flags if time comparison works reliably
                        # print(f"GCD_DEBUG:   >>> ACTIVE! (Node {hex(current_node_ptr)}, Duration: {gcd_duration}ms, Flags: {flags})", "DEBUG")
                        return True # GCD is active because expiry is in the future
                    # else:
                    #     print(f"GCD_DEBUG:   Skipping check (duration match, but expiry time passed)", "DEBUG")
                # else:
                    # Print why we skipped this node
                    # if gcd_duration <= 0:
                    #     print(f"GCD_DEBUG:   Skipping check (duration={gcd_duration})", "DEBUG") # Re-enable print
                    # else:
                    #     print(f"GCD_DEBUG:   Skipping check (duration {gcd_duration}ms outside GCD range [1000, 1600])", "DEBUG") # Re-enable print

                # Move to the next node
                next_node_ptr = self.mem.read_uint(current_node_ptr + OFFSET_NEXT_NODE)
                if next_node_ptr is None:
                    # print(f"GCD_DEBUG: Error reading next node pointer from {hex(current_node_ptr + OFFSET_NEXT_NODE)}.", "ERROR")
                    return None # Indicate error
                # print(f"GCD_DEBUG:   Next node pointer = {hex(next_node_ptr)}", "DEBUG")
                current_node_ptr = next_node_ptr

            if iterations >= MAX_ITERATIONS:
                 # print("GCD_DEBUG: Hit max iterations, potential list issue.", "WARNING")
                 pass

            # If loop finishes without finding an active GCD
            # print("GCD_DEBUG: Iteration finished, GCD NOT ACTIVE", "DEBUG")
            return False

        except Exception as e:
            print(f"GameInterface Error: Exception during GCD check - {type(e).__name__}: {e}")
            # import traceback
            # traceback.print_exc()
            return None

    # --- Lua C API Interaction (Advanced) ---

    def call_lua_function(self, lua_func_name: str, args: list, return_types: list) -> Optional[list]:
        """
        Calls a global Lua function using lua_pcall via shellcode injection.
        Uses the confirmed LUA_GETGLOBAL sequence start address for 3.3.5a.
        Simplified shellcode error handling.

        Args:
            lua_func_name: The name of the global Lua function to call (e.g., "GetSpellInfo").
            args: A list of Python values to pass as arguments to the Lua function.
                  Supported types: str. (int, bool, float disabled due to unconfirmed offsets)
            return_types: A list of strings indicating the expected Lua types of the
                          return values ('string', 'number', 'integer'). ('boolean' disabled)

        Returns:
            A list containing the Python representations of the return values read
            from the Lua stack, or None if the call fails (including internal pcall errors).
        """
        if not self.lua_state or not self.is_ready():
            print("GameInterface Error: Lua state invalid or not ready for call_lua_function.", "ERROR")
            return None

        # --- Memory Allocation --- #
        arg_allocs = []
        result_buffer_addr = 0
        result_string_buffer_addr = 0
        MAX_STRING_RESULT_LEN = 256

        try:
            # --- 1. Allocate memory for Lua function name ---
            lua_func_name_bytes = lua_func_name.encode('utf-8') + b'\0'
            alloc_func_name = self._allocate_memory(len(lua_func_name_bytes))
            if not alloc_func_name or not self._write_memory(alloc_func_name, lua_func_name_bytes):
                raise MemoryError("Failed to allocate/write Lua function name")
            arg_allocs.append(alloc_func_name)

            # --- 2. Allocate memory for result buffer ---
            num_returns = len(return_types)
            result_buffer_size = 0
            if num_returns > 0:
                max_result_size = max((8 if rt == 'number' else 4) for rt in return_types if rt in ['string', 'number', 'integer'])
                if max_result_size > 0:
                    result_buffer_size = num_returns * max_result_size
                    result_buffer_addr = self._allocate_memory(result_buffer_size)
                    if not result_buffer_addr:
                         raise MemoryError("Failed to allocate memory for result buffer")
                    if any(rt == 'string' for rt in return_types):
                         result_string_buffer_addr = self._allocate_memory(MAX_STRING_RESULT_LEN)
                         if not result_string_buffer_addr:
                             raise MemoryError("Failed to allocate memory for result string buffer")

            # --- 3. Build Shellcode ---
            shellcode = b''
            lua_stack_args = 0

            # --- Get Global Function using WoW 3.3.5a Pattern (Manual Lookup) ---
            # 1. Push C string pointer for function name
            shellcode += bytes([0x68, *alloc_func_name.to_bytes(4, 'little')])
            # 2. Push lua_State*
            shellcode += bytes([0x68, *self.lua_state.to_bytes(4, 'little')])
            # 3. Call lua_pushstring (Confirmed 0x84E350)
            shellcode += bytes([0xB8, *offsets.LUA_PUSHSTRING.to_bytes(4, 'little'), 0xFF, 0xD0])
            # 4. Clean up C args (L, ptr)
            shellcode += bytes([0x83, 0xC4, 0x08])
            # --- Lua stack now has function name string on top ---

            # 5. Push LUA_GLOBALSINDEX (Confirmed 0xFFFFD8EE)
            shellcode += bytes([0x68, *offsets.LUA_GLOBALSINDEX.to_bytes(4, 'little', signed=True)])
            # 6. Push lua_State*
            shellcode += bytes([0x68, *self.lua_state.to_bytes(4, 'little')])
            # 7. Call lua_getfield_by_stack_key (Confirmed 0x84E600)
            shellcode += bytes([0xB8, *offsets.LUA_GETFIELD_BY_STACK_KEY.to_bytes(4, 'little'), 0xFF, 0xD0])
            # 8. Clean up C args (L, index)
            shellcode += bytes([0x83, 0xC4, 0x08])
            # --- Lua stack now has the actual global function on top ---

            # --- Push arguments (Only strings and integers enabled) ---
            for arg in args:
                if isinstance(arg, str):
                    arg_bytes = arg.encode('utf-8') + b'\0'
                    alloc = self._allocate_memory(len(arg_bytes))
                    if not alloc or not self._write_memory(alloc, arg_bytes):
                        raise MemoryError(f"Failed to allocate/write string arg: {arg}")
                    arg_allocs.append(alloc)
                    shellcode += bytes([
                        0x68, *alloc.to_bytes(4, 'little'),
                        0x68, *self.lua_state.to_bytes(4, 'little'),
                        0xB8, *offsets.LUA_PUSHSTRING.to_bytes(4, 'little'),
                        0xFF, 0xD0, # call eax
                        0x83, 0xC4, 0x08 # add esp, 8
                    ])
                    lua_stack_args += 1
                elif isinstance(arg, int):
                    # lua_pushinteger(L, n) (Confirmed 0x84E2D0)
                    shellcode += bytes([
                        0x68, *arg.to_bytes(4, 'little', signed=True), # push n (integer arg)
                        0x68, *self.lua_state.to_bytes(4, 'little'),   # push L
                        0xB8, *offsets.LUA_PUSHINTEGER.to_bytes(4, 'little'), # mov eax, lua_pushinteger
                        0xFF, 0xD0,                                     # call eax
                        0x83, 0xC4, 0x08                                # add esp, 8
                    ])
                    lua_stack_args += 1
                # --- Other types still disabled ---
                elif isinstance(arg, bool):
                    print("ERROR: Boolean arguments disabled - LUA_PUSHBOOLEAN offset unconfirmed.", "ERROR")
                    raise TypeError("Boolean arguments disabled due to unconfirmed offset.")
                elif isinstance(arg, float):
                    print("ERROR: Float arguments disabled (requires double handling).", "ERROR")
                    raise TypeError("Float arguments disabled.")
                else:
                    raise TypeError(f"Unsupported arg type: {type(arg)}")

            # --- Call lua_pcall ---
            shellcode += bytes([
                0x6A, 0x00, # push 0 (errfunc)
                0x6A, num_returns,
                0x6A, lua_stack_args,
                0x68, *self.lua_state.to_bytes(4, 'little'),
                0xB8, *offsets.LUA_PCALL.to_bytes(4, 'little'),
                0xFF, 0xD0, # call eax (EAX = pcall status)
            ])

            # --- Check pcall status and prepare for results/cleanup ---
            # Store EAX (pcall status) temporarily into the start of the result buffer if allocated
            # This allows us to check for internal Lua errors after execution.
            shellcode_post_pcall = b''
            pcall_status_offset = 0 # Store status at the beginning
            pcall_status_size = 4
            if result_buffer_addr != 0:
                shellcode_post_pcall += bytes([
                    # Store EAX into result_buffer_addr + pcall_status_offset
                    0xA3, *(result_buffer_addr + pcall_status_offset).to_bytes(4, 'little')
                ])
                actual_result_offset = pcall_status_size # Start reading actual results after status
            else:
                actual_result_offset = 0 # No place to store status

            # If EAX != 0, jump to error cleanup. If EAX == 0, cleanup C args and proceed.
            shellcode_post_pcall += bytes([
                0x85, 0xC0,                                # test eax, eax
                0x0F, 0x85, 0x00, 0x00, 0x00, 0x00,        # jnz handle_pcall_error (Placeholder)
                # Pcall OK:
                0x83, 0xC4, 0x10,                           # add esp, 16 (Cleanup pcall C args)
                # Jump over error cleanup to result retrieval
                0xE9, 0x00, 0x00, 0x00, 0x00,              # jmp retrieve_results (Placeholder)
            ])
            handle_pcall_error_offset_rel = len(shellcode_post_pcall)
            shellcode_post_pcall += bytes([
                # Handle pcall Error (EAX != 0):
                0x83, 0xC4, 0x10,                           # add esp, 16 (Cleanup pcall C args)
                # Jump directly to error stack cleanup
                0xE9, 0x00, 0x00, 0x00, 0x00,              # jmp pcall_fail_cleanup (Placeholder)
            ])
            retrieve_results_start_offset_rel = len(shellcode_post_pcall)

            # --- Retrieve results (if pcall OK) ---
            result_retrieval_shellcode = b''
            current_buffer_write_offset = actual_result_offset # Where to write results in buffer
            sizeof_ptr = 4
            sizeof_double = 8
            for i in range(num_returns):
                result_index = -1 - i
                ret_type = return_types[num_returns - 1 - i]
                target_addr = result_buffer_addr + current_buffer_write_offset
                result_size = 0
                if ret_type == 'string':
                    result_size = sizeof_ptr
                    result_retrieval_shellcode += bytes([
                        0x6A, 0x00, 0x68, *result_index.to_bytes(4, 'little', signed=True),
                        0x68, *self.lua_state.to_bytes(4, 'little'),
                        0xB8, *offsets.LUA_TOLSTRING.to_bytes(4, 'little'), 0xFF, 0xD0,
                        0xA3, *target_addr.to_bytes(4, 'little'), 0x83, 0xC4, 0x0C
                    ])
                elif ret_type == 'number':
                    result_size = sizeof_double
                    result_retrieval_shellcode += bytes([
                        0x68, *result_index.to_bytes(4, 'little', signed=True),
                        0x68, *self.lua_state.to_bytes(4, 'little'),
                        0xB8, *offsets.LUA_TONUMBER.to_bytes(4, 'little'), 0xFF, 0xD0,
                        0xDB, 0x1D, *target_addr.to_bytes(4, 'little'), 0x83, 0xC4, 0x08
                    ])
                elif ret_type == 'integer':
                    result_size = sizeof_ptr
                    result_retrieval_shellcode += bytes([
                        0x68, *result_index.to_bytes(4, 'little', signed=True),
                        0x68, *self.lua_state.to_bytes(4, 'little'),
                        0xB8, *offsets.LUA_TOINTEGER.to_bytes(4, 'little'), 0xFF, 0xD0,
                        0xA3, *target_addr.to_bytes(4, 'little'), 0x83, 0xC4, 0x08
                    ])
                # --- Boolean type disabled ---
                elif ret_type == 'boolean':
                     raise TypeError("Boolean return type disabled due to unconfirmed offset.")
                else:
                     raise TypeError(f"Unsupported return type: {ret_type}")
                current_buffer_write_offset += result_size

            # --- Cleanup Lua stack (Success) ---
            success_stack_cleanup_shellcode = b''
            if num_returns > 0:
                 stack_target_index = -(num_returns + 1)
                 success_stack_cleanup_shellcode += bytes([
                     0x68, *stack_target_index.to_bytes(4,'little', signed=True),
                     0x68, *self.lua_state.to_bytes(4, 'little'),
                     0xB8, *offsets.LUA_SETTOP.to_bytes(4, 'little'), 0xFF, 0xD0,
                     0x83, 0xC4, 0x08
                 ])
            success_stack_cleanup_shellcode += bytes([0xE9, 0x00, 0x00, 0x00, 0x00]) # jmp final_exit

            pcall_fail_cleanup_start_offset_rel = len(shellcode_post_pcall) + len(result_retrieval_shellcode) + len(success_stack_cleanup_shellcode)
            # --- Cleanup Lua stack (Failure) ---
            pcall_fail_cleanup_shellcode = bytes([
                0x68, *(-2).to_bytes(4, 'little', signed=True), # push -2 (pop 1 item)
                0x68, *self.lua_state.to_bytes(4, 'little'),
                0xB8, *offsets.LUA_SETTOP.to_bytes(4, 'little'), 0xFF, 0xD0,
                0x83, 0xC4, 0x08
            ])
            final_exit_offset_rel = len(shellcode_post_pcall) + len(result_retrieval_shellcode) + len(success_stack_cleanup_shellcode) + len(pcall_fail_cleanup_shellcode)
            # --- final_exit: --- #

            # --- Assemble and Patch Jumps --- #
            base_shellcode = shellcode # GetGlobal + PushArgs + pcall
            post_pcall_logic = shellcode_post_pcall + result_retrieval_shellcode + success_stack_cleanup_shellcode + pcall_fail_cleanup_shellcode

            # Find jump instruction relative offsets within post_pcall_logic
            jnz_instr_offset_in_post = shellcode_post_pcall.find(b'\x0f\x85')
            jmp1_instr_offset_in_post = shellcode_post_pcall.find(b'\xe9', jnz_instr_offset_in_post)
            jmp2_instr_offset_in_post = shellcode_post_pcall.find(b'\xe9', jmp1_instr_offset_in_post + 1)
            jmp3_instr_offset_in_post = len(shellcode_post_pcall) + len(result_retrieval_shellcode) + success_stack_cleanup_shellcode.find(b'\xe9')

            # Calculate absolute targets
            jnz_target_abs = len(base_shellcode) + handle_pcall_error_offset_rel
            jmp1_target_abs = len(base_shellcode) + retrieve_results_start_offset_rel
            jmp2_target_abs = len(base_shellcode) + pcall_fail_cleanup_start_offset_rel
            jmp3_target_abs = len(base_shellcode) + final_exit_offset_rel

            # Calculate relative offsets from instruction *after* jump
            jnz_source_abs = len(base_shellcode) + jnz_instr_offset_in_post + 6
            jmp1_source_abs = len(base_shellcode) + jmp1_instr_offset_in_post + 5
            jmp2_source_abs = len(base_shellcode) + jmp2_instr_offset_in_post + 5
            jmp3_source_abs = len(base_shellcode) + jmp3_instr_offset_in_post + 5

            jnz_rel_offset = jnz_target_abs - jnz_source_abs
            jmp1_rel_offset = jmp1_target_abs - jmp1_source_abs
            jmp2_rel_offset = jmp2_target_abs - jmp2_source_abs
            jmp3_rel_offset = jmp3_target_abs - jmp3_source_abs

            # Patch the combined post_pcall_logic block
            patched_post_pcall_logic = bytearray(post_pcall_logic)
            patched_post_pcall_logic[jnz_instr_offset_in_post+2 : jnz_instr_offset_in_post+6] = jnz_rel_offset.to_bytes(4, 'little', signed=True)
            patched_post_pcall_logic[jmp1_instr_offset_in_post+1 : jmp1_instr_offset_in_post+5] = jmp1_rel_offset.to_bytes(4, 'little', signed=True)
            patched_post_pcall_logic[jmp2_instr_offset_in_post+1 : jmp2_instr_offset_in_post+5] = jmp2_rel_offset.to_bytes(4, 'little', signed=True)
            patched_post_pcall_logic[jmp3_instr_offset_in_post+1 : jmp3_instr_offset_in_post+5] = jmp3_rel_offset.to_bytes(4, 'little', signed=True)

            # Reassemble final shellcode AND ADD THE FINAL RET
            final_shellcode = base_shellcode + bytes(patched_post_pcall_logic) + b'\xc3'

            # --- 4. Execute Shellcode ---
            print(f"Executing Lua C API call to '{lua_func_name}' via pcall...", "DEBUG")
            output_specs = [(result_buffer_addr, result_buffer_size)] if result_buffer_size > 0 else None
            results_bytes_list = self._execute_shellcode(final_shellcode, output_specs)

            # --- 5. Process Results ---
            if results_bytes_list is None: # Thread execution failed
                 print(f"Shellcode execution failed entirely for Lua pcall {lua_func_name}.", "ERROR")
                 raise RuntimeError("Shellcode execution failed")

            # Check pcall status if buffer was allocated
            pcall_status = 0 # Assume success if no buffer
            if result_buffer_addr != 0 and len(results_bytes_list) > 0 and results_bytes_list[0] is not None and len(results_bytes_list[0]) >= pcall_status_size:
                pcall_status = struct.unpack('<i', results_bytes_list[0][:pcall_status_size])[0]
                if pcall_status != 0:
                    print(f"Lua pcall '{lua_func_name}' failed internally (Error code: {pcall_status}). Check Lua stack/error message.", "ERROR")
                    # Error message might be readable if we implement retrieval
                    return None # Indicate internal Lua failure
            elif result_buffer_addr != 0:
                 print(f"Warning: Could not read pcall status for {lua_func_name}. Assuming success but results may be invalid.", "WARNING")
                 # Proceed with caution

            # Process results only if pcall succeeded (status 0) and returns expected
            final_results = []
            if pcall_status == 0 and num_returns > 0:
                if not results_bytes_list or not results_bytes_list[0]:
                     print(f"Error: Missing result buffer data after successful pcall for {lua_func_name}.", "ERROR")
                     return None # Should not happen if status was readable

                raw_results_buffer = results_bytes_list[0][actual_result_offset:] # Skip status bytes
                results_offset = 0
                for i in range(num_returns):
                    ret_type = return_types[num_returns - 1 - i]
                    result_size = 0
                    if ret_type == 'number': result_size = 8
                    elif ret_type in ['string', 'integer']: result_size = 4

                    if results_offset + result_size > len(raw_results_buffer):
                         print(f"Error unpacking results: buffer too small ({len(raw_results_buffer)} bytes) for type '{ret_type}' at offset {results_offset}", "ERROR")
                         return None # Error processing results

                    current_result_bytes = raw_results_buffer[results_offset : results_offset + result_size]

                    if ret_type == 'string':
                        string_ptr = struct.unpack('<I', current_result_bytes)[0]
                        if string_ptr == 0: final_results.append(None)
                        else:
                            string_data = self._read_memory(string_ptr, MAX_STRING_RESULT_LEN)
                            if string_data:
                                null_pos = string_data.find(b'\0')
                                decoded = string_data[:null_pos if null_pos != -1 else None].decode('utf-8', errors='replace')
                                final_results.append(decoded)
                            else: final_results.append(None)
                        results_offset += 4
                    elif ret_type == 'number':
                        final_results.append(struct.unpack('<d', current_result_bytes)[0])
                        results_offset += 8
                    elif ret_type == 'integer':
                        final_results.append(struct.unpack('<i', current_result_bytes)[0])
                        results_offset += 4
                    # Boolean disabled
            elif pcall_status == 0 and num_returns == 0:
                 # Successful pcall, no returns expected
                 return []

            # If we got here, pcall succeeded and results (if any) were processed
            print(f"Lua pcall '{lua_func_name}' results: {final_results}", "DEBUG")
            return final_results

        except (MemoryError, OSError, RuntimeError, struct.error, TypeError, ValueError) as e:
            print(f"GameInterface Error (Lua pcall): {type(e).__name__} - {e}", "ERROR")
            return None
        except Exception as e:
            print(f"GameInterface Error: Unexpected error during call_lua_function (pcall) - {type(e).__name__}: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return None
        finally:
            # --- Cleanup --- #
            for alloc in arg_allocs: # Free string/name allocations
                if alloc: self._free_memory(alloc)
            if result_buffer_addr: # Free result buffer
                self._free_memory(result_buffer_addr)
            if result_string_buffer_addr: # Free string reading buffer
                 self._free_memory(result_string_buffer_addr)

    def get_spell_cooldown(self, spell_id: int) -> Optional[dict]:
        """
        Gets spell cooldown information by calling the Lua function GetSpellCooldown.

        Args:
            spell_id: The ID of the spell.

        Returns:
            A dictionary with 'startTime', 'duration', 'enabled', and calculated 'remaining',
            or None if the Lua call fails.
            - startTime (ms, from Lua - may differ from C function)
            - duration (ms, from Lua - may differ from C function)
            - enabled (bool, True if spell usable off CD/GCD)
            - remaining (float, calculated seconds until ready)
        """
        if not self.is_ready() or not self.lua_state:
            print("GameInterface Error: Not ready for Lua spell cooldown check.", "ERROR")
            return None

        lua_func_name = "GetSpellCooldown"
        args = [spell_id]
        # Lua API: startTime, duration, isEnabled
        # Temporarily remove boolean as LUA_TOBOOLEAN is unconfirmed
        return_types = ['number', 'number'] # REMOVED: 'boolean'

        try:
            # print(f"Calling Lua {lua_func_name}({spell_id})...", "DEBUG")
            results = self.call_lua_function(lua_func_name, args, return_types)

            # Adjust check for number of results
            if results is None or len(results) != 2: # CHANGED from 3
                print(f"Lua call {lua_func_name} for spell {spell_id} failed or returned unexpected results: {results}", "ERROR")
                return None

            # Adjust unpacking
            start_time_lua, duration_lua = results # REMOVED: enabled_lua
            # Ensure results are valid types before proceeding
            # REMOVED check for enabled_lua type
            if not isinstance(start_time_lua, (int, float)) or not isinstance(duration_lua, (int, float)):
                 print(f"Lua call {lua_func_name} returned unexpected types for spell {spell_id}: {type(start_time_lua)}, {type(duration_lua)}", "ERROR")
                 return None

            # Calculate remaining cooldown
            # Cannot reliably determine if CD is truly ready without 'enabled' flag.
            # Set remaining based purely on time for now.
            remaining = 0.0
            # Simplified check: if duration > 0, calculate remaining time.
            if duration_lua > 0:
                current_game_time = self.get_game_time_millis_direct() # Returns millis
                if current_game_time is not None:
                     start_time_ms = start_time_lua * 1000
                     duration_ms = duration_lua * 1000
                     expiry_time_ms = start_time_ms + duration_ms
                     remaining_ms = max(0, expiry_time_ms - current_game_time)
                     remaining = remaining_ms / 1000.0
                else:
                     print("Warning: Could not get game time to calculate remaining cooldown.", "WARNING")

            cooldown_info = {
                "startTime": int(start_time_lua * 1000) if isinstance(start_time_lua, (int, float)) else None,
                "duration": int(duration_lua * 1000) if isinstance(duration_lua, (int, float)) else None,
                "enabled": None, # Cannot determine reliably yet
                "remaining": remaining
            }
            # print(f"Lua Cooldown Info for {spell_id}: {cooldown_info}", "DEBUG")
            return cooldown_info

        # Add specific TypeError handling if call_lua_function raises it
        except TypeError as te:
            print(f"GameInterface Type Error during get_spell_cooldown (Lua) - {te}", "ERROR")
            return None
        except Exception as e:
            print(f"GameInterface Error: Unexpected error during get_spell_cooldown (Lua) - {type(e).__name__}: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return None

    def get_spell_range(self, spell_id: int) -> Optional[dict]:
        """
        Gets spell range information by calling the Lua function GetSpellInfo.

        Args:
            spell_id: The ID of the spell.

        Returns:
            A dictionary with 'minRange' and 'maxRange' (floats), or None if the call fails.
        """
        if not self.is_ready() or not self.lua_state:
            print("GameInterface Error: Not ready for Lua spell range check.", "ERROR")
            return None

        lua_func_name = "GetSpellInfo"
        args = [spell_id]
        # GetSpellInfo returns: name[1], rank[2], icon[3], cost[4], isFunnel[5],
        #                     powerType[6], castTime[7], minRange[8], maxRange[9]
        # Indices adjusted for 0-based Python list
        return_types = [
            'string', 'string', 'string', 'number', 'boolean', 
            'number', 'number', 'number', 'number'
        ]

        try:
            # print(f"Calling Lua {lua_func_name}({spell_id}) for range...", "DEBUG")
            results = self.call_lua_function(lua_func_name, args, return_types)

            if results is None or len(results) != 9:
                print(f"Lua call {lua_func_name} for spell {spell_id} range failed or returned unexpected results: {results}", "ERROR")
                return None

            # Extract minRange (index 7) and maxRange (index 8)
            min_range = results[7]
            max_range = results[8]

            # Validate types
            if not isinstance(min_range, (int, float)) or not isinstance(max_range, (int, float)):
                print(f"Lua call {lua_func_name} returned unexpected range types for spell {spell_id}: {type(min_range)}, {type(max_range)}", "ERROR")
                return None

            range_info = {
                "minRange": float(min_range),
                "maxRange": float(max_range)
            }
            # print(f"Lua Range Info for {spell_id}: {range_info}", "DEBUG")
            return range_info

        except Exception as e:
            print(f"GameInterface Error: Unexpected error during get_spell_range (Lua) - {type(e).__name__}: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return None

    def is_spell_in_range(self, spell_id: int, target_unit_id: str = "target") -> Optional[int]:
        """
        Checks if a spell is usable on the target unit based on range.
        Uses the Lua function IsSpellInRange(spellID, unitID).

        Args:
            spell_id: The ID of the spell.
            target_unit_id: The unit identifier string (e.g., "target", "player", "focus").

        Returns:
            1 if the spell is in range.
            0 if the spell is out of range.
            None if the Lua call fails or the spell/unit is invalid.
        """
        # Option 1: Use IsSpellInRange(spellID, unitID) -> returns 0 or 1
        if not self.is_ready() or not self.lua_state:
            print("GameInterface Error: Not ready for Lua spell range check (IsSpellInRange).", "ERROR")
            return None

        lua_func_name = "IsSpellInRange"
        args = [spell_id, target_unit_id] # Pass spell ID (int) and unit ID (string)
        return_types = ['number'] # Lua function returns 0 or 1 (treated as number)

        try:
            # print(f"Calling Lua {lua_func_name}({spell_id}, '{target_unit_id}')...", "DEBUG")
            results = self.call_lua_function(lua_func_name, args, return_types)

            if results is None or len(results) != 1:
                print(f"Lua call {lua_func_name} for spell {spell_id} on '{target_unit_id}' failed or returned unexpected results: {results}", "ERROR")
                return None

            in_range_result = results[0]

            # Lua returns 0 or 1, which is read as a number (float/int)
            if isinstance(in_range_result, (int, float)) and in_range_result in [0, 1]:
                # print(f"Lua IsSpellInRange({spell_id}, '{target_unit_id}') returned: {int(in_range_result)}", "DEBUG")
                return int(in_range_result)
            else:
                 print(f"Lua call {lua_func_name} returned unexpected value: {in_range_result} ({type(in_range_result)})")
                 return None

        except Exception as e:
            print(f"GameInterface Error: Unexpected error during is_spell_in_range (Lua) - {type(e).__name__}: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return None

        # --- Option 2: (Legacy/Alternative) Get range values and compare with target distance --- #
        # Requires target distance calculation, which depends on ObjectManager
        # range_info = self.get_spell_range(spell_id) # Call the new Lua-based range getter
        # if range_info is None:
        #     print(f"Error: Could not get range info for spell {spell_id} to check range.")
        #     return None

        # min_range = range_info["minRange"]
        # max_range = range_info["maxRange"]

        # # Get target distance
        # if not self.om or not self.om.local_player:
        #     print("Error: Cannot check range, ObjectManager or Local Player not found.", "ERROR")
        #     return None

        # target = self.om.get_object_by_unit_id(target_unit_id)
        # if not target:
        #     print(f"Error: Cannot check range, target unit '{target_unit_id}' not found.", "ERROR")
        #     return None

        # distance = self.om.local_player.distance_to(target.position)
        # if distance is None:
        #      print("Error: Could not calculate distance to target.", "ERROR")
        #      return None

        # # Perform the check (consider melee range slightly differently?)
        # # Standard check: min_range <= distance <= max_range
        # # Simplification: Check only max_range for now, assume min_range is 0 or handled by game
        # if distance <= max_range:
        #     # print(f"Range Check: Spell {spell_id} (Max: {max_range:.1f}yd) IN RANGE for '{target_unit_id}' (Dist: {distance:.1f}yd)", "DEBUG")
        #     return 1 # In range
        # else:
        #     # print(f"Range Check: Spell {spell_id} (Max: {max_range:.1f}yd) OUT OF RANGE for '{target_unit_id}' (Dist: {distance:.1f}yd)", "DEBUG")
        #     return 0 # Out of range

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
            cooldown_info = game.get_spell_cooldown(test_spell_id)
            if cooldown_info:
                 print(f"Cooldown Info: Duration={cooldown_info['duration']}ms, Start={cooldown_info['startTime']}, Enabled={cooldown_info['enabled']}")
            else:
                 print("Failed to get cooldown info.")

            print(f"\n--- Testing Direct Range Call (SpellID: {test_spell_id}) ---")
            # Try getting player object pointer if ObjectManager exists and is populated
            # context = 0
            # if game.mem.om and game.mem.om.local_player:
            #      context = game.mem.om.local_player.base_address # Example context
            # print(f"Using context pointer: {hex(context)}")
            range_info = game.get_spell_range(test_spell_id) # Using default context=0 for now
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