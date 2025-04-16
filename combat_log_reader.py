import time
import ctypes
import logging
import traceback # Import traceback
from typing import Optional, Generator, Tuple, Any, TYPE_CHECKING

import offsets
from memory import MemoryHandler
import pymem # For exceptions

# Use TYPE_CHECKING to avoid circular imports during runtime
if TYPE_CHECKING:
    from gui import WowMonitorApp # Import from the main gui module

logger = logging.getLogger(__name__) # Keep logger for potential non-GUI use if needed

# Structure for the entire combat log node
# Based on AppendLinkedListNode, handle_combat_log_entry, handleCombatEvent analysis (2024-07-19)
class CombatLogEventNode(ctypes.Structure):
    _fields_ = [
        # --- Linked List Pointers (from AppendLinkedListNode) --- #
        # Offset +0x00: Pointer to Previous Node
        ("pPrev", ctypes.c_uint32),
        # Offset +0x04: Pointer to Next Node
        ("pNext", ctypes.c_uint32),

        # --- Timestamp (from handleCombatEvent) --- #
        # Offset +0x08:
        ("timestamp", ctypes.c_uint32),

        # --- Core Event Data (from handle_combat_log_entry) --- #
        # Offset +0x0C:
        ("event_type_id", ctypes.c_int32),
        # Offset +0x10:
        ("unknown_0x10", ctypes.c_uint32),
        # Offset +0x14:
        ("unknown_0x14", ctypes.c_uint32), # Often seems zero?
        # Offset +0x18: Source GUID Low
        ("source_guid_low", ctypes.c_uint32),
        # Offset +0x1C: Source GUID High
        ("source_guid_high", ctypes.c_uint32),
        # Offset +0x20: Source Flags?
        ("source_flags", ctypes.c_uint32),
        # Offset +0x24: Unknown/Padding?
        ("unknown_0x24", ctypes.c_uint32),
        # Offset +0x28: Source Raid Flags?
        ("source_raid_flags", ctypes.c_uint32),
        # Offset +0x2C: Unknown/Padding?
        ("unknown_0x2C", ctypes.c_uint32),
        # Offset +0x30: Dest GUID Low
        ("dest_guid_low", ctypes.c_uint32),
        # Offset +0x34: Dest GUID High
        ("dest_guid_high", ctypes.c_uint32),
        # Offset +0x38: Dest Flags?
        ("dest_flags", ctypes.c_uint32),
        # Offset +0x3C: Unknown/Padding?
        ("unknown_0x3C", ctypes.c_uint32),
        # Offset +0x40: Dest Raid Flags?
        ("dest_raid_flags", ctypes.c_uint32),
        # Offset +0x44: Owner GUID Low? (or Padding?)
        ("owner_guid_low", ctypes.c_uint32),
        # Offset +0x48: Owner GUID High? (or string hash ptr?)
        ("owner_guid_high_or_strptr", ctypes.c_uint32),
        # Offset +0x4C: Unknown/Padding?
        ("unknown_0x4C", ctypes.c_uint32),
        # Offset +0x50: Unknown/Padding?
        ("unknown_0x50", ctypes.c_uint32),
        # Offset +0x54: Unknown/Padding?
        ("unknown_0x54", ctypes.c_uint32),
        # Offset +0x58: Unknown/Padding?
        ("unknown_0x58", ctypes.c_uint32),

        # --- Parameters (Mapping Attempt 5 - Based strictly on ACLE->HCE trace) --- #
        # NOTE: SpellID location is UNKNOWN from this trace.
        # Offset +0x5C: (HCE arg_8 <- ACLE arg_C <- Packet Amount)
        ("amount", ctypes.c_int32),             # Primary Amount (Damage/Heal/Energize?)
        # Offset +0x60: (HCE arg_C <- ACLE arg_10 <- Packet Overkill)
        ("overkill_or_power_type", ctypes.c_int32), # Overkill/Overheal OR Power Type?
        # Offset +0x64: (HCE arg_10 <- ACLE arg_14 <- Packet School Mask)
        ("school_mask", ctypes.c_int32),       # School Mask (Seems reliable for Damage)
        # Offset +0x68: (HCE arg_1C <- ACLE arg_20 <- Packet Absorb)
        ("absorbed", ctypes.c_int32),          # Absorbed amount
        # Offset +0x6C: (HCE arg_14 <- ACLE arg_1C <- Packet Resist)
        ("resisted", ctypes.c_int32),          # Resisted amount
        # Offset +0x70: (HCE arg_18 <- ACLE arg_18 <- Packet Block/Miss)
        ("blocked_or_miss_type", ctypes.c_int32), # Blocked amount OR Miss Type
        # Offset +0x74: (HCE flags <- ACLE arg_24 derived -> Bit 0)
        ("flags", ctypes.c_uint32),             # Bit 0: Crit, Bit 1/2: TBD (Glance/Crush?)

        # Total size currently: 0x74 + 4 = 0x78 bytes (120 bytes)
        # Might need padding or more fields if structure is larger aligned.
    ]
    _pack_ = 1 # Important for memory alignment

