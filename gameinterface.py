import ctypes
from ctypes import wintypes
import time
import pymem # Keep for process finding? Maybe remove later if not needed.
import offsets # Keep for LUA_STATE and function addrs if needed by DLL
from memory import MemoryHandler # Keep if mem handler needed for other tasks
# from object_manager import ObjectManager # No longer needed directly here
from typing import Optional # Union, Any, List, Tuple - Removed unused

# --- Pipe Constants ---
PIPE_NAME = r'\\.\pipe\WowInjectPipe' # Raw string literal
PIPE_BUFFER_SIZE = 1024 * 4 # 4KB buffer for commands/responses
PIPE_TIMEOUT_MS = 5000 # Timeout for connection attempts

# Windows API Constants for Pipes
INVALID_HANDLE_VALUE = -1 # Using ctypes default which is -1 for handles
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
ERROR_PIPE_BUSY = 231

# Kernel32 Functions needed for Pipes
kernel32 = ctypes.windll.kernel32
CreateFileW = kernel32.CreateFileW
WriteFile = kernel32.WriteFile
ReadFile = kernel32.ReadFile
CloseHandle = kernel32.CloseHandle
WaitNamedPipeW = kernel32.WaitNamedPipeW
GetLastError = kernel32.GetLastError

# Define argument types for clarity and correctness
CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
CreateFileW.restype = wintypes.HANDLE
WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
WaitNamedPipeW.restype = wintypes.BOOL
WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
WriteFile.restype = wintypes.BOOL
ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
ReadFile.restype = wintypes.BOOL
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL


