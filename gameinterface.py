import ctypes
from ctypes import wintypes
import time
import pymem # Keep for process finding? Maybe remove later if not needed.
import offsets # Keep for LUA_STATE and function addrs if needed by DLL
from memory import MemoryHandler # Keep if mem handler needed for other tasks
# from object_manager import ObjectManager # No longer needed directly here
from typing import Optional, List # Union, Any, List, Tuple - Removed unused

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
ERROR_BROKEN_PIPE = 109

# Kernel32 Functions needed for Pipes
kernel32 = ctypes.windll.kernel32
CreateFileW = kernel32.CreateFileW
WriteFile = kernel32.WriteFile
ReadFile = kernel32.ReadFile
CloseHandle = kernel32.CloseHandle
WaitNamedPipeW = kernel32.WaitNamedPipeW
GetLastError = kernel32.GetLastError
FlushFileBuffers = kernel32.FlushFileBuffers
PeekNamedPipe = kernel32.PeekNamedPipe

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
FlushFileBuffers.argtypes = [wintypes.HANDLE]
FlushFileBuffers.restype = wintypes.BOOL
PeekNamedPipe.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD)
]
PeekNamedPipe.restype = wintypes.BOOL


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


    def send_receive(self, command: str, timeout_ms: int = 10000) -> Optional[str]:
        """Sends a command and waits for a specific response prefix."""
        if not self.is_ready():
            print("[GameInterface] Cannot send command: Pipe not connected.")
            return None

        expected_prefix = None
        if command.startswith("GET_UNIT_INFO"):
            expected_prefix = "UNIT_INFO:"
        elif command.startswith("GET_PLAYER_INFO"):
            expected_prefix = "PLAYER_INFO:"
        elif command == "GET_TARGET_GUID":
            expected_prefix = "TARGET_GUID:"
        elif command.startswith("CAST_SPELL"):
            expected_prefix = "CAST_RESULT:"
        elif command.startswith("RUN_LUA"):
            expected_prefix = "LUA_RESULT:"
        elif command.startswith("GET_SPELL_INFO"):
            expected_prefix = "SPELL_INFO:"
        elif command == "GET_COMBO_POINTS":
            expected_prefix = "CP:"
        elif command == "GET_KNOWN_SPELLS":
             expected_prefix = "KNOWN_SPELLS:"
        elif command.startswith("EXEC_LUA:"):
            expected_prefix = "LUA_RESULT:"
        # Add other command prefixes here

        if expected_prefix is None:
            print(f"[GameInterface] Warning: No expected prefix defined for command: {command}")
            return None

        try:
            # Ensure pipe handle is valid
            if self.pipe_handle == INVALID_HANDLE_VALUE:
                print("[GameInterface] Warning: Pipe handle is invalid. Attempting reconnect...")
                self.connect_pipe() # Attempt to reconnect
                if not self.is_ready(): return None # Reconnect failed

            print(f"[GameInterface] Sending command: {command}")
            # Encode command with null terminator
            request = (command + '\0').encode('utf-8')
            # Send command
            bytes_written = wintypes.DWORD(0)
            success = WriteFile(
                self.pipe_handle,
                request,
                len(request),
                ctypes.byref(bytes_written),
                None # Not overlapped
            )
            if not success or bytes_written.value != len(request):
                error_code = GetLastError()
                print(f"[GameInterface] Failed to write command to pipe. Success: {success}, Written: {bytes_written.value}/{len(request)}, Error: {error_code}")
                self.disconnect_pipe() # Disconnect on error
                return None
            if not FlushFileBuffers(self.pipe_handle):
                 error_code = GetLastError()
                 print(f"[GameInterface] Warning: FlushFileBuffers failed after write. Error: {error_code}")
            print(f"[GameInterface] Sent {bytes_written.value} bytes.")

            # Receive response
            start_time = time.time()
            buffer = b""
            while True:
                last_error = 0 # Track last error
                try:
                    # Check time elapsed
                    if (time.time() - start_time) * 1000 > timeout_ms:
                        print(f"[GameInterface] Timeout waiting for response prefix '{expected_prefix}' for command '{command}'. Buffer: {buffer[:200]}")
                        self._clear_pipe_buffer() # Attempt to clear stale data
                        return None

                    # Peek at the pipe using kernel32.PeekNamedPipe
                    bytes_avail = wintypes.DWORD(0)
                    total_bytes_avail = wintypes.DWORD(0)
                    # bytes_left = wintypes.DWORD(0) # Not typically needed for byte stream pipes

                    # We only need to know if *any* bytes are available
                    peek_success = PeekNamedPipe(
                        self.pipe_handle,
                        None, # Don't read into buffer yet
                        0,    # Buffer size 0
                        ctypes.byref(bytes_avail), # Ptr to bytes read (usually 0)
                        ctypes.byref(total_bytes_avail), # Ptr to total bytes available
                        None # lpBytesLeftThisMessage (NULL)
                    )

                    if not peek_success:
                        last_error = GetLastError()
                        if last_error == ERROR_BROKEN_PIPE:
                            print("[GameInterface] Pipe broken during peek.")
                            self.disconnect_pipe()
                            return None
                        else:
                            print(f"[GameInterface] PeekNamedPipe failed. Error: {last_error}")
                            # Avoid tight loop on persistent peek error
                            time.sleep(0.1)
                            continue # Try peeking again after a delay

                    # Now check if total_bytes_avail > 0
                    if total_bytes_avail.value > 0:
                        # Read only available bytes (up to a limit to avoid huge reads)
                        read_size = min(total_bytes_avail.value, 4096)
                        read_buffer = ctypes.create_string_buffer(read_size)
                        bytes_actually_read = wintypes.DWORD(0)

                        read_success = ReadFile(
                            self.pipe_handle,
                            read_buffer,
                            read_size,
                            ctypes.byref(bytes_actually_read),
                            None
                        )

                        if not read_success or bytes_actually_read.value == 0:
                             last_error = GetLastError()
                             if last_error == ERROR_BROKEN_PIPE:
                                 print("[GameInterface] Pipe broken during read.")
                                 self.disconnect_pipe()
                                 return None
                             else:
                                 print(f"[GameInterface] ReadFile failed after peek indicated data. Error: {last_error}")
                                 # Possible race condition or other error, wait and retry loop
                                 time.sleep(0.05)
                                 continue

                        # Append successfully read data
                        buffer += read_buffer.raw[:bytes_actually_read.value]
                        print(f"[GameInterface] Read {bytes_actually_read.value} bytes, total buffer {len(buffer)} bytes.")

                        # Check if buffer contains the null terminator marking end of message
                        if b'\0' in buffer:
                            message, _, remaining_buffer = buffer.partition(b'\0')
                            decoded_message = message.decode('utf-8', errors='replace').strip()
                            print(f"[GameInterface] Received full message: [{decoded_message[:200]}...] (Remaining buffer: {len(remaining_buffer)} bytes)")

                            if decoded_message.startswith(expected_prefix):
                                return decoded_message # Success!
                            else:
                                # Log unexpected message and discard it
                                print(f"[GameInterface] Warning: Received unexpected response '{decoded_message[:100]}...' while waiting for '{expected_prefix}' (Command: '{command}'). Discarding.")
                                # Reset buffer to only contain the remaining part AFTER the null terminator
                                buffer = remaining_buffer
                                # Continue loop to wait for the correct message or timeout
                        # else: Null terminator not found yet, continue reading

                    else:
                        # No data available, wait briefly
                        time.sleep(0.01) # Small sleep to avoid busy-waiting

                except Exception as e:
                    # Catch other potential programming errors
                    print(f"[GameInterface] Unexpected Python error during pipe receive loop: {e}")
                    # Log the traceback for debugging
                    import traceback
                    traceback.print_exc()
                    self.disconnect_pipe()
                    return None

        except Exception as e:
            # Catch errors during send or initial setup
            print(f"[GameInterface] Error sending/receiving command '{command}': {e}")
            # Log the traceback for debugging
            import traceback
            traceback.print_exc()
            # Ensure pipe is disconnected if error occurred during send
            last_error = GetLastError() # Check if OS error code provides hint
            if last_error == ERROR_BROKEN_PIPE:
                 print("[GameInterface] Pipe likely broken during send attempt.")
                 self.disconnect_pipe()
            elif self.is_ready(): # If error wasn't pipe related, still disconnect? Maybe not.
                 # Consider if self.disconnect_pipe() should always happen here
                 pass
            return None

    def _clear_pipe_buffer(self):
        """Attempts to read any remaining data in the pipe to clear it after a timeout or error."""
        if not self.is_ready():
            return
        try:
            print("[GameInterface] Attempting to clear stale pipe buffer...")
            total_cleared = 0
            while True:
                bytes_avail = wintypes.DWORD(0)
                total_bytes_avail = wintypes.DWORD(0)
                peek_success = PeekNamedPipe(self.pipe_handle, None, 0, ctypes.byref(bytes_avail), ctypes.byref(total_bytes_avail), None)
                if not peek_success or total_bytes_avail.value == 0:
                    break # No more data or error peeking

                read_size = min(total_bytes_avail.value, 4096)
                read_buffer = ctypes.create_string_buffer(read_size)
                bytes_actually_read = wintypes.DWORD(0)
                read_success = ReadFile(self.pipe_handle, read_buffer, read_size, ctypes.byref(bytes_actually_read), None)

                if not read_success or bytes_actually_read.value == 0:
                    break # Error reading or no bytes read
                total_cleared += bytes_actually_read.value
            print(f"[GameInterface] Cleared approximately {total_cleared} bytes from pipe.")
        except Exception as e:
            print(f"[GameInterface] Error while clearing pipe buffer: {e}")
            self.disconnect_pipe() # Disconnect if clearing fails badly

    # --- High-Level Actions (To be adapted for IPC) ---

    def execute(self, lua_code: str, source_name: str = "PyWoWExec") -> Optional[List[str]]:
        """
        Sends Lua code to the injected DLL for execution on the main thread.
        Uses a specific command format, e.g., "EXEC_LUA:<lua_code_here>"
        Waits for a response (LUA_RESULT:...) and returns a list of result strings.
        """
        if not self.is_ready():
            print("[GameInterface] Cannot execute Lua: Pipe not connected.")
            return None # Return None for error/not ready
        if not lua_code:
            print("[GameInterface] Warning: Empty Lua code provided to execute().")
            return [] # Return empty list for empty code?

        # Format the command for the DLL
        command = f"EXEC_LUA:{lua_code}"

        # Use send_receive to wait for the result
        response = self.send_receive(command, timeout_ms=15000) # Allow longer timeout for Lua execution

        if response and response.startswith("LUA_RESULT:"):
            try:
                # Extract the comma-separated results after the prefix
                result_part = response.split(':', 1)[1]
                # Return an empty list if the result part is empty, otherwise split
                results = result_part.split(',') if result_part else []
                print(f"[GameInterface] Lua results received: {results}")
                return results
            except Exception as e:
                print(f"[GameInterface] Error parsing LUA_RESULT response '{response}': {e}")
                return None # Indicate parsing error
        elif response:
             print(f"[GameInterface] Unexpected response to EXEC_LUA: {response[:100]}...")
             return None # Indicate unexpected response
        else:
             print(f"[GameInterface] No or invalid response to EXEC_LUA command for code: {lua_code[:50]}...")
             return None # Indicate timeout or connection error


    def ping_dll(self) -> bool:
        """Sends a 'ping' command to the DLL and checks for a valid response."""
        print("[GameInterface] Sending ping...")
        response = self.send_receive("ping", timeout_ms=2000)
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
        response = self.send_receive(command, timeout_ms=1000) # Faster timeout for frequent calls

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
        response = self.send_receive(command, timeout_ms=1000) # Use a reasonable timeout

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
        response = self.send_receive(command, timeout_ms=500) # Use short timeout for time
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

    def get_combo_points(self) -> Optional[int]:
        """Retrieves the current combo points on the target via IPC."""
        response = self.send_receive("GET_COMBO_POINTS")
        if response and response.startswith("CP:"):
            try:
                # Extract the number after "CP:"
                cp_str = response.split(':')[1]
                combo_points = int(cp_str)
                print(f"[GameInterface] Received Combo Points: {combo_points}")
                # Handle negative values as errors/indicators from DLL
                if combo_points == -1:
                     print("[GameInterface] Warning: GetComboPoints Lua returned nil (No/Invalid Target?).")
                     return 0 # Return 0 to GUI, but log the warning
                elif combo_points < -1:
                     print(f"[GameInterface] DLL reported error fetching combo points (Code: {combo_points})")
                     return None # Indicate error to GUI
                return combo_points
            except (IndexError, ValueError) as e:
                print(f"[GameInterface] Failed to parse combo points from response '{response}': {e}")
                return None
        else:
            print(f"[GameInterface] Warning: Failed to get combo points or received invalid response: {response}")
            return None


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

            # --- Test Combo Points ---
            print("\n--- Testing Get Combo Points ---")
            if game.is_ready():
                 cp = game.get_combo_points()
                 if cp is not None:
                      print(f"Current Combo Points on Target: {cp}")
                 else:
                      print("Failed to get combo points (or no response/error from DLL).")
            else:
                 print("Skipping Get Combo Points test: Pipe not connected.")

            game.disconnect_pipe()
        else:
            print("Pipe connection failed.")
            
    else:
        print("Memory Handler failed to attach to WoW process.")