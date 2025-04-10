import time
import offsets
from memory import MemoryHandler
from wow_object import WowObject
from typing import Optional, Generator, Dict, Set # Added Generator, Dict, Set
import pymem

class ObjectManager:
    """
    Handles interaction with the WoW Object Manager. Reads object data,
    manages a cache, and provides methods to access player, target,
    and other objects.
    """

    def __init__(self, mem_handler: MemoryHandler):
        self.mem = mem_handler
        self.client_connection: int = 0
        self.object_manager_base: int = 0
        self.first_object_address: int = 0
        self.local_player_guid: int = 0
        self.local_player: Optional[WowObject] = None
        self.target_guid: int = 0
        self.target: Optional[WowObject] = None
        self.object_cache: Dict[int, WowObject] = {} # Cache objects by GUID
        self.last_refresh_time: float = 0.0

        self._initialize_addresses()

    def _initialize_addresses(self):
        """Reads the core pointers needed to access the object manager."""
        if not self.mem or not self.mem.is_attached():
            print("ObjectManager Error: Memory Handler not attached.")
            return False # Indicate failure

        # Read ClientConnection - Static Pointer Address
        cc_ptr_val = self.mem.read_uint(offsets.STATIC_CLIENT_CONNECTION)
        if not cc_ptr_val:
            print(f"ObjectManager Error: Could not read ClientConnection at {hex(offsets.STATIC_CLIENT_CONNECTION)}.")
            return False
        self.client_connection = cc_ptr_val
        # print(f"DEBUG: ClientConnection Ptr Value: {hex(self.client_connection)}")

        # Read ObjectManager base pointer (Relative to ClientConnection value)
        om_base_addr = self.client_connection + offsets.OBJECT_MANAGER_OFFSET
        om_base_val = self.mem.read_uint(om_base_addr)
        if not om_base_val:
            print(f"ObjectManager Error: Could not read ObjectManager base pointer at {hex(om_base_addr)}.")
            return False
        self.object_manager_base = om_base_val
        # print(f"DEBUG: ObjectManager Base: {hex(self.object_manager_base)}")

        # Read First Object address (Relative to ObjectManager base)
        first_obj_addr = self.object_manager_base + offsets.FIRST_OBJECT_OFFSET
        first_obj_val = self.mem.read_uint(first_obj_addr)
        # No need to fail if first object is 0 (might happen briefly)
        self.first_object_address = first_obj_val
        # print(f"DEBUG: First Object Address: {hex(self.first_object_address)}")

        # Read Local Player GUID (Relative to ObjectManager base)
        local_guid_addr = self.object_manager_base + offsets.LOCAL_GUID_OFFSET
        local_guid_val = self.mem.read_ulonglong(local_guid_addr)
        if not local_guid_val:
             # This can be zero briefly during loading screens
             print(f"Warning: Local Player GUID read as zero from {hex(local_guid_addr)}. May be loading.")
             self.local_player_guid = 0
        else:
             self.local_player_guid = local_guid_val
             # print(f"DEBUG: Local Player GUID: 0x{self.local_player_guid:X}")

        # Read Target GUID (Static Address) - Optional at init
        # target_guid_addr = offsets.LOCAL_TARGET_GUID_STATIC
        # self.target_guid = self.mem.read_ulonglong(target_guid_addr)
        # print(f"DEBUG: Initial Target GUID (Static Read): 0x{self.target_guid:X}")

        # Initial update of player/target objects
        self.update_local_player() # Try to find player object immediately
        self.update_target()       # Read and find target object

        return True # Initialization successful (or at least pointers read)


    def is_ready(self) -> bool:
        """Check if the Object Manager has been successfully initialized."""
        # Check essential pointers are non-zero
        return bool(
            self.mem and self.mem.is_attached() and
            self.client_connection and
            self.object_manager_base
            # self.first_object_address # Can be 0 temporarily
            # self.local_player_guid # Can be 0 temporarily
        )

    def get_object_by_guid(self, guid_to_find: int) -> Optional[WowObject]:
        """
        Returns a WowObject from the cache or iterates the OM list if not found.
        Updates dynamic data for the returned object.
        """
        if guid_to_find == 0:
            return None
        if not self.is_ready():
            # Attempt re-init if trying to get an object but not ready
            if not self._initialize_addresses():
                 return None # Still not ready

        # --- Check Cache ---
        cached_obj = self.object_cache.get(guid_to_find)
        if cached_obj:
            # Quick validity check: Re-read type from memory. If 0, likely invalid.
            obj_type = self.mem.read_short(cached_obj.base_address + offsets.OBJECT_TYPE)
            if obj_type == cached_obj.type and obj_type != 0:
                 # cached_obj.update_dynamic_data(force_update=True) # Update data before returning
                 return cached_obj
            else:
                 # Object seems invalid, remove from cache
                 # print(f"DEBUG: Removing invalidated object {hex(guid_to_find)} from cache.")
                 del self.object_cache[guid_to_find]

        # --- Iterate Object List if not in cache or cache invalidated ---
        current_address = self.first_object_address
        checked_objects = 0
        max_checks = 5000 # Safety limit

        while current_address != 0 and current_address % 2 == 0 and checked_objects < max_checks:
            try:
                current_guid = self.mem.read_ulonglong(current_address + offsets.OBJECT_GUID)

                if current_guid == guid_to_find:
                    # Found it, create object, cache it, return it
                    new_obj = WowObject(current_address, self.mem, self.local_player_guid if current_guid == self.local_player_guid else 0)
                    if new_obj.guid != 0: # Check if core data read okay
                        # Get name immediately upon finding
                        self._fetch_object_name(new_obj)
                        # new_obj.update_dynamic_data(force_update=True) # Update dynamics
                        self.object_cache[guid_to_find] = new_obj
                        return new_obj
                    else:
                        return None # Failed to init object

                # Move to the next object
                next_addr = self.mem.read_uint(current_address + offsets.NEXT_OBJECT_OFFSET)
                if next_addr == current_address or next_addr == 0 or next_addr % 2 != 0:
                    break # End of list or invalid pointer or loop detected
                current_address = next_addr
                checked_objects += 1
            except Exception as e:
                # print(f"Error reading object list at 0x{current_address:X}: {e}") # Debug
                return None # Exit on memory error

        return None # Not found after iteration


    def _fetch_object_name(self, obj: WowObject):
         """Internal helper to get object name based on type."""
         if not obj or obj.name: return # Skip if no object or name exists

         if obj.is_player:
             obj.name = self.get_player_name_from_guid(obj.guid)
         elif obj.is_unit:
             obj.name = self._get_unit_name(obj.base_address)
         elif obj.type == WowObject.TYPE_GAMEOBJECT:
             obj.name = self._get_gameobject_name(obj.base_address)
         # Add other types if needed (GameObjects etc.)
         # else: obj.name = f"Obj_{obj.type}@{hex(obj.base_address)}" # Default fallback


    def update_local_player(self):
        """Updates the local player WowObject instance."""
        # Re-read local player GUID in case it changed (e.g., login/logout)
        if self.object_manager_base:
            local_guid_addr = self.object_manager_base + offsets.LOCAL_GUID_OFFSET
            current_local_guid = self.mem.read_ulonglong(local_guid_addr)
            if current_local_guid != self.local_player_guid:
                 print(f"Local player GUID changed: 0x{self.local_player_guid:X} -> 0x{current_local_guid:X}")
                 self.local_player_guid = current_local_guid
                 self.object_cache.clear() # Clear cache if player changes
                 self.local_player = None

        if not self.local_player_guid:
            self.local_player = None
            return

        player_obj = self.get_object_by_guid(self.local_player_guid)

        if player_obj:
            # Ensure name is retrieved if missing (should be caught by get_object_by_guid now)
            # self._fetch_object_name(player_obj)
            player_obj.update_dynamic_data(force_update=True) # Force update for player
            self.local_player = player_obj
            # <<< ADDED TEMPORARY DEBUG PRINT >>>
            # print(f"DEBUG: Player Base Address: {hex(self.local_player.base_address)}")
            # print(f"DEBUG: Player UnitFields Address: {hex(self.local_player.unit_fields_address)}")
            # <<< END TEMPORARY DEBUG PRINT >>>
        else:
            self.local_player = None # Player object not found in OM list


    def update_target(self):
        """Updates the target WowObject instance by reading the static target GUID."""
        if not self.is_ready(): # Ensure OM base is known before reading target
            self.target = None
            return

        # Read the current target GUID from the static address
        current_target_guid = self.mem.read_ulonglong(offsets.LOCAL_TARGET_GUID_STATIC)

        # Check if target changed
        target_changed = (current_target_guid != self.target_guid)

        if current_target_guid == 0:
            self.target = None
            self.target_guid = 0
            return

        self.target_guid = current_target_guid
        target_obj = self.get_object_by_guid(self.target_guid)

        if target_obj:
            # Ensure name is fetched if missing or if target changed
            # if not target_obj.name or target_changed:
            #      self._fetch_object_name(target_obj)
            target_obj.update_dynamic_data(force_update=True) # Force update for target
            self.target = target_obj
        else:
            self.target = None # Target GUID exists but object not found in OM


    def get_player_name_from_guid(self, guid: int) -> str:
        """Retrieves a player's name using the name cache structure."""
        if guid == 0: return ""
        # Added check for readiness
        if not self.is_ready(): return ""

        try:
            # NAME_STORE_BASE points to the structure containing Mask and Base pointers
            name_store_struct_addr = offsets.NAME_STORE_BASE
            mask_addr = name_store_struct_addr + offsets.NAME_MASK_OFFSET
            name_base_ptr_addr = name_store_struct_addr + offsets.NAME_BASE_OFFSET

            mask = self.mem.read_uint(mask_addr)
            name_base_ptr = self.mem.read_uint(name_base_ptr_addr) # Pointer to array of linked list heads

            if mask == 0 or name_base_ptr == 0:
                # print("Warning: Name cache mask or name array base pointer is zero.") # Reduce spam
                return ""

            short_guid = guid & 0xFFFFFFFF
            index_base_offset = 12 * (mask & short_guid)

            # Read the head pointer for the linked list at this index
            current_node_ptr_addr = name_base_ptr + index_base_offset + 8
            current_node_ptr = self.mem.read_uint(current_node_ptr_addr)
            next_node_offset_ptr_addr = name_base_ptr + index_base_offset
            next_node_offset = self.mem.read_uint(next_node_offset_ptr_addr)


            checks = 0
            max_list_checks = 50 # Safety break

            while current_node_ptr != 0 and checks < max_list_checks:
                # Check validity marker (lowest bit)
                if (current_node_ptr & 0x1) == 0x1: return "" # Invalid node marker

                # C# logic: testGUID = ReadUInt32((IntPtr)(current));
                node_guid_test = self.mem.read_uint(current_node_ptr) # Read only lower 32 bits for check

                if node_guid_test == short_guid:
                    # Found match, read the name pointer
                    # C# logic: return WowReader.ReadString((IntPtr)(current + NameOffsets.nameString));
                    name_addr = current_node_ptr + offsets.NAME_NODE_NAME_OFFSET

                    if name_addr != 0:
                        player_name = self.mem.read_string(name_addr, max_length=40) # Names are usually short
                        return player_name
                    else:
                        return "" # Name pointer was null

                # Move to next node
                # C# logic: current = WowReader.ReadUInt32((IntPtr)(current + offset + 4));
                next_node_ptr_addr = current_node_ptr + next_node_offset + 4
                current_node_ptr = self.mem.read_uint(next_node_ptr_addr) # Get next node address
                checks += 1

            return "" # Not found in linked list

        except pymem.exception.MemoryReadError:
            # print(f"Memory Error reading player name for GUID {hex(guid)}") # Debug spam
            return ""
        except Exception as e:
            # print(f"Error reading player name for GUID {hex(guid)}: {e}") # Debug
            return ""


    def _get_unit_name(self, unit_base_address: int) -> str:
        """Reads NPC/Unit name (simpler structure usually)."""
        # Try reading via Base -> +0x964 -> +0x5C -> Name String (Based on C# example)
        try:
            ptr1 = self.mem.read_uint(unit_base_address + 0x964)
            if ptr1 == 0: return "" # First pointer invalid

            ptr2 = self.mem.read_uint(ptr1 + 0x5C)
            if ptr2 == 0: return "" # Second pointer invalid (points to name string)

            name_addr = ptr2 # ptr2 holds the address of the name string

            unit_name = self.mem.read_string(name_addr, max_length=100)
            return unit_name
        except pymem.exception.MemoryReadError:
            return "" # Common if object is invalid
        except Exception as e:
            # print(f"Error reading unit name at {hex(unit_base_address)}: {e}") # Debug
            return ""

    def _get_gameobject_name(self, go_base_address: int) -> str:
        """Reads GameObject name via the info pointer structure."""
        try:
            # Read pointer to GameObjectInfo structure
            info_ptr_addr = go_base_address + offsets.OBJECT_GAMEOBJECT_INFO_PTR
            info_ptr = self.mem.read_uint(info_ptr_addr)
            if info_ptr == 0:
                # print(f"DEBUG: GameObject at {hex(go_base_address)} has null info pointer.")
                return ""

            # Read pointer to Name string from GameObjectInfo
            name_ptr_addr = info_ptr + offsets.GAMEOBJECT_INFO_NAME_PTR
            name_ptr = self.mem.read_uint(name_ptr_addr)
            if name_ptr == 0:
                # print(f"DEBUG: GameObject info at {hex(info_ptr)} has null name pointer.")
                return ""

            # Read the actual name string
            go_name = self.mem.read_string(name_ptr, max_length=100)
            # print(f"DEBUG: Read GameObject name '{go_name}' from {hex(name_ptr)}")
            return go_name

        except pymem.exception.MemoryReadError:
            # print(f"Memory Error reading GameObject name at {hex(go_base_address)}")
            return ""
        except Exception as e:
            # print(f"Error reading GameObject name at {hex(go_base_address)}: {e}")
            return ""

    def get_objects(self, object_type_filter: Optional[int] = None) -> Generator[WowObject, None, None]:
        """
        Generator that yields WowObjects from the object manager.
        Iterates the linked list and uses the cache. Updates names.
        """
        if not self.is_ready():
            return

        processed_guids_this_scan: Set[int] = set() # Keep track of GUIDs found in this scan
        current_address = self.first_object_address
        max_objects = 5000 # Safety limit

        while current_address != 0 and current_address % 2 == 0 and len(processed_guids_this_scan) < max_objects:
            try:
                obj_guid = self.mem.read_ulonglong(current_address + offsets.OBJECT_GUID)

                if obj_guid == 0: # Skip invalid GUIDs immediately
                     next_address = self.mem.read_uint(current_address + offsets.NEXT_OBJECT_OFFSET)
                     if next_address == current_address or next_address == 0 or next_address % 2 != 0: break
                     current_address = next_address
                     continue

                processed_guids_this_scan.add(obj_guid)

                # --- Use or create object ---
                obj = self.object_cache.get(obj_guid)
                if obj and obj.base_address == current_address:
                    # Object exists in cache and base address matches - likely valid
                    pass # Use existing 'obj'
                else:
                    # Not in cache or base address mismatch - create/recreate
                    obj = WowObject(current_address, self.mem, self.local_player_guid if obj_guid == self.local_player_guid else 0)
                    if obj.guid == 0: # Failed core read
                         next_address = self.mem.read_uint(current_address + offsets.NEXT_OBJECT_OFFSET)
                         if next_address == current_address or next_address == 0 or next_address % 2 != 0: break
                         current_address = next_address
                         continue # Skip this invalid object

                    # Fetch name for new object and cache it
                    self._fetch_object_name(obj)
                    self.object_cache[obj_guid] = obj

                # --- Yield if matches filter ---
                if object_type_filter is None or obj.type == object_type_filter:
                    yield obj

                # --- Move to next object ---
                next_address = self.mem.read_uint(current_address + offsets.NEXT_OBJECT_OFFSET)
                if next_address == current_address or next_address == 0 or next_address % 2 != 0:
                    break # End of list or invalid pointer or loop detected
                current_address = next_address

            except pymem.exception.MemoryReadError:
                 # Likely hit end of valid memory or object list corruption
                 # print(f"MemoryReadError during object iteration near {hex(current_address)}") # Debug
                 break
            except Exception as e:
                # print(f"Error during object iteration at {hex(current_address)}: {e}") # Debug
                break # Stop iteration on other errors

        # --- Cache Cleanup (Remove objects not seen in this scan) ---
        current_cache_guids = set(self.object_cache.keys())
        guids_to_remove = current_cache_guids - processed_guids_this_scan
        for guid_to_remove in guids_to_remove:
             # Keep local player/target in cache even if briefly not seen? Optional.
             # if guid_to_remove != self.local_player_guid and guid_to_remove != self.target_guid:
             try:
                  del self.object_cache[guid_to_remove]
                  # print(f"DEBUG: Removed GUID {hex(guid_to_remove)} from OM cache.")
             except KeyError: pass # Already removed


    def refresh(self):
        """Updates the local player and target objects."""
        now = time.time()
        # Add throttling if needed, e.g., refresh max 5 times/sec
        # if now < self.last_refresh_time + 0.2: return

        if not self.is_ready():
            if not self._initialize_addresses():
                return # Still not ready

        # Force update of player and target objects
        self.update_local_player()
        self.update_target()

        # Update other cached objects (skip player/target as they were just updated)
        # Make a copy of keys to avoid modification during iteration issues
        cached_guids = list(self.object_cache.keys())
        for guid in cached_guids:
            if guid == self.local_player_guid or guid == self.target_guid:
                continue # Skip already updated player/target
            obj = self.object_cache.get(guid)
            if obj:
                try:
                    # Optional: Add throttling here too if needed for performance
                    obj.update_dynamic_data()
                except Exception as e:
                    # Log error and potentially remove object from cache if update fails badly
                    print(f"[ObjectManager] Error updating cached object {guid:X}: {e}")
                    # Optionally remove from cache: del self.object_cache[guid]
            # else: Object disappeared from cache during iteration (rare)

        self.last_refresh_time = now


    def read_known_spell_ids(self) -> list[int]:
        """Reads the list of known spell IDs directly from memory using verified offsets."""
        spell_ids = []
        # Added readiness check
        if not self.is_ready():
            print("ObjectManager Error: Cannot read spell IDs, OM not fully initialized.")
            return spell_ids

        try:
            known_spell_count_addr = offsets.SPELLBOOK_KNOWN_SPELL_COUNT_ADDRESS
            known_spell_count = self.mem.read_uint(known_spell_count_addr)

            max_reasonable_spells = 5000 # Increased limit slightly
            if not (0 < known_spell_count < max_reasonable_spells):
                print(f"Warning: Spell count ({known_spell_count}) at {hex(known_spell_count_addr)} seems invalid. Aborting spell ID read.")
                return spell_ids

            spell_map_base_addr = offsets.SPELLBOOK_SLOT_MAP_ADDRESS
            if spell_map_base_addr == 0:
                 print("Error: SPELLBOOK_SLOT_MAP_ADDRESS is not defined or zero.")
                 return spell_ids

            # print(f"DEBUG: Reading {known_spell_count} spell IDs from {hex(spell_map_base_addr)}...") # Debug
            for i in range(known_spell_count):
                spell_id_addr = spell_map_base_addr + (i * 4)
                spell_id = self.mem.read_uint(spell_id_addr)
                if spell_id > 0: # Filter out potential zero entries
                    spell_ids.append(spell_id)

            # print(f"DEBUG: Successfully read {len(spell_ids)} positive spell IDs.") # Debug
            return spell_ids

        except pymem.exception.MemoryReadError as e:
            print(f"Memory Error reading spellbook IDs: {e}")
            return []
        except Exception as e:
            print(f"Unexpected Error reading spellbook IDs: {e}")
            return []