class CombatLogReader:
    """Reads WoW Combat Log entries from memory."""

    def __init__(self, mem: MemoryHandler, app_instance: 'WowMonitorApp'):
        self.mem = mem
        self.app = app_instance # Store app instance for logging
        self.last_read_node_addr: int = 0
        self.initialized: bool = False
        self._initialize()

    def _initialize(self):
        """Initializes pointers and finds the starting point."""
        log_prefix = "CombatLogReader Init:"
        if not self.mem or not self.mem.is_attached():
            # log_func = self.app.log_message if hasattr(self.app, 'log_message') else print
            # log_func(f"{log_prefix} Memory handler not attached.", "ERROR")
            return

        try:
            manager_addr = offsets.COMBAT_LOG_LIST_MANAGER
            if not manager_addr:
                # self.app.log_message(f"{log_prefix} COMBAT_LOG_LIST_MANAGER offset is zero.", "ERROR")
                return

            # Read the tail pointer using the correct offset
            tail_ptr_addr = manager_addr + offsets.COMBAT_LOG_LIST_TAIL_OFFSET
            self.last_read_node_addr = self.mem.read_uint(tail_ptr_addr)

            if self.last_read_node_addr == 0:
                # self.app.log_message(f"{log_prefix} Initial tail pointer is null. Will start reading from head on first update.", "WARN")
                pass # Explicitly pass
            else:
                # self.app.log_message(f"{log_prefix} Initialized. Last known node: {self.last_read_node_addr:#x}", "INFO")
                pass # Explicitly pass

            self.initialized = True

        except pymem.exception.MemoryReadError as e:
            # self.app.log_message(f"{log_prefix} MemoryReadError: {e}", "ERROR")
            self.initialized = False
        except Exception as e:
            tb_str = traceback.format_exc()
            # self.app.log_message(f"{log_prefix} Unexpected error: {e}\n{tb_str}", "ERROR")
            self.initialized = False

    def read_new_entries(self) -> Generator[Tuple[int, CombatLogEventNode], None, None]: # Return the full node
        """
        Reads new combat log entries since the last read by tracking the tail pointer.
        Yields tuples of (timestamp, event_node_structure).
        """
        # logger.debug("--- read_new_entries called ---") # Commented out
        if not self.initialized or not self.mem or not self.mem.is_attached():
            # logger.debug("Reader not initialized or memory detached. Returning.") # Commented out
            return

        current_node_addr = 0
        target_tail_node_addr = 0
        processed_count = 0
        max_process_per_tick = 200 # Safety limit

        try:
            # --- Get the manager address (No longer assumes it might be a pointer) ---
            manager_addr = offsets.COMBAT_LOG_LIST_MANAGER
            # logger.debug(f"Using Manager Base Address: {manager_addr:#x}") # Commented out

            # --- Get the current head and tail pointers using the correct offsets --- #
            head_ptr_addr = manager_addr + offsets.COMBAT_LOG_LIST_HEAD_OFFSET
            tail_ptr_addr = manager_addr + offsets.COMBAT_LOG_LIST_TAIL_OFFSET
            current_head_node_addr = self.mem.read_uint(head_ptr_addr)
            target_tail_node_addr = self.mem.read_uint(tail_ptr_addr)
            # logger.debug(f"Read Head: {current_head_node_addr:#x}, Tail: {target_tail_node_addr:#x}, LastRead: {self.last_read_node_addr:#x}") # Commented out

            # --- Determine starting point --- #
            if target_tail_node_addr == 0:
                # logger.debug("Tail pointer is null, list might be empty. Returning.") # Commented out
                return

            if self.last_read_node_addr == 0:
                current_node_addr = current_head_node_addr
                # logger.debug(f"Starting read from head: {current_node_addr:#x}") # Commented out
            else:
                try:
                    # Read the 'next' pointer using the correct offset (0x4)
                    # logger.debug(f"Attempting to read next pointer from last_read_node: {self.last_read_node_addr:#x} + offset {offsets.COMBAT_LOG_EVENT_NEXT_OFFSET}") # Commented out
                    next_node_addr_check = self.mem.read_uint(self.last_read_node_addr + offsets.COMBAT_LOG_EVENT_NEXT_OFFSET)
                    # logger.debug(f"Read next pointer: {next_node_addr_check:#x}") # Commented out

                    if self.last_read_node_addr == target_tail_node_addr:
                        # logger.debug("Last read was already the target tail, no new entries likely. Returning.") # Commented out
                        return
                    current_node_addr = next_node_addr_check
                    # logger.debug(f"Resuming read from node after last read: {current_node_addr:#x}") # Commented out
                except pymem.exception.MemoryReadError:
                    logger.warning(f"Failed to read next from last node {self.last_read_node_addr:#x}. Resyncing from head.")
                    current_node_addr = current_head_node_addr
                    self.last_read_node_addr = 0

            if current_node_addr == 0:
                 # logger.debug(f"Calculated start node is null (last_read={self.last_read_node_addr:#x}, target_tail={target_tail_node_addr:#x}). Returning.") # Commented out
                 return

            # logger.debug(f"Starting iteration loop with current_node_addr: {current_node_addr:#x}") # Commented out
            # --- Iterate until we reach the current tail --- #
            while current_node_addr != 0 and current_node_addr % 2 == 0 and processed_count < max_process_per_tick:
                # logger.debug(f"Looping: Processing node {current_node_addr:#x}") # Commented out
                node_to_process = current_node_addr

                # --- Read Data (Read the entire node structure) ---
                node_size = ctypes.sizeof(CombatLogEventNode)
                raw_data = self.mem.read_bytes(node_to_process, node_size)

                if raw_data and len(raw_data) == node_size:
                    try:
                        event_struct = CombatLogEventNode.from_buffer_copy(raw_data)
                        # Yield timestamp from struct and the struct itself
                        # logger.debug(f"Yielding event from node {node_to_process:#x}, Timestamp: {event_struct.timestamp}") # Commented out
                        yield (event_struct.timestamp, event_struct)
                        processed_count += 1
                    except Exception as cast_err:
                        logger.error(f"Failed to cast event data for node {node_to_process:#x}: {cast_err}")
                        # Attempt to read next node even on cast error
                        pass
                else:
                    log_msg = f"Failed to read event data for node {node_to_process:#x}"
                    if raw_data is not None:
                        log_msg += f" (Read {len(raw_data)} bytes, expected {node_size})"
                    logger.warning(log_msg)
                    # Don't break immediately, try to get next node first
                    pass

                # --- Update last read node --- #
                self.last_read_node_addr = node_to_process
                # logger.debug(f"Updated last_read_node_addr to: {self.last_read_node_addr:#x}") # Commented out

                # --- Check if we just processed the target tail --- #
                if node_to_process == target_tail_node_addr:
                    # logger.debug(f"Reached target tail node {target_tail_node_addr:#x}. Breaking loop.") # Commented out
                    break

                # --- Move to next node using the correct offset (0x4) from the struct --- #
                # Need to read the raw pointer first before accessing the potentially invalid struct
                try:
                    next_node_addr = self.mem.read_uint(node_to_process + offsets.COMBAT_LOG_EVENT_NEXT_OFFSET)
                    # logger.debug(f"Moving to next node: {next_node_addr:#x}") # Commented out
                    current_node_addr = next_node_addr
                except pymem.exception.MemoryReadError as read_next_err:
                    logger.error(f"Failed to read next node pointer from {node_to_process:#x}: {read_next_err}. Breaking loop.")
                    self.last_read_node_addr = 0 # Reset on error
                    break # Cannot continue if next pointer is unreadable

                # --- Sanity check for infinite loops --- #
                if current_node_addr == node_to_process:
                    logger.error(f"Detected loop (next node is same as current: {current_node_addr:#x}). Breaking.")
                    self.last_read_node_addr = 0 # Reset on error
                    break

            # --- Post-loop logging --- #
            # logger.debug(f"Exited loop. Processed count: {processed_count}") # Commented out
            if processed_count >= max_process_per_tick:
                 logger.warning(f"Hit combat log processing limit ({max_process_per_tick}). Some events might be delayed.") # Change to Warning
                 pass

        except pymem.exception.MemoryReadError as e:
            logger.error(f"MemoryReadError during update: {e} near node {current_node_addr:#x} (target tail: {target_tail_node_addr:#x})")
            self.last_read_node_addr = 0 # Reset on error to force resync
        except Exception as e:
            tb_str = traceback.format_exc()
            logger.error(f"Unexpected error during update: {e}\n{tb_str}")
            self.last_read_node_addr = 0 # Reset on error

        # logger.debug("--- read_new_entries finished ---") # Commented out 