class GameInterface:
    """Handles interaction with the WoW process via an injected DLL using Named Pipes."""

    def __init__(self, mem_handler: MemoryHandler):
        self.mem = mem_handler # Keep mem_handler reference if needed elsewhere
        self.pipe_handle: Optional[wintypes.HANDLE] = None # Initialize pipe handle
        # Removed Lua state, VirtualFree, and other shellcode-related initializations

        # Attempt initial connection? Optional, or connect explicitly later.
        # self.connect_pipe()

    def is_ready(self) -> bool:
        """Check if the pipe connection to the injected DLL is established."""
        return self.pipe_handle is not None and self.pipe_handle != INVALID_HANDLE_VALUE

    def connect_pipe(self, timeout_ms: int = PIPE_TIMEOUT_MS) -> bool:
        """Attempts to connect to the named pipe server run by the injected DLL."""
        if self.is_ready():
            print("[GameInterface] Already connected to pipe.")
            return True

        pipe_name_lpcwstr = wintypes.LPCWSTR(PIPE_NAME)

        try:
            # Wait for the pipe to become available
            if not WaitNamedPipeW(pipe_name_lpcwstr, timeout_ms):
                error_code = GetLastError()
                print(f"[GameInterface] Pipe '{PIPE_NAME}' not available after {timeout_ms}ms. Error: {error_code}")
                return False

            # Attempt to open the pipe
            self.pipe_handle = CreateFileW(
                pipe_name_lpcwstr,
                GENERIC_READ | GENERIC_WRITE,
                0, # No sharing
                None, # Default security attributes
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None # No template file
            )

            if self.pipe_handle == INVALID_HANDLE_VALUE:
                error_code = GetLastError()
                print(f"[GameInterface] Failed to connect to pipe '{PIPE_NAME}'. Error: {error_code}")
                self.pipe_handle = None # Ensure handle is None on failure
                return False
            else:
                print(f"[GameInterface] Successfully connected to pipe '{PIPE_NAME}'.")
                return True

        except Exception as e:
            print(f"[GameInterface] Exception during pipe connection: {e}")
            self.pipe_handle = None
            return False

    def disconnect_pipe(self):
        """Disconnects from the named pipe."""
        if self.is_ready():
            try:
                CloseHandle(self.pipe_handle)
                print("[GameInterface] Pipe disconnected.")
            except Exception as e:
                print(f"[GameInterface] Exception during pipe disconnection: {e}")
            finally:
                self.pipe_handle = None
        else:
            print("[GameInterface] Pipe already disconnected.")


    def send_command(self, command: str) -> bool:
        """Sends a command string to the DLL via the pipe."""
        if not self.is_ready():
            print("[GameInterface] Cannot send command: Pipe not connected.")
            return False

        try:
            command_bytes = command.encode('utf-8') # Ensure UTF-8 encoding
            bytes_to_write = len(command_bytes)
            bytes_written = wintypes.DWORD(0)

            success = WriteFile(
                self.pipe_handle,
                command_bytes,
                bytes_to_write,
                ctypes.byref(bytes_written),
                None # Not overlapped
            )

            if not success or bytes_written.value != bytes_to_write:
                error_code = GetLastError()
                print(f"[GameInterface] Failed to write command to pipe. Success: {success}, Written: {bytes_written.value}/{bytes_to_write}, Error: {error_code}")
                self.disconnect_pipe() # Disconnect on error
                return False
            
            # print(f"[GameInterface] Sent: {command}") # Debug print
            return True

        except Exception as e:
            print(f"[GameInterface] Exception during send_command: {e}")
            self.disconnect_pipe() # Disconnect on error
            return False

    def receive_response(self, buffer_size: int = PIPE_BUFFER_SIZE, timeout_s: float = 5.0) -> Optional[str]:
        """Receives a response string from the DLL via the pipe. (Blocking with simple timeout)"""
        if not self.is_ready():
            # print("[GameInterface] Cannot receive response: Pipe not connected.") # Reduce log spam
            return None

        # NOTE: Implementing robust non-blocking reads or using PeekNamedPipe is more complex.
        # This is a simpler blocking read with a basic timeout mechanism.
        # It assumes the DLL sends responses terminated appropriately or within the buffer size.
        
        buffer = ctypes.create_string_buffer(buffer_size)
        bytes_read = wintypes.DWORD(0)
        start_time = time.time() # Timeout for the *entire* receive attempt, including potential loops later

        # --- Simplified Blocking Read ---
        # Windows ReadFile on pipes can block. We rely on the DLL sending data.
        # A more robust solution would involve overlapped I/O or PeekNamedPipe.
        # We'll implement the retry/matching logic in send_receive. This function
        # just attempts one blocking read. The timeout needs careful consideration.
        # For now, keep the basic ReadFile call.
        try:
            # print(f"[GameInterface] Attempting ReadFile (timeout={timeout_s:.1f}s)...") # Debug
            # NOTE: ReadFile itself doesn't have a direct timeout parameter in this non-overlapped usage.
            # The timeout check happens *after* it returns or fails.
            success = ReadFile(
                self.pipe_handle,
                buffer,
                buffer_size - 1, # Leave space for null terminator
                ctypes.byref(bytes_read),
                None # Not overlapped
            )
            
            # Check if the *call itself* seems to have taken too long, even if it eventually succeeded.
            # This isn't a true functional timeout but can indicate delays.
            if time.time() - start_time > timeout_s:
                 # This might happen if ReadFile was blocked for a long time
                 print(f"[GameInterface] Warning: ReadFile call took longer than timeout ({timeout_s}s).")

            if not success or bytes_read.value == 0:
                error_code = GetLastError()
                # Don't log broken pipe frequently, it's expected on disconnect
                if error_code not in [109]: # ERROR_BROKEN_PIPE
                     print(f"[GameInterface] ReadFile failed. Success: {success}, Read: {bytes_read.value}, Error: {error_code}")
                # else:
                #     print("[GameInterface] Pipe broken during receive.") # Debug log for disconnect
                self.disconnect_pipe() # Disconnect on error/broken pipe
                return None

            # Null-terminate the received data just in case
            buffer[bytes_read.value] = b'\0'
            # Decode using utf-8, replace errors to avoid crashes on malformed data
            response = buffer.value.decode('utf-8', errors='replace').strip() # Strip whitespace
            # print(f"[GameInterface] Raw Read: '{response}'") # Debug print raw value
            return response

        except Exception as e:
            print(f"[GameInterface] Exception during receive_response: {e}")
            self.disconnect_pipe() # Disconnect on error
            return None


    def send_receive(self, command: str, timeout_s: float = 5.0) -> Optional[str]:
        """Sends a command and waits for the *correct* response, discarding mismatches."""
        if not self.is_ready():
            print("[GameInterface] Cannot send/receive: Pipe not connected.")
            return None

        # Determine expected response prefix based on command
        expected_prefix = None
        if command == "ping": expected_prefix = "PONG"
        elif command == "GET_TIME_MS": expected_prefix = "TIME:"
        elif command.startswith("GET_CD:"): expected_prefix = "CD:" # Covers CD: and CD_ERR:
        elif command.startswith("GET_RANGE:"): expected_prefix = "RANGE:"
        elif command.startswith("IS_IN_RANGE:"): expected_prefix = "IN_RANGE:" # Covers IN_RANGE: and RANGE_ERR:
        elif command.startswith("GET_SPELL_INFO:"): expected_prefix = "SPELLINFO:" # Covers SPELLINFO: and SPELLINFO_ERR:
        elif command.startswith("CAST_SPELL:"): expected_prefix = "CAST_" # Covers CAST_SENT: and CAST_ERR:
        # EXEC_LUA currently doesn't expect a specific response format, handle separately if needed

        if not expected_prefix and not command.startswith("EXEC_LUA:"):
            print(f"[GameInterface] Warning: Unknown command format for send_receive: {command}")
            # Proceed but might fail if DLL sends unexpected response

        # Send the command first
        if not self.send_command(command):
            return None # Send failed

        start_time = time.time()
        attempts = 0
        max_attempts = 10 # Limit attempts to prevent infinite loops

        while time.time() - start_time < timeout_s and attempts < max_attempts:
            attempts += 1
            # Use a shorter internal timeout for each ReadFile attempt within the loop
            # This allows quicker checking for subsequent messages if the first is wrong.
            response = self.receive_response(timeout_s=max(0.1, timeout_s / max_attempts))

            if response is not None:
                # Check if the received response matches the expected type
                if expected_prefix and response.startswith(expected_prefix):
                    # print(f"[GameInterface] Received expected response for '{command}': '{response}'") # Debug success
                    return response # Found the correct response
                # Handle EXEC_LUA which might not have a standard response or prefix
                elif command.startswith("EXEC_LUA:"):
                     # Currently, EXEC_LUA doesn't expect a reply. If it reads *anything*,
                     # it's likely a leftover response. We should probably just return None or True
                     # after sending, but if we *do* read something, log it and discard.
                     print(f"[GameInterface] Warning: Received unexpected response after EXEC_LUA: '{response}'. Discarding.")
                     # Continue loop to potentially clear buffer or hit timeout/max_attempts
                else:
                    # Received something, but it's not what we expected for this command
                    print(f"[GameInterface] Warning: Received unexpected response '{response}' while waiting for '{expected_prefix}' (Command: '{command}'). Discarding.")
                    # Continue the loop to try reading again
            else:
                # receive_response returned None (timeout or error/disconnect)
                if not self.is_ready():
                    print("[GameInterface] Pipe disconnected during receive loop.")
                    return None # Pipe broke, exit
                # If receive_response timed out on this attempt, continue loop until overall timeout
                # print(f"[GameInterface] receive_response returned None (attempt {attempts}). Continuing loop.") # Debug

            # Optional small delay to prevent tight spinning if receive_response returns None quickly
            # time.sleep(0.01)

        # Loop finished due to timeout or max attempts
        if expected_prefix:
            print(f"[GameInterface] Timeout or max attempts reached waiting for '{expected_prefix}' response to command '{command}'.")
        else:
            print(f"[GameInterface] Timeout or max attempts reached after command '{command}'.")
        return None

    # --- High-Level Actions (To be adapted for IPC) ---

    def execute(self, lua_code: str, source_name: str = "PyWoWExec") -> bool:
        """
        Sends Lua code to the injected DLL for execution on the main thread.
        Uses a specific command format, e.g., "EXEC_LUA:<lua_code_here>"
        Returns True if the command was sent successfully, False otherwise.
        (Actual execution success determined by DLL/response if needed)
        """
        if not self.is_ready():
            print("[GameInterface] Cannot execute Lua: Pipe not connected.")
            return False
        if not lua_code:
            print("[GameInterface] Warning: Empty Lua code provided to execute().")
            return False

        # Format the command for the DLL
        # Using a simple prefix convention. More robust might be JSON etc.
        command = f"EXEC_LUA:{lua_code}" 
        
        # Send the command - Fire and forget for now
        # Could adapt to use send_receive if DLL sends back success/failure
        success = self.send_command(command)
        if not success:
             print(f"[GameInterface] Failed to send EXEC_LUA command for code: {lua_code[:50]}...")
        return success


    def ping_dll(self) -> bool:
        """Sends a 'ping' command to the DLL and checks for a valid response."""
        print("[GameInterface] Sending ping...")
        response = self.send_receive("ping", timeout_s=2.0)
        if response:
            print(f"[GameInterface] Ping response: '{response}'")
            # Check if response indicates success (e.g., contains "pong" or "Received: ping")
            # Let's standardize on a simple "PONG" response from DLL
            return response is not None and "PONG" in response.upper() 
        else:
            print("[GameInterface] No response to ping.")
            return False
            
    # --- Placeholder Methods (Adapt later for specific commands) ---

    def get_spell_cooldown(self, spell_id: int) -> Optional[dict]:
        """
        Gets spell cooldown information by sending a command to the DLL.
        Uses the game's internal GetSpellCooldown via Lua.
        Command: "GET_CD:<spell_id>"
        Response: "CD:<start_ms>,<duration_ms>,<enabled_int>" (enabled_int=1 if usable, 0 if on CD)
                   or "CD_ERR:Not found" or similar on failure.
        """
        command = f"GET_CD:{spell_id}"
        response = self.send_receive(command, timeout_s=1.0) # Faster timeout for frequent calls

        if response and response.startswith("CD:"):
            try:
                parts = response.split(':')[1].split(',')
                if len(parts) == 3:
                    start_ms = int(parts[0])
                    duration_ms = int(parts[1])
                    # Lua GetSpellCooldown returns 'enabled' (1 if usable/ready, nil/0 if not)
                    # Our DLL maps this to 1 or 0. We will recalculate readiness below.
                    # lua_enabled_int = int(parts[2]) # We don't strictly need this anymore

                    is_ready = True # Assume ready unless proven otherwise
                    remaining_ms = 0

                    # Fetch current game time - crucial for calculation
                    current_game_time_ms = self.get_game_time_millis()

                    if current_game_time_ms is None:
                        print("[GameInterface] Warning: Could not get current game time for cooldown calculation. Assuming not ready.")
                        # If we can't get time, we can't reliably check cooldown.
                        # Default to 'not ready' if duration/start indicate it *might* be on CD.
                        is_ready = not (duration_ms > 0 and start_ms > 0) # Guess based on non-zero values
                        remaining_ms = -1 # Indicate unknown remaining time
                    elif duration_ms > 0 and start_ms > 0:
                        # Only calculate if duration and start time suggest a cooldown is active
                        end_time_ms = start_ms + duration_ms
                        if current_game_time_ms < end_time_ms:
                            is_ready = False
                            remaining_ms = end_time_ms - current_game_time_ms
                        else:
                            is_ready = True # Cooldown finished
                            remaining_ms = 0
                    # else: # If duration is 0 or start_ms is 0, it's ready
                         # is_ready remains True, remaining_ms remains 0

                    return {
                        "startTime": start_ms / 1000.0, # Seconds
                        "duration": duration_ms,        # Milliseconds
                        "isReady": is_ready,            # Calculated readiness
                        "remaining": remaining_ms / 1000.0 if remaining_ms >= 0 else -1.0 # Seconds or -1
                    }
                else:
                    print(f"[GameInterface] Invalid CD response format: {response}")
            except (ValueError, IndexError, TypeError) as e:
                print(f"[GameInterface] Error parsing CD response '{response}': {e}")
        elif response and response.startswith("CD_ERR"):
            # print(f"[GameInterface] Cooldown query for {spell_id} failed: {response}") # Debug
            pass # Silently fail if DLL reports error
        # else: # Reduce spam for non-responses or timeouts
             # print(f"[GameInterface] Failed to get cooldown for {spell_id} or invalid/no response: {response}")
        return None

    def get_spell_range(self, spell_id: int) -> Optional[dict]:
        """
        Gets spell range by sending a command to the DLL.
        Example command: "GET_RANGE:<spell_id>"
        DLL should respond with formatted data (e.g., "RANGE:<min>,<max>")
        """
        command = f"GET_RANGE:{spell_id}"
        response = self.send_receive(command)
        if response and response.startswith("RANGE:"):
            try:
                 parts = response.split(':')[1].split(',')
                 if len(parts) == 2:
                      min_range = float(parts[0])
                      max_range = float(parts[1])
                      return {"minRange": min_range, "maxRange": max_range}
                 else:
                      print(f"[GameInterface] Invalid RANGE response format: {response}")
            except (ValueError, IndexError) as e:
                 print(f"[GameInterface] Error parsing RANGE response '{response}': {e}")
        else:
             print(f"[GameInterface] Failed to get range for {spell_id} or invalid response: {response}")
        return None

    def is_spell_in_range(self, spell_id: int, target_unit_id: str = "target") -> Optional[int]:
        """
        Checks spell range by sending a command to the DLL.
        Example command: "IS_IN_RANGE:<spell_id>,<unit_id>"
        DLL should respond with "IN_RANGE:0" or "IN_RANGE:1"
        """
        command = f"IS_IN_RANGE:{spell_id},{target_unit_id}"
        response = self.send_receive(command)
        if response and response.startswith("IN_RANGE:"):
             try:
                 result = int(response.split(':')[1])
                 return result # Should be 0 or 1
             except (ValueError, IndexError) as e:
                 print(f"[GameInterface] Error parsing IS_IN_RANGE response '{response}': {e}")
        else:
             print(f"[GameInterface] Failed to check range for {spell_id} or invalid response: {response}")
        return None

    # --- ADDED: Get Spell Info via IPC ---
    def get_spell_info(self, spell_id: int) -> Optional[dict]:
        """
        Gets spell details (name, rank, cast time, range, icon) using the GET_SPELL_INFO IPC command.
        Command: "GET_SPELL_INFO:<spell_id>"
        Response: "SPELLINFO:<name>,<rank>,<castTime_ms>,<minRange>,<maxRange>,<icon>,<cost>,<powerType>"
                  or "SPELLINFO_ERR:<message>"
        """
        command = f"GET_SPELL_INFO:{spell_id}"
        response = self.send_receive(command, timeout_s=1.0) # Use a reasonable timeout

        if response and response.startswith("SPELLINFO:"):
            try:
                # Split the part after "SPELLINFO:"
                parts = response.split(':', 1)[1].split(',')
                if len(parts) == 8: # Expect 8 parts now
                    name = parts[0] if parts[0] != "N/A" else None
                    rank = parts[1] if parts[1] != "N/A" else None
                    cast_time_ms = float(parts[2])
                    min_range = float(parts[3])
                    max_range = float(parts[4])
                    icon = parts[5] if parts[5] != "N/A" else None
                    cost = float(parts[6]) # Cost
                    power_type = int(parts[7]) # Power Type ID

                    return {
                        "name": name,
                        "rank": rank,
                        "castTime": cast_time_ms, # Keep as ms
                        "minRange": min_range,
                        "maxRange": max_range,
                        "icon": icon,
                        "cost": cost,
                        "powerType": power_type
                    }
                else:
                    print(f"[GameInterface] Invalid SPELLINFO response format (expected 8 parts, got {len(parts)}): {response}")
            except (ValueError, IndexError, TypeError) as e:
                print(f"[GameInterface] Error parsing SPELLINFO response '{response}': {e}")
        elif response and response.startswith("SPELLINFO_ERR"):
            # print(f"[GameInterface] Spell info query for {spell_id} failed: {response}") # Debug
            pass # Silently fail if DLL reports error
        # else: # Reduce spam
        #     print(f"[GameInterface] Failed to get spell info for {spell_id} or invalid/no response: {response}")
        return None

    # --- Add method to get game time --- 
    def get_game_time_millis(self) -> Optional[int]:
        """
        Gets the current in-game time in milliseconds by sending a GET_TIME_MS command.
        DLL should respond with "TIME:<milliseconds>"
        """
        command = "GET_TIME_MS"
        response = self.send_receive(command, timeout_s=0.5) # Use short timeout for time
        if response and response.startswith("TIME:"):
            try:
                time_str = response.split(':')[1]
                game_time_ms = int(time_str)
                return game_time_ms
            except (ValueError, IndexError, TypeError) as e:
                 print(f"[GameInterface] Error parsing GET_TIME_MS response '{response}': {e}")
        # else: # Reduce spam
            # print(f"[GameInterface] Failed to get game time ms or invalid response: {response}")
        return None

    # --- Deprecated get_game_time, use get_game_time_millis instead ---
    # def get_game_time(self) -> Optional[float]:
    #     """ Gets the current in-game time in seconds (float). DEPRECATED: Use get_game_time_millis."""
    #     ms = self.get_game_time_millis()
    #     return ms / 1000.0 if ms is not None else None

    # --- Removed old direct memory/shellcode functions ---
    # _allocate_memory, _free_memory, _write_memory, _read_memory
    # _execute_shellcode, call_lua_function, _read_lua_stack_string
    # _get_spell_cooldown_direct_legacy, _get_spell_range_direct_legacy
    # get_game_time_millis_direct, is_gcd_active (These might return later via IPC calls)

    def cast_spell(self, spell_id: int, target_guid: Optional[int] = None) -> bool:
        """
        Sends a command to the DLL to cast a spell using the internal C function.
        Command: "CAST_SPELL:<spell_id>[,<target_guid>]"
        Returns True if the command was sent successfully, False otherwise.
        (Does not guarantee the spell cast was successful in-game).
        """
        if not self.is_ready():
            print("[GameInterface] Cannot cast spell: Pipe not connected.")
            return False

        if target_guid:
            command = f"CAST_SPELL:{spell_id},{target_guid}"
        else:
            command = f"CAST_SPELL:{spell_id}" # No GUID, implies self-cast or current target handling by C func

        print(f"[GameInterface] Sending cast command: {command}") # Debug print
        success = self.send_command(command)
        if not success:
             print(f"[GameInterface] Failed to send CAST_SPELL command: {command}")
        # Optional: Could use send_receive here if we want to wait for "CAST_SENT"
        # response = self.send_receive(command, timeout_s=0.5)
        # return response is not None and response.startswith(f"CAST_SENT:{spell_id}")
        return success # Return based on send success for now

    # --- Example Usage (Test Function) ---
    def test_cast_spell(self, spell_id_to_test: int, target_guid_to_test: Optional[int] = None):
         print(f"\n--- Testing Cast Spell (Internal C Func) ---")
         if self.is_ready():
              target_desc = f"target GUID 0x{target_guid_to_test:X}" if target_guid_to_test else "default target (GUID 0)"
              print(f"Attempting to cast spell ID {spell_id_to_test} on {target_desc}...")
              if self.cast_spell(spell_id_to_test, target_guid_to_test):
                   print(f"CAST_SPELL command for {spell_id_to_test} sent successfully.")
              else:
                   print(f"Failed to send CAST_SPELL command for {spell_id_to_test}.")
              # Note: Add a small delay if testing repeatedly to see effect in game
              time.sleep(0.5)
         else:
              print("Skipping Cast Spell test: Pipe not connected.")


