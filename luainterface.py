import ctypes
from ctypes import wintypes # For pointer types like DWORD
import time
import pymem
import offsets
from memory import MemoryHandler
from typing import Union, Any, List, Optional
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

class LuaInterface:
    """Handles interaction with the WoW Lua engine via C API calls."""

    def __init__(self, mem_handler: MemoryHandler):
        self.mem = mem_handler
        # LUA_STATE offset holds the ADDRESS where the lua_State* pointer is stored
        self.lua_state_ptr_addr = offsets.LUA_STATE
        self.lua_state = 0 # The actual lua_State* value

        if not self.mem or not self.mem.is_attached():
            print("LuaInterface Error: Memory Handler not attached.")
            return

        # Read the lua_State* pointer value from the static address
        self.lua_state = self.mem.read_uint(self.lua_state_ptr_addr)
        if not self.lua_state:
             print(f"LuaInterface Error: Could not read Lua State pointer value from address {hex(self.lua_state_ptr_addr)}. Lua C API calls will fail.")
        else:
            print(f"Lua State Pointer Value Found: {hex(self.lua_state)}")

    def is_ready(self) -> bool:
        """Check if the Lua Interface can interact (Memory attached and Lua State pointer read)."""
        # Add a check to re-read Lua state if it seems invalid? Maybe later.
        return bool(self.mem and self.mem.is_attached() and self.lua_state)

    def _allocate_memory(self, size: int, permissions: int = PAGE_EXECUTE_READWRITE) -> Optional[int]:
        """Helper to allocate memory in the target process."""
        if not self.is_ready(): return None
        process_handle = self.mem.pm.process_handle
        address = VirtualAllocEx(process_handle, 0, size, MEM_COMMIT | MEM_RESERVE, wintypes.DWORD(permissions))
        if not address:
             print(f"Error: Failed to allocate {size} bytes. Error code: {kernel32.GetLastError()}")
             return None
        return address

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


    def _execute_shellcode(self, shellcode: bytes, result_size: int = 4) -> Optional[bytes]:
        """
        Executes shellcode in the target process using CreateRemoteThread.
        Uses an allocated buffer to retrieve the function's return value (from EAX or FPU ST0).
        Returns the raw bytes read from the result buffer, or None on failure, or b'' for result_size=0 success.
        result_size: Expected size of the return value (4=int/ptr, 8=double, 0=void).
        """
        if not self.is_ready():
             print("Error: Cannot execute shellcode, LuaInterface not ready.")
             return None

        shellcode_alloc = None
        result_buffer_alloc = None
        thread_handle = None
        process_handle = self.mem.pm.process_handle
        final_shellcode = b""

        try:
            # 1. Allocate result buffer (if needed)
            if result_size > 0:
                result_buffer_alloc = self._allocate_memory(result_size, wintypes.DWORD(0x04)) # PAGE_READWRITE
                if not result_buffer_alloc: raise OSError("Failed to allocate result buffer")
                # print(f"DEBUG: Allocated result buffer at {hex(result_buffer_alloc)}")

            # 2. Construct final shellcode (Base + Store Result + RET)
            store_instructions = b""
            if result_buffer_alloc: # Only add store instructions if buffer exists
                if result_size == 8: # Double return (lua_tonumber) -> FPU ST(0)
                    # FSTP QWORD PTR [result_buffer_alloc] ; Store FP value and Pop
                    store_instructions = bytes([0xDD, 0x1D]) + result_buffer_alloc.to_bytes(4, 'little')
                elif result_size > 0: # Integer/Pointer/Boolean return -> EAX
                    # MOV [result_buffer_alloc], EAX
                    store_instructions = bytes([0xA3]) + result_buffer_alloc.to_bytes(4, 'little')

            if not shellcode.endswith(b'\xC3'):
                print("CRITICAL WARNING: Base shellcode missing final RET (0xC3). Execution unreliable.")
                # Still try to append store + ret, hoping base code balanced stack
                final_shellcode = shellcode + store_instructions + b'\xC3'
            else:
                # Replace original RET with store instructions + new RET
                final_shellcode = shellcode[:-1] + store_instructions + b'\xC3'

            # 3. Allocate memory for the final shellcode
            shellcode_alloc = self._allocate_memory(len(final_shellcode), PAGE_EXECUTE_READWRITE)
            if not shellcode_alloc: raise OSError("Failed to allocate shellcode memory")

            # 4. Write the final shellcode
            if not self._write_memory(shellcode_alloc, final_shellcode):
                 raise OSError("Failed to write final shellcode")

            # 5. Create and run the remote thread
            thread_handle = CreateRemoteThread(process_handle, None, 0, shellcode_alloc, None, 0, None)
            if not thread_handle:
                 raise OSError(f"Failed to create remote thread. Error: {kernel32.GetLastError()}")

            # 6. Wait for thread completion (with timeout)
            wait_result = WaitForSingleObject(thread_handle, 5000) # 5 second timeout
            if wait_result == 0x102: # WAIT_TIMEOUT
                 print("Warning: Remote thread timed out execution.")
                 # Consider TerminateThread? Risky.
            elif wait_result != 0x0: # WAIT_OBJECT_0
                 print(f"Warning: WaitForSingleObject returned code {wait_result}")

            # 7. Read the result from the allocated buffer
            result_bytes = None
            if result_buffer_alloc and result_size > 0:
                result_bytes = self._read_memory(result_buffer_alloc, result_size)
                if result_bytes is None:
                     print(f"CRITICAL Warning: Failed to read result buffer {hex(result_buffer_alloc)}. Process crash or memory issue?")
            elif result_size == 0:
                return b'' # Indicate success for void functions

            return result_bytes # Return raw bytes or None

        except pymem.exception.PymemError as e:
            print(f"LuaInterface Shellcode PymemError: {e}")
            return None
        except OSError as e:
             print(f"LuaInterface Shellcode OSError: {e}")
             return None
        except Exception as e:
            print(f"LuaInterface Shellcode Unexpected Error: {type(e).__name__}: {e}")
            import traceback
            # traceback.print_exc() # Uncomment for full traceback during debugging
            return None
        finally:
            # Cleanup
            if thread_handle: CloseHandle(thread_handle)
            if shellcode_alloc: self._free_memory(shellcode_alloc)
            if result_buffer_alloc: self._free_memory(result_buffer_alloc)

    # --- Lua C API Wrappers ---

    def get_top(self) -> Optional[int]:
        """Calls lua_gettop(L). Returns stack top index or None on failure."""
        if not self.is_ready(): return None
        func_addr = offsets.LUA_GETTOP
        state_ptr = self.lua_state

        # Shellcode: push lua_state; call LUA_GETTOP; add esp, 4; RET (Result in EAX)
        shellcode = bytes([
            0x68, *state_ptr.to_bytes(4, 'little'), # push state_ptr
            0xB8, *func_addr.to_bytes(4, 'little'), # mov eax, func_addr
            0xFF, 0xD0,                         # call eax
            0x83, 0xC4, 0x04,                   # add esp, 4 ; Cleanup arg
            0xC3                                # ret
        ])

        result_bytes = self._execute_shellcode(shellcode, result_size=4)
        if result_bytes is not None:
            return int.from_bytes(result_bytes, 'little', signed=True)
        # print("Error: get_top() failed to execute or read result.") # Reduce spam
        return None

    def set_top(self, index: int) -> bool:
        """Calls lua_settop(L, index). Returns True on success attempt."""
        if not self.is_ready(): return False
        func_addr = offsets.LUA_SETTOP
        state_ptr = self.lua_state

        # Shellcode: push index; push lua_state; call LUA_SETTOP; add esp, 8; RET
        shellcode = bytes([
            0x68, *index.to_bytes(4, 'little', signed=True), # push index
            0x68, *state_ptr.to_bytes(4, 'little'),          # push state_ptr
            0xB8, *func_addr.to_bytes(4, 'little'),          # mov eax, func_addr
            0xFF, 0xD0,                                      # call eax
            0x83, 0xC4, 0x08,                                # add esp, 8 ; Cleanup args
            0xC3                                             # ret
        ])

        result = self._execute_shellcode(shellcode, result_size=0) # result_size=0 for void
        if result is None:
             # print(f"Error: set_top({index}) failed to execute.") # Reduce spam
             return False
        return True


    def pop(self, n: int) -> bool:
        """Calls lua_pop(L, n), equivalent to settop(L, -n-1). Returns True on success attempt."""
        if not self.is_ready(): return False
        # Using settop is generally safer unless LUA_POP offset is needed for specific reason
        current_top = self.get_top()
        if current_top is not None:
            return self.set_top(current_top - n)
        return False


    def to_string(self, index: int) -> Optional[str]:
        """Calls lua_tolstring(L, index, NULL). Returns string or None."""
        if not self.is_ready(): return None
        func_addr = offsets.LUA_TOLSTRING
        state_ptr = self.lua_state

        # Shellcode: push 0 (len ptr); push index; push lua_state; call LUA_TOLSTRING; add esp, 0xC; RET (Result Ptr in EAX)
        shellcode = bytes([
            0x6A, 0x00,                                      # push 0 (arg3: len* = NULL)
            0x68, *index.to_bytes(4, 'little', signed=True), # push index (arg2)
            0x68, *state_ptr.to_bytes(4, 'little'),          # push state_ptr (arg1)
            0xB8, *func_addr.to_bytes(4, 'little'),          # mov eax, func_addr
            0xFF, 0xD0,                                      # call eax
            0x83, 0xC4, 0x0C,                                # add esp, 0xC ; Cleanup args
            0xC3                                             # ret
        ])

        result_bytes = self._execute_shellcode(shellcode, result_size=4)
        if result_bytes is not None:
            string_ptr = int.from_bytes(result_bytes, 'little')
            if string_ptr != 0:
                try:
                    return self.mem.read_string(string_ptr, max_length=512) # Increased length
                except Exception as e:
                     print(f"Error reading string from pointer {hex(string_ptr)}: {e}")
                     return None
            else:
                 return None # Lua function returned NULL (e.g., value not convertible to string)
        # print(f"Error: to_string({index}) failed.") # Reduce spam
        return None

    def to_number(self, index: int) -> Optional[float]:
        """Calls lua_tonumber(L, index). Returns float (double) or None."""
        if not self.is_ready(): return None
        func_addr = offsets.LUA_TONUMBER
        state_ptr = self.lua_state

        # Shellcode: push index; push lua_state; call LUA_TONUMBER; add esp, 8; RET (Result in FPU ST0)
        shellcode = bytes([
            0x68, *index.to_bytes(4, 'little', signed=True), # push index
            0x68, *state_ptr.to_bytes(4, 'little'),          # push state_ptr
            0xB8, *func_addr.to_bytes(4, 'little'),          # mov eax, func_addr
            0xFF, 0xD0,                                      # call eax
            0x83, 0xC4, 0x08,                                # add esp, 8 ; Cleanup args
            0xC3                                             # ret
        ])

        result_bytes = self._execute_shellcode(shellcode, result_size=8) # Expect 8 bytes for double
        if result_bytes is not None:
            try:
                number = struct.unpack('<d', result_bytes)[0] # '<d' = little-endian double
                return number
            except struct.error as e:
                 print(f"Error unpacking double from bytes {result_bytes.hex()}: {e}")
                 return None
        # print(f"Error: to_number({index}) failed.") # Reduce spam
        return None

    def to_boolean(self, index: int) -> Optional[bool]:
        """Calls lua_toboolean(L, index). Returns bool or None on failure."""
        if not self.is_ready(): return None
        func_addr = offsets.LUA_TOBOOLEAN
        state_ptr = self.lua_state

        # Shellcode: push index; push lua_state; call LUA_TOBOOLEAN; add esp, 8; RET (Result Int in EAX=0 or non-zero)
        shellcode = bytes([
            0x68, *index.to_bytes(4, 'little', signed=True), # push index
            0x68, *state_ptr.to_bytes(4, 'little'),          # push state_ptr
            0xB8, *func_addr.to_bytes(4, 'little'),          # mov eax, func_addr
            0xFF, 0xD0,                                      # call eax
            0x83, 0xC4, 0x08,                                # add esp, 8 ; Cleanup args
            0xC3                                             # ret
        ])

        result_bytes = self._execute_shellcode(shellcode, result_size=4)
        if result_bytes is not None:
            bool_int = int.from_bytes(result_bytes, 'little')
            # Lua convention: false and nil are false, everything else is true
            return bool_int != 0
        # print(f"Error: to_boolean({index}) failed.") # Reduce spam
        return None

    # --- Higher Level Lua Interaction ---

    def execute(self, lua_code: str, source_name: str = "PyWoWExec") -> bool:
        """
        Executes a string of Lua code using FrameScript_Execute (fire and forget).
        Best for actions like casting, using items, running macros.
        Returns True if execution was attempted, False on memory/allocation error.
        """
        if not self.is_ready():
            print("LuaInterface Error: Not ready to execute (FrameScript).")
            return False
        if not lua_code:
            print("LuaInterface Warning: Empty Lua code provided to execute().")
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
            print(f"LuaInterface Error (Pymem) in execute: {e}")
            return False
        except OSError as e:
             print(f"LuaInterface Error (OS) in execute: {e}")
             return False
        except Exception as e:
            print(f"LuaInterface Error: Unexpected error during execute - {type(e).__name__}: {e}")
            return False
        finally:
            # Cleanup allocated strings
            if alloc_lua_code: self._free_memory(alloc_lua_code)
            if alloc_source_name: self._free_memory(alloc_source_name)


    def call_function(self, lua_code_to_run: str, num_expected_results: int) -> Optional[List[Any]]:
        """
        Attempts to execute Lua code and retrieve results from the stack using basic wrappers.
        WARNING: This is less reliable than a proper implementation using pcall.
                 It uses execute() and then tries to read the stack.
        """
        if not self.is_ready():
            print("LuaInterface Error: Not ready for call_function.")
            return None

        initial_top = self.get_top()
        if initial_top is None:
            print("LuaInterface Error: Failed to get initial stack top for call_function.")
            return None
        # print(f"DEBUG Lua Call: Initial stack top: {initial_top}")

        results = []
        try:
            # 1. Execute the code (using FrameScript_Execute)
            if not self.execute(lua_code_to_run, "LuaCallFunc"):
                 print("LuaInterface Error: Failed to execute Lua code in call_function.")
                 self.set_top(initial_top) # Attempt cleanup
                 return None

            time.sleep(0.05) # Give Lua a moment

            # 2. Get stack top after execution
            final_top = self.get_top()
            if final_top is None:
                 print("LuaInterface Error: Failed to get final stack top after execution.")
                 self.set_top(initial_top) # Attempt cleanup
                 return None

            actual_results = final_top - initial_top
            # print(f"DEBUG Lua Call: Stack top after execution: {final_top} ({actual_results} results on stack)")

            if actual_results < 0:
                 print(f"Error: Stack top decreased after call ({initial_top} -> {final_top}). Code: {lua_code_to_run[:50]}...")
                 self.set_top(initial_top) # Cleanup
                 return None

            num_to_read = min(actual_results, num_expected_results)
            if actual_results < num_expected_results:
                 print(f"Warning: Lua call resulted in {actual_results} items, expected {num_expected_results}. Reading available.")
            elif actual_results > num_expected_results:
                 print(f"Warning: Lua call resulted in {actual_results} items, expected {num_expected_results}. Reading only expected.")

            # 3. Retrieve results (from top of stack downwards)
            for i in range(num_to_read):
                stack_index = -(i + 1) # -1, -2, ...

                # Attempt type retrieval (Try number -> boolean -> string)
                value_num = self.to_number(stack_index)
                if value_num is not None:
                    results.append(value_num)
                    continue

                value_bool = self.to_boolean(stack_index)
                if value_bool is not None:
                    results.append(value_bool)
                    continue

                value_str = self.to_string(stack_index)
                if value_str is not None:
                    results.append(value_str)
                    continue

                # If nothing worked, it might be nil or an unsupported type
                # TODO: Check lua_type(index) == LUA_TNIL
                print(f"Warning: Could not determine type or read value from stack index {stack_index}")
                results.append(None) # Append None to maintain result count


            # Reverse results because we read from top (-1, -2...) but want order as returned
            return results[::-1]

        except Exception as e:
            print(f"LuaInterface Error during call_function: {type(e).__name__}: {e}")
            return None
        finally:
            # 4. Clean up stack: Restore original top
            # print(f"DEBUG Lua Call: Cleaning stack, setting top to {initial_top}")
            if initial_top is not None:
                 self.set_top(initial_top)


