import pymem
import pymem.process
import time
import offsets # Import offsets to use STATIC_CLIENT_CONNECTION etc. in example

PROCESS_NAME = "Wow.exe" # Adjust if your executable name is different

class MemoryHandler:
    def __init__(self):
        self.pm = None
        self.base_address = None
        try:
            self.pm = pymem.Pymem(PROCESS_NAME)
            # Note: process.module_from_name finds the module based on the process name.
            # For WoW.exe, this usually gives the correct base address.
            self.base_address = pymem.process.module_from_name(self.pm.process_handle, PROCESS_NAME).lpBaseOfDll
            print(f"Successfully attached to {PROCESS_NAME} (PID: {self.pm.process_id})")
            print(f"Base address: {hex(self.base_address)}")
        except pymem.exception.ProcessNotFound:
            print(f"Error: Process '{PROCESS_NAME}' not found. Is WoW running?")
            self.pm = None
        except Exception as e:
            print(f"An unexpected error occurred during attachment: {e}")
            self.pm = None

    def is_attached(self):
        """Check if successfully attached to the process."""
        # Pymem methods will raise exceptions if the handle is invalid or process closed.
        # A simple check if self.pm exists is sufficient here.
        return bool(self.pm)

    def read_uint(self, address):
        if not self.is_attached(): return 0
        try:
            return self.pm.read_uint(address)
        except pymem.exception.MemoryReadError: return 0 # Common error, return default
        except Exception as e:
            # print(f"Error reading uint at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0

    def read_ulonglong(self, address):
        if not self.is_attached(): return 0
        try:
            return self.pm.read_ulonglong(address)
        except pymem.exception.MemoryReadError: return 0
        except Exception as e:
            # print(f"Error reading ulonglong at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0

    def read_float(self, address):
        if not self.is_attached(): return 0.0
        try:
            return self.pm.read_float(address)
        except pymem.exception.MemoryReadError: return 0.0
        except Exception as e:
            # print(f"Error reading float at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0.0

    def read_double(self, address):
        """Reads an 8-byte double-precision floating point number."""
        if not self.is_attached(): return 0.0
        try:
            return self.pm.read_double(address)
        except pymem.exception.MemoryReadError: return 0.0
        except Exception as e:
            # print(f"Error reading double at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0.0

    def read_short(self, address):
        """Reads a signed short (2 bytes)."""
        if not self.is_attached(): return 0
        try:
            byte_data = self.pm.read_bytes(address, 2)
            return int.from_bytes(byte_data, byteorder='little', signed=True)
        except pymem.exception.MemoryReadError: return 0
        except Exception as e:
            # print(f"Error reading short at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0

    def read_ushort(self, address):
        """Reads an unsigned short (2 bytes)."""
        if not self.is_attached(): return 0
        try:
            byte_data = self.pm.read_bytes(address, 2)
            return int.from_bytes(byte_data, byteorder='little', signed=False)
        except pymem.exception.MemoryReadError: return 0
        except Exception as e:
            # print(f"Error reading ushort at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0

    def read_string(self, address, max_length=100, encoding='utf-8'):
        """Reads a null-terminated string from memory."""
        if not self.is_attached() or address == 0: return ""
        try:
            # Read bytes incrementally until null terminator or max_length
            buffer = bytearray()
            chunk_size = 32 # Read in chunks
            read_length = 0
            while read_length < max_length:
                 bytes_to_read = min(chunk_size, max_length - read_length)
                 chunk = self.pm.read_bytes(address + read_length, bytes_to_read)
                 if not chunk: break # Read failed

                 null_term_index = chunk.find(b'\x00')
                 if null_term_index != -1:
                      buffer.extend(chunk[:null_term_index])
                      break # Found null terminator
                 else:
                      buffer.extend(chunk)
                      read_length += len(chunk)
                      if len(chunk) < bytes_to_read: # Read less than requested, likely end of readable memory
                           break

            # Decode explicitly, ignoring errors
            return buffer.decode(encoding, errors='ignore')
        except pymem.exception.MemoryReadError:
             # print(f"MemoryReadError reading string at {hex(address)}") # Debug
             return ""
        except Exception as e:
            # print(f"Error reading string at {hex(address)}: {e}") # Optional: uncomment for debugging
            return ""

    def read_uchar(self, address):
        """Reads a single unsigned byte (uchar)."""
        if not self.is_attached(): return 0
        try:
            byte_data = self.pm.read_bytes(address, 1)
            return int.from_bytes(byte_data, byteorder='little', signed=False)
        except pymem.exception.MemoryReadError: return 0
        except Exception as e:
            # print(f"Error reading uchar at {hex(address)}: {e}") # Optional: uncomment for debugging
            return 0

    def read_bytes(self, address, length):
        """Reads a raw sequence of bytes."""
        if not self.is_attached(): return b''
        try:
            return self.pm.read_bytes(address, length)
        except pymem.exception.MemoryReadError: return b''
        except Exception as e:
            # print(f"Error reading bytes at {hex(address)}: {e}") # Optional: uncomment for debugging
            return b''

    # --- Write Methods ---
    def write_bytes(self, address, data: bytes):
        if not self.is_attached(): return False
        try:
            self.pm.write_bytes(address, data, len(data))
            return True
        except pymem.exception.MemoryWriteError as e:
            print(f"Error writing bytes at {hex(address)}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error writing bytes at {hex(address)}: {e}")
            return False

    def write_uint(self, address, value: int):
        if not self.is_attached(): return False
        try:
            self.pm.write_uint(address, value)
            return True
        except pymem.exception.MemoryWriteError as e:
            print(f"Error writing uint at {hex(address)}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error writing uint at {hex(address)}: {e}")
            return False

    def write_float(self, address, value: float):
        if not self.is_attached(): return False
        try:
            self.pm.write_float(address, value)
            return True
        except pymem.exception.MemoryWriteError as e:
            print(f"Error writing float at {hex(address)}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error writing float at {hex(address)}: {e}")
            return False

    def write_string(self, address, text: str, encoding='utf-8'):
        """Writes a string to memory, including null terminator."""
        if not self.is_attached(): return False
        try:
            byte_data = text.encode(encoding) + b'\0' # Add null terminator
            self.pm.write_bytes(address, byte_data, len(byte_data))
            return True
        except pymem.exception.MemoryWriteError as e:
            print(f"Error writing string at {hex(address)}: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error writing string at {hex(address)}: {e}")
            return False