# --- Example Usage ---
if __name__ == "__main__":
    print("Attempting to initialize Game Interface (IPC)...")
    # MemoryHandler might still be needed for process finding or other tasks
    mem = MemoryHandler() 
    if mem.is_attached():
        game = GameInterface(mem)
        
        print("\n--- Testing Pipe Connection ---")
        if game.connect_pipe():
            print("Pipe connection successful.")
            
            print("\n--- Testing Ping ---")
            if game.ping_dll():
                 print("Ping successful!")
            else:
                 print("Ping failed.")

            print("\n--- Testing Lua Execute (Example) ---")
            # Send a simple print command
            lua_cmd = "print('Hello from Python via Injected DLL!')"
            if game.execute(lua_cmd):
                 print(f"Sent Lua command: {lua_cmd}")
                 # Note: We don't get direct output back from execute currently
            else:
                 print("Failed to send Lua command.")
                 
            print("\n--- Testing Get Cooldown (Example Spell ID) ---")
            test_spell_id_cd = 6673 # Redemption Rank 1 (Paladin) - Example with CD
            if game.is_ready(): # Only test if pipe connected
                cd_info = game.get_spell_cooldown(test_spell_id_cd)
                if cd_info:
                    status = "Ready" if cd_info['isReady'] else f"On Cooldown ({cd_info['remaining']:.1f}s left)"
                    print(f"Cooldown Info for {test_spell_id_cd}: Status={status}, Start={cd_info['startTime']}, Duration={cd_info['duration']}ms")
                else:
                    print(f"Failed to get cooldown info for {test_spell_id_cd} (or no response/error from DLL).")
            else:
                 print("Skipping Cooldown test: Pipe not connected.")

            print("\n--- Testing Get Range (Example Spell ID) ---")
            test_spell_id_range = 1752
            range_info = game.get_spell_range(test_spell_id_range)
            if range_info:
                print(f"Range Info for {test_spell_id_range}: {range_info}")
            else:
                print(f"Failed to get range info for {test_spell_id_range}.")

            print("\n--- Testing Is In Range (Example) ---")
            test_spell_id_range = 1752 # Holy Light Rank 1
            if game.is_ready(): # Only test if pipe connected
                is_in_range = game.is_spell_in_range(test_spell_id_range, "target")
                if is_in_range is not None:
                    # Simplify the f-string
                    status_str = 'Yes' if is_in_range == 1 else ('No' if is_in_range == 0 else 'Unknown')
                    print(f"Is Spell {test_spell_id_range} in range of 'target'? {status_str}")
                else:
                    print(f"Failed to check range for {test_spell_id_range} (or no response/error from DLL).")
            else:
                 print("Skipping Range Check test: Pipe not connected.")

            # --- Test Game Time ---
            print("\n--- Testing Get Game Time (Milliseconds) ---")
            if game.is_ready():
                gt_ms = game.get_game_time_millis()
                if gt_ms is not None:
                    print(f"Current Game Time: {gt_ms} ms ({gt_ms / 1000.0:.2f} s)")
                else:
                    print("Failed to get game time (or no response/error from DLL).")
            else:
                 print("Skipping Get Time test: Pipe not connected.")

            game.disconnect_pipe()
        else:
            print("Pipe connection failed.")
            
    else:
        print("Memory Handler failed to attach to WoW process.")