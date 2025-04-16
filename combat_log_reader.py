import time
import ctypes
import logging
from typing import Optional, Generator, Tuple, Any

import offsets
from memory import MemoryHandler
import pymem # For exceptions

logger = logging.getLogger(__name__)

# Tentative structure - size and field offsets need heavy verification
# class CombatLogEventArgs(ctypes.Structure):
#     _fields_ = [
#         # Guessed based on AppendCombatLogEntry stack pushes
#         ("sourceGUID_low", ctypes.c_uint32),
#         ("sourceGUID_high", ctypes.c_uint32),
#         ("destGUID_low", ctypes.c_uint32),
#         ("destGUID_high", ctypes.c_uint32),
#         ("eventTypeOrSpellID", ctypes.c_int32), # Event Type ID or Spell ID
#         ("param1", ctypes.c_int32), # Amount? SchoolMask?
#         ("param2", ctypes.c_int32), # Overkill? PowerType?
#         ("param3", ctypes.c_int32), # Resisted? ExtraSpellID?
#         ("param4", ctypes.c_int32), # Blocked? AuraType?
#         ("param5", ctypes.c_int32), # Absorbed?
#         ("param6", ctypes.c_int32), # Critical? Glancing? Crushing?
#         ("byteFlag1", ctypes.c_byte), # Derived flag?
#         ("_pad1", ctypes.c_byte * 3),
#         ("byteFlag2", ctypes.c_byte), # Derived flag?
#         ("_pad2", ctypes.c_byte * 3),
#         ("param7", ctypes.c_int32), # Extra param?
#         # ... potentially more fields ...
#     ]

class CombatLogReader:
    """Reads WoW Combat Log entries from memory."""

    def __init__(self, mem: MemoryHandler):
        self.mem = mem
        self.last_read_node_addr: int = 0
        self.initialized: bool = False
        self._initialize()

    def _initialize(self):
        """Initializes pointers and finds the starting point."""
        if not self.mem or not self.mem.is_attached():
            logger.error("CombatLogReader: Memory handler not attached.")
            return

        # Find the address of the *last* node currently in the list
        # We read the manager structure, then the tail pointer from it.
        try:
            manager_addr = offsets.COMBAT_LOG_LIST_MANAGER
            if not manager_addr:
                logger.error("CombatLogReader: COMBAT_LOG_LIST_MANAGER offset is zero.")
                return

            # Read the tail pointer (assuming offset 0x4 within manager struct)
            # WARNING: Offsets 0x0 and 0x4 need verification!
            tail_ptr_addr = manager_addr + offsets.COMBAT_LOG_LIST_TAIL_OFFSET
            self.last_read_node_addr = self.mem.read_uint(tail_ptr_addr)

            if self.last_read_node_addr == 0:
                logger.warning("CombatLogReader: Initial tail pointer is null. Will start reading from head on first update.")
                # If tail is 0, list might be empty, or head/tail logic is different.
                # We'll handle starting from head in read_new_entries if last_read is 0.
            else:
                logger.info(f"CombatLogReader: Initialized. Last known node: {self.last_read_node_addr:#x}")

            self.initialized = True

        except pymem.exception.MemoryReadError as e:
            logger.error(f"CombatLogReader: MemoryReadError during initialization: {e}")
            self.initialized = False
        except Exception as e:
            logger.exception(f"CombatLogReader: Unexpected error during initialization: {e}")
            self.initialized = False

    def read_new_entries(self) -> Generator[Tuple[int, bytes], None, None]:
        """
        Reads new combat log entries since the last read.
        Yields tuples of (timestamp, raw_event_data_bytes).
        """
        if not self.initialized or not self.mem or not self.mem.is_attached():
            # print("CombatLogReader: Not initialized or memory detached.", file=sys.stderr) # Debug
            return # Don't yield anything if not ready

        current_node_addr = 0
        processed_count = 0
        max_process_per_tick = 200 # Safety limit

        try:
            if self.last_read_node_addr == 0:
                # List was empty or first run, try starting from head
                manager_addr = offsets.COMBAT_LOG_LIST_MANAGER
                head_ptr_addr = manager_addr + offsets.COMBAT_LOG_LIST_HEAD_OFFSET
                current_node_addr = self.mem.read_uint(head_ptr_addr)
                logger.info(f"CombatLogReader: Starting read from head: {current_node_addr:#x}")
            else:
                # Start from the node *after* the last one we read
                next_node_addr = self.mem.read_uint(self.last_read_node_addr + offsets.COMBAT_LOG_EVENT_NEXT_OFFSET)
                current_node_addr = next_node_addr
                # if current_node_addr != 0:
                #     logger.debug(f"CombatLogReader: Resuming read from {current_node_addr:#x}")

            while current_node_addr != 0 and current_node_addr % 2 == 0 and processed_count < max_process_per_tick:
                # Read timestamp/sequence
                timestamp = self.mem.read_uint(current_node_addr + offsets.COMBAT_LOG_EVENT_TIMESTAMP_OFFSET)

                # Read raw event data block
                event_data_addr = current_node_addr + offsets.COMBAT_LOG_EVENT_DATA_OFFSET
                raw_data = self.mem.read_bytes(event_data_addr, offsets.COMBAT_LOG_EVENT_DATA_SIZE)

                if raw_data:
                    yield (timestamp, raw_data)
                    processed_count += 1
                else:
                    logger.warning(f"CombatLogReader: Failed to read event data at {event_data_addr:#x} for node {current_node_addr:#x}")
                    # Decide whether to break or try next node
                    # break # Safer to stop if data read fails

                # Update last read node
                self.last_read_node_addr = current_node_addr

                # Move to next node
                current_node_addr = self.mem.read_uint(current_node_addr + offsets.COMBAT_LOG_EVENT_NEXT_OFFSET)

            # if processed_count > 0:
            #     logger.debug(f"CombatLogReader: Processed {processed_count} new entries.")
            if processed_count >= max_process_per_tick:
                 logger.warning(f"CombatLogReader: Hit processing limit ({max_process_per_tick}). Will continue next tick.")

        except pymem.exception.MemoryReadError as e:
            logger.error(f"CombatLogReader: MemoryReadError during update: {e} near node {current_node_addr:#x}")
            # Potentially reset last_read_node_addr or re-initialize?
            # For now, just stop reading for this tick.
            pass
        except Exception as e:
            logger.exception(f"CombatLogReader: Unexpected error during update: {e}")
            # Maybe reset state?
            pass 