# Example Usage (Optional - can be run if this file is executed directly)
if __name__ == "__main__":
    mem = MemoryHandler()
    if mem.is_attached():
        print("Memory handler initialized.")
        # Add test reads here if needed, e.g.:
        # Test reading client connection pointer value
        try: # Wrap in try/except as offsets might not be loaded if run directly
            cc_ptr_val = mem.read_uint(offsets.STATIC_CLIENT_CONNECTION)
            print(f"Value at STATIC_CLIENT_CONNECTION ({hex(offsets.STATIC_CLIENT_CONNECTION)}): {hex(cc_ptr_val)}")

            # Test reading Lua state pointer value
            lua_state_val = mem.read_uint(offsets.LUA_STATE)
            print(f"Value at LUA_STATE ({hex(offsets.LUA_STATE)}): {hex(lua_state_val)}")

            # Example Read String from a known location (if available)
            # known_string_addr = 0xSOME_ADDRESS # Replace with actual address
            # if known_string_addr:
            #     test_string = mem.read_string(known_string_addr, 50)
            #     print(f"String at {hex(known_string_addr)}: '{test_string}'")

        except NameError:
            print("Skipping offset tests (run main gui.py instead).")
        except Exception as e:
            print(f"Error during tests: {e}")


    else:
        print("Failed to initialize memory handler.")