# --- Example Usage ---
if __name__ == "__main__":
    print("Attempting to initialize Lua Interface...")
    mem = MemoryHandler()
    if mem.is_attached():
        lua = LuaInterface(mem)
        if lua.is_ready():
            print("Lua Interface Initialized.")

            # --- Test Core C API Calls (Buffer Method) ---
            print("\n--- Testing Basic Lua C API Calls ---")

            top1 = lua.get_top()
            print(f"1. Initial Stack Top: {top1}")

            print("\nExecuting: _G.my_test_var = 123.45; print('Set test var')")
            lua.execute("_G.my_test_var = 123.45; print('Set test var')")
            time.sleep(0.1)

            top2 = lua.get_top()
            print(f"2. Stack Top after execute: {top2} (Should be same as initial: {top1 == top2})")

            # --- Test call_function with the simplified implementation ---
            print("\n--- Testing call_function (Reads stack after execute) ---")

            # Ensure stack is clean before call
            if top1 is not None: lua.set_top(top1)
            time.sleep(0.05)
            top_before_call = lua.get_top()
            print(f"3. Stack Top before call_function: {top_before_call}")

            call_code = "return 99, 'call_func test', true, nil, false, 1.23"
            print(f"4. Executing: {call_code}")
            results = lua.call_function(call_code, 6) # Expect 6 results
            print(f"5. Results from call_function: {results}")
            if results:
                print(f"   Types: {[type(r).__name__ for r in results]}")

            top_after_call = lua.get_top()
            print(f"6. Stack Top after call_function (and cleanup): {top_after_call} (Should match before: {top_before_call == top_after_call})")

            # --- Verification using direct calls on stack items (if call succeeded) ---
            if results and len(results) == 6 and top_after_call == top_before_call:
                 print("\n--- Verifying direct C API calls on returned values ---")
                 # Manually push the results back onto the stack to test reading them
                 # This requires working push functions - skip for now.
                 # Instead, just report that call_function worked.
                 print("   (Skipping direct verification - requires push* functions)")
            elif results is None:
                 print("call_function failed.")
            else:
                 print("call_function might have worked but stack cleanup or result count seems off.")

            print("--------------------------------------")

        else:
            print("Failed to initialize Lua Interface (is_ready() failed).")
    else:
        print("Failed to attach Memory Handler.")