# --- Example Usage ---
if __name__ == "__main__":
    mem = MemoryHandler()
    if mem.is_attached():
        om = ObjectManager(mem)
        if om.is_ready():
            print("\nObject Manager Initialized.")

            start_time = time.time()
            om.refresh()
            refresh_time = time.time() - start_time
            print(f"Initial Refresh took: {refresh_time:.4f}s")

            if om.local_player: print(f"\nLocal Player Data:\n  {om.local_player}")
            else: print("\nLocal Player not found.")

            if om.target: print(f"\nTarget Data:\n  {om.target}")
            else: print("\nNo target selected or target not found.")

            print("\n--- Iterating Nearby Units/Players (First 20) ---")
            found_count = 0
            iter_start_time = time.time()
            for obj in om.get_objects(): # Iterate all types
                if obj.guid == om.local_player_guid: continue # Skip self
                if obj.is_player or obj.is_unit:
                     obj.update_dynamic_data() # Update dynamics for display
                     # Name should be fetched by get_object_by_guid or refresh
                     print(f"  {obj}")
                     found_count += 1
                     if found_count >= 20: break
            iter_time = time.time() - iter_start_time
            print(f"Finished iterating in {iter_time:.4f}s")

            print("\n--- Reading Spell IDs ---")
            known_ids = om.read_known_spell_ids()
            if known_ids: print(f"Found {len(known_ids)} known spell IDs (showing first 20): {known_ids[:20]}")
            else: print("Could not read spell IDs or count was invalid.")

        else: print("Failed to initialize Object Manager.")
    else: print("Failed to attach Memory Handler.")