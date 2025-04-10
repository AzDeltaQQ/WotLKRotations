import offsets # Import offsets globally for constants
import time
import logging

logger = logging.getLogger(__name__)

class WowObject:
    """Represents a generic World of Warcraft object (Player, NPC, Item, etc.)."""

    # Object Types (Keep only Player and Unit)
    TYPE_NONE = 0
    TYPE_UNIT = 3       # NPCs, Mobs
    TYPE_PLAYER = 4
    # TYPE_GAMEOBJECT = 5 # Removed
    # TYPE_DYNAMICOBJECT = 6 # Removed
    # TYPE_CORPSE = 7 # Removed

    # --- Class IDs and Power Types for 3.3.5a ---
    CLASS_WARRIOR = 1
    CLASS_PALADIN = 2
    CLASS_HUNTER = 3
    CLASS_ROGUE = 4
    CLASS_PRIEST = 5
    CLASS_DEATH_KNIGHT = 6
    CLASS_SHAMAN = 7
    CLASS_MAGE = 8
    CLASS_WARLOCK = 9
    CLASS_DRUID = 11

    POWER_MANA = 0
    POWER_RAGE = 1
    POWER_FOCUS = 2 # Not primary in Wrath for players
    POWER_ENERGY = 3
    POWER_HAPPINESS = 4 # Pets
    POWER_RUNES = 5 # DK resource (Not the main bar)
    POWER_RUNIC_POWER = 6 # DK primary bar

    # Unit Flags (from Wowhead/common sources for 3.3.5 - Check bits in UNIT_FIELD_FLAGS)
    # Simplified relevant flags:
    UNIT_FLAG_NONE = 0x00000000
    UNIT_FLAG_SERVER_CONTROLLED = 0x00000001       # set only on server side controls
    UNIT_FLAG_NON_ATTACKABLE = 0x00000002          # not attackable
    UNIT_FLAG_DISABLE_MOVE = 0x00000004
    UNIT_FLAG_PVP_ATTACKABLE = 0x00000008          # Subject to PvP rules
    UNIT_FLAG_PREPARATION = 0x00000020             # Unit is preparing spell
    UNIT_FLAG_OOC_NOT_ATTACKABLE = 0x00000100      # Makes unit unattackable while OOC
    UNIT_FLAG_PASSIVE = 0x00000200                 # Passive unit (won't aggro)
    UNIT_FLAG_LOOTING = 0x00000400                 # Player is Looting
    UNIT_FLAG_PET_IN_COMBAT = 0x00000800           # Player Pet is in combat
    UNIT_FLAG_PVP = 0x00001000                     # Player flagged PvP
    UNIT_FLAG_SILENCED = 0x00002000                # Unit is silenced
    UNIT_FLAG_PACIFIED = 0x00020000                # Unit is pacified
    UNIT_FLAG_STUNNED = 0x00040000                 # Unit is stunned
    UNIT_FLAG_IN_COMBAT = 0x00080000               # Unit is in combat (NOTE: Often unreliable for players!)
    UNIT_FLAG_TAXI_FLIGHT = 0x00100000             # Unit is on taxi
    UNIT_FLAG_DISARMED = 0x00200000                # Unit is disarmed
    UNIT_FLAG_CONFUSED = 0x00400000
    UNIT_FLAG_FLEEING = 0x00800000
    UNIT_FLAG_PLAYER_CONTROLLED = 0x01000000       # Charmed or Possessed
    UNIT_FLAG_NOT_SELECTABLE = 0x02000000
    UNIT_FLAG_SKINNABLE = 0x04000000
    UNIT_FLAG_MOUNT = 0x08000000                   # Unit is mounted
    UNIT_FLAG_SHEATHE = 0x40000000                 # Unit weapons are sheathed


    def __init__(self, base_address: int, mem_handler, local_player_guid: int = 0):
        self.base_address = base_address
        self.mem = mem_handler
        self.local_player_guid = local_player_guid # Store the local player GUID if this is the local player

        # --- Core properties read immediately ---
        self.guid: int = 0
        self.type: int = WowObject.TYPE_NONE
        self.unit_fields_address: int = 0
        self.descriptor_address: int = 0
        self.target_guid: int = 0 # Read early if Unit/Player

        # --- Properties updated dynamically or lazily ---
        self.name: str = ""
        self.x_pos: float = 0.0
        self.y_pos: float = 0.0
        self.z_pos: float = 0.0
        self.rotation: float = 0.0
        self.level: int = 0
        self.health: int = 0
        self.max_health: int = 0
        self.energy: int = 0 # Current primary power
        self.max_energy: int = 0 # Max primary power
        self.power_type: int = -1 # Enum value (POWER_MANA, POWER_RAGE etc.)
        self.unit_flags: int = 0 # Raw flags field
        self.summoned_by_guid: int = 0
        self.casting_spell_id: int = 0
        self.channeling_spell_id: int = 0
        self.is_dead: bool = False
        self.last_update_time: float = 0.0 # Track last dynamic update

        # Read initial essential data if base address is valid
        if self.base_address and self.mem and self.mem.is_attached():
            self._read_core_data()

    def _read_core_data(self):
        """Reads the most essential data (GUID, Type, Field/Descriptor Ptrs, TargetGUID)."""
        # import offsets # Usually not needed here if imported globally

        self.guid = self.mem.read_ulonglong(self.base_address + offsets.OBJECT_GUID)
        self.type = self.mem.read_short(self.base_address + offsets.OBJECT_TYPE) # Use read_short for 2 bytes

        if self.type == WowObject.TYPE_UNIT or self.type == WowObject.TYPE_PLAYER:
            unit_fields_ptr_addr = self.base_address + offsets.OBJECT_UNIT_FIELDS
            self.unit_fields_address = self.mem.read_uint(unit_fields_ptr_addr)

            descriptor_ptr_addr = self.base_address + offsets.OBJECT_DESCRIPTOR_OFFSET
            self.descriptor_address = self.mem.read_uint(descriptor_ptr_addr)

            # Read target GUID immediately if unit/player and fields ptr is valid
            if self.unit_fields_address:
                 target_guid_addr = self.unit_fields_address + offsets.UNIT_FIELD_TARGET_GUID
                 self.target_guid = self.mem.read_ulonglong(target_guid_addr)


    def update_dynamic_data(self, force_update=False):
        """Updates frequently changing data. Optional throttling."""
        now = time.time()
        # Throttle updates unless forced (e.g., reduce updates for non-target units)
        # Add more sophisticated throttling later if needed
        # if not force_update and now < self.last_update_time + 0.1: # Update max 10 times/sec
        #      return

        if not self.base_address or not self.mem or not self.mem.is_attached():
            return
        # import offsets # Local import

        # --- Position and Rotation ---
        self.x_pos = self.mem.read_float(self.base_address + offsets.OBJECT_POS_X)
        self.y_pos = self.mem.read_float(self.base_address + offsets.OBJECT_POS_Y)
        self.z_pos = self.mem.read_float(self.base_address + offsets.OBJECT_POS_Z)
        self.rotation = self.mem.read_float(self.base_address + offsets.OBJECT_ROTATION)

        # --- DEBUG LOG --- Check Position Read
        # if self.type in [WowObject.TYPE_UNIT, WowObject.TYPE_PLAYER] and self.guid != self.local_player_guid: # Log only other units/players
        #     print(f"[DEBUG WOW_OBJ {self.guid:X}] Pos: ({self.x_pos:.1f}, {self.y_pos:.1f}, {self.z_pos:.1f}) from base {self.base_address:X}")

        # --- Data primarily from Unit Fields (Check if pointer is valid!) ---
        if self.unit_fields_address:
            # --- Health and Level ---
            self.health = self.mem.read_uint(self.unit_fields_address + offsets.UNIT_FIELD_HEALTH)
            self.max_health = self.mem.read_uint(self.unit_fields_address + offsets.UNIT_FIELD_MAXHEALTH)
            self.level = self.mem.read_uint(self.unit_fields_address + offsets.UNIT_FIELD_LEVEL)

            # --- DEBUG LOG --- Check Health Read
            # if self.type in [WowObject.TYPE_UNIT, WowObject.TYPE_PLAYER] and self.guid != self.local_player_guid:
            #     print(f"[DEBUG WOW_OBJ {self.guid:X}] Health: {self.health}/{self.max_health} from UnitFields {self.unit_fields_address:X}")

            # --- Flags ---
            self.unit_flags = self.mem.read_uint(self.unit_fields_address + offsets.UNIT_FIELD_FLAGS)

            # --- Summoner ---
            self.summoned_by_guid = self.mem.read_ulonglong(self.unit_fields_address + offsets.UNIT_FIELD_SUMMONEDBY)

            # --- Target (might have changed) ---
            self.target_guid = self.mem.read_ulonglong(self.unit_fields_address + offsets.UNIT_FIELD_TARGET_GUID)

            # --- Power Reading (Needs Power Type first) ---
            # Determine Power Type (Descriptor preferred)
            current_power_type = -1

            # Try reading power type from UNIT_FIELD_BYTES_0 (Byte 3) first - often reliable
            bytes_0_addr = self.unit_fields_address + offsets.UNIT_FIELD_BYTES_0
            bytes_0_val = self.mem.read_uint(bytes_0_addr)
            current_power_type = (bytes_0_val >> 24) & 0xFF # 4th byte
            if current_power_type > 10: # If invalid, try descriptor
                 current_power_type = -1 # Reset before trying descriptor
                 if self.descriptor_address:
                      power_type_addr = self.descriptor_address + offsets.UNIT_FIELD_POWER_TYPE_BYTE_FROM_DESCRIPTOR # Offset 0x47
                      current_power_type = self.mem.read_uchar(power_type_addr)
                      if current_power_type > 10: current_power_type = -1 # Sanity check descriptor result

            # Fallback if descriptor fails or type invalid (This part is now less likely to be needed)
            # if current_power_type == -1:
            #    # Already tried bytes_0 above, so this fallback is redundant
            #    pass

            self.power_type = current_power_type

            # Read Current and Max Power based on determined type
            if self.power_type != -1:
                # --- Current Power ---
                # Reverting to original logic that used specific offsets per type
                current_power_addr = 0
                if self.power_type == WowObject.POWER_MANA: current_power_addr = self.unit_fields_address + (0x19 * 4) # UNIT_FIELD_POWER1 ?
                elif self.power_type == WowObject.POWER_RAGE: current_power_addr = self.unit_fields_address + (0x19 * 4) # UNIT_FIELD_POWER1 ?
                elif self.power_type == WowObject.POWER_FOCUS: current_power_addr = self.unit_fields_address + (0x1A * 4) # UF + 0x68 << UNTESTED
                elif self.power_type == WowObject.POWER_ENERGY:
                    # User confirmation: Address UF + 0x70 (calculated MaxEnergy offset) shows current energy
                    current_power_addr = self.unit_fields_address + 0x70
                    # current_power_addr = self.unit_fields_address + 0x64 # Tried this - Incorrect
                    # current_power_addr = self.unit_fields_address + 0x58 # UF + 0x58 << IDA Offset - FAILED
                # elif self.power_type == WowObject.POWER_HAPPINESS: current_power_addr = self.unit_fields_address + (0x1C * 4) # UNIT_FIELD_POWER4 ?
                # Skip Runes (complex)
                elif self.power_type == WowObject.POWER_RUNIC_POWER: current_power_addr = self.unit_fields_address + (0x1E * 4) # UF + 0x78 << UNTESTED
                else: current_power_addr = self.unit_fields_address + (0x19 * 4) # Default to POWER1

                read_value = 0 # Initialize before read
                if current_power_addr:
                    # Try reading as bytes and converting manually (as per original logic)
                    raw_bytes = self.mem.read_bytes(current_power_addr, 4)
                    if raw_bytes and len(raw_bytes) == 4:
                        try:
                            read_value = int.from_bytes(raw_bytes, 'little')
                        except ValueError:
                            # print(f\"[WOW_OBJECT] Error converting bytes {raw_bytes.hex()} to int at {current_power_addr:X}\", \"ERROR\")
                            read_value = 0 # Ensure it's zero on conversion failure
                    else:
                        read_value = 0 # Ensure it's zero if read fails
                else:
                    read_value = 0 # Ensure it's zero if address was not determined

                self.energy = read_value # Assign whatever was read (or 0) to self.energy

                # --- Max Power ---
                # Using the original logic that was present
                if self.power_type == WowObject.POWER_ENERGY:
                    max_power_addr = self.unit_fields_address + 0x6C
                else: # Use the offset that worked for Max Mana
                    max_power_base_offset = 0x64
                    max_power_addr = self.unit_fields_address + max_power_base_offset + (self.power_type * 4)

                self.max_energy = self.mem.read_uint(max_power_addr)

                # --- Fallback for Max Energy (Keep this) ---
                if self.power_type == WowObject.POWER_ENERGY and (self.max_energy <= 0 or self.max_energy > 150):
                    self.max_energy = 100
                    #print(\"DEBUG: Max Energy read failed or invalid, using fallback 100\", \"DEBUG\")

            else: # Invalid or unhandled power type
                self.energy = 0
                self.max_energy = 0

        # --- Casting/Channeling Info (from object base offsets) ---
        # These seem more reliable based on common usage
        self.casting_spell_id = self.mem.read_uint(self.base_address + offsets.OBJECT_CASTING_SPELL_ID)
        self.channeling_spell_id = self.mem.read_uint(self.base_address + offsets.OBJECT_CHANNEL_SPELL_ID)

        # --- Derived States ---
        self.is_dead = (self.health <= 0) or self.has_flag(WowObject.UNIT_FLAG_SKINNABLE)

        self.last_update_time = now # Record update time

    # --- Property helpers for Flags ---
    def has_flag(self, flag: int) -> bool:
        """Checks if the unit has a specific flag set."""
        return bool(self.unit_flags & flag)

    @property
    def is_player(self) -> bool:
        return self.type == WowObject.TYPE_PLAYER

    @property
    def is_unit(self) -> bool:
        return self.type == WowObject.TYPE_UNIT

    @property
    def is_attackable(self) -> bool:
        # Basic check: Not dead, has GUID, not non-attackable flag
        # More complex checks involve faction, PvP status etc.
        if self.is_dead or self.guid == 0: return False
        if self.has_flag(WowObject.UNIT_FLAG_NON_ATTACKABLE): return False
        if self.has_flag(WowObject.UNIT_FLAG_OOC_NOT_ATTACKABLE): # Check combat status needed here
             # Need reliable IsInCombat check (Lua?)
             return False # Assume not attackable if OOC flag is set for simplicity now
        return True

    # Add more flag properties as needed (is_stunned, is_silenced etc.)
    @property
    def is_stunned(self) -> bool:
        return self.has_flag(WowObject.UNIT_FLAG_STUNNED)

    @property
    def is_casting(self) -> bool:
        return self.casting_spell_id != 0

    @property
    def is_channeling(self) -> bool:
        return self.channeling_spell_id != 0

    # --- End Property helpers ---

    def get_name(self) -> str:
        """Returns the object's name. Relies on ObjectManager to set it."""
        return self.name if self.name else f"Obj_{self.type}@{hex(self.base_address)}"

    def get_power_label(self) -> str:
        """Returns the string label for the object's primary power type."""
        type_map = {
            WowObject.POWER_MANA: "Mana", WowObject.POWER_RAGE: "Rage",
            WowObject.POWER_FOCUS: "Focus", WowObject.POWER_ENERGY: "Energy",
            WowObject.POWER_HAPPINESS: "Happiness", WowObject.POWER_RUNES: "Runes",
            WowObject.POWER_RUNIC_POWER: "RunicPower"
        }
        return type_map.get(self.power_type, "Power")

    def get_type_str(self) -> str:
        """Returns a human-readable string for the object's type."""
        type_map = {
            WowObject.TYPE_NONE: "None",
            WowObject.TYPE_UNIT: "Unit",
            WowObject.TYPE_PLAYER: "Player",
            # WowObject.TYPE_GAMEOBJECT: "GameObject", # Removed
            # WowObject.TYPE_DYNAMICOBJECT: "DynamicObj", # Removed
            # WowObject.TYPE_CORPSE: "Corpse" # Removed
        }
        return type_map.get(self.type, "Unknown")

    def __str__(self):
        name_str = self.get_name()
        type_map = {
            WowObject.TYPE_NONE: "None",
            WowObject.TYPE_UNIT: "Unit", WowObject.TYPE_PLAYER: "Player",
            # WowObject.TYPE_GAMEOBJECT: "GameObject", # Removed
            # WowObject.TYPE_DYNAMICOBJECT: "DynObj", # Removed
            # WowObject.TYPE_CORPSE: "Corpse", # Removed
        }
        obj_type_str = type_map.get(self.type, f"Type{self.type}")
        guid_hex = f"0x{self.guid:X}"

        details = f"<{obj_type_str} '{name_str}' GUID:{guid_hex}"
        if self.is_unit or self.is_player:
            status = "Dead" if self.is_dead else ("Casting" if self.is_casting else ("Channeling" if self.is_channeling else "Alive"))
            details += f", Lvl:{self.level}, HP:{self.health}/{self.max_health}"

            power_label = self.get_power_label()
            max_display = self.max_energy if self.power_type != WowObject.POWER_ENERGY or self.max_energy > 0 else 100
            if max_display > 0 or self.energy > 0: # Show power if relevant
                 details += f", {power_label}:{self.energy}/{max_display}"

            details += f" ({status})"
            if self.target_guid != 0: details += f" Target:0x{self.target_guid:X}"
            # Add flags if useful f" Flags:{hex(self.unit_flags)}"

        details += f", Pos:({self.x_pos:.1f},{self.y_pos:.1f},{self.z_pos:.1f})"
        details += ">"
        return details

    def __repr__(self):
        # Provide a concise representation, useful for debugging collections
        return f"WowObject(GUID=0x{self.guid:X}, Base=0x{self.base_address:X}, Type={self.type})"

    