# Offsets for WoW Client (Target Version: 3.3.5a 12340 - Based on User Analysis)
# Offsets are relative to the process base address (e.g., 0x400000)

# --- Confirmed Lua C API Functions (3.3.5a 12340 - User Verified List 2024-07-15) ---
LUA_GETTOP = 0x0084DBD0    # lua_gettop(L) -> int (Updated)
LUA_SETTOP = 0x0084DBF0    # lua_settop(L, index) -> void (Verified)
LUA_PUSHSTRING = 0x0084E350 # lua_pushstring(L, s) -> void (Verified)
LUA_PUSHINTEGER = 0x0084E2D0 # lua_pushinteger(L, n) -> void (Verified)
LUA_PUSHNUMBER = 0x0084E2A0  # lua_pushnumber(L, n) -> void (Seems correct, not on list but standard)
LUA_TOLSTRING = 0x0084E0E0  # lua_tolstring(L, index, len) -> const char* (Updated)
LUA_TONUMBER = 0x0084E030   # lua_tonumber(L, index) -> lua_Number (double) (Updated)
LUA_TOINTEGER = 0x0084E070  # lua_tointeger(L, index) -> lua_Integer (int) (Verified)
LUA_TYPE = 0x0084DEB0       # lua_type(L, index) -> int (type ID) (Seems correct, not on list but standard)
LUA_PCALL = 0x0084EC50    # lua_pcall(L, nargs, nresults, errfunc) -> int (Verified)
# LUA_GETTABLE = 0x0084E0E0    # lua_gettable(L, index) -> void (Commented out - Conflicts with LUA_TOLSTRING)
LUA_PUSHBOOLEAN = 0x0084E4D0 # lua_pushboolean(L, b) -> void (From List: FrameScript_pushboolean)
LUA_PUSHCCLOSURE = 0x0084E400 # lua_pushcclosure(L, fn, n) -> void (From List: FrameScript_pushcclosure)
LUA_TOBOOLEAN = 0x0044E2C0   # lua_toboolean(L, index) -> int (From List: FrameScript_toboolean)
TOCFUNCTION = 0x0084E1C0 # lua_tocfunction(L, index) -> lua_CFunction (From List: FrameScript_tocfunction)

# --- Effective lua_getglobal Sequence Start (3.3.5a 12340) ---
# Calling this sequence directly seems to cause crashes (0x84E200). Reverting to manual lookup.
# This address points to the start of the core instruction sequence (after the
# WoW helper function pushes its own args) that achieves the standard
# lua_getglobal(L, name) behavior using pushstring + getfield_by_stack_key.
# We call this address directly after pushing our C args (L, name_ptr).
# LUA_GETGLOBAL = 0x00818020  # Sequence start (xor edi, edi) after helper pushes - COMMENTED OUT - Causes crash?

# --- WoW Custom / Modified Functions (3.3.5a 12340 - User Verified List 2024-07-15) ---
LUA_GETFIELD_BY_STACK_KEY = 0x0084F3B0 # WoW specific: getfield(L, index) - expects key on Lua stack (Updated from FrameScript_getfield)
FRAMESCRIPT_EXECUTE = 0x00819210      # WoW func: FrameScript_Execute(code, source, 0) (Verified)
WOW_SETFIELD = 0x0084E900             # WoW specific: setfield(L, index, key) - custom implementation (From List: FrameScript_setfield)
LUA_RAWGET_HELPER = 0x00854510        # WoW C impl for rawget() Lua func
WOW_GETGLOBALSTRINGVARIABLE = 0x00818010 # WoW helper: getglobal(L, s, char** result) -> bool

# --- Confirmed Constants (3.3.5a 12340) ---
LUA_GLOBALSINDEX = -10002 # Pseudo-index for _G (0xFFFFD8EE in hex representation)

# --- Game Specific Functions (Examples - Need Verification) ---
# These are likely dynamic or different in other versions
# SPELL_C_GET_SPELL_COOLDOWN = 0x00807980 # C func for GetSpellCooldown? (Unverified Signature)
# SPELL_C_GET_SPELL_RANGE = 0x0080AB40    # C func for GetSpellRange? (Unverified Signature)


# Client Connection and Object Manager
STATIC_CLIENT_CONNECTION = 0x00C79CE0
OBJECT_MANAGER_OFFSET = 0x2ED0  # Relative to ClientConnection
FIRST_OBJECT_OFFSET = 0xAC  # Relative to ObjectManager
LOCAL_GUID_OFFSET = 0xC0  # Relative to ObjectManager

# GUIDs (Static addresses might be less reliable than dynamic reads)
LOCAL_PLAYER_GUID_STATIC = 0xBD07A8 # Consider reading dynamically via ObjectManager + LOCAL_GUID_OFFSET
LOCAL_TARGET_GUID_STATIC = 0x00BD07B0 # Consider reading dynamically

# Object Properties (Relative to Object Base Address)
OBJECT_TYPE = 0x14
OBJECT_GUID = 0x30
OBJECT_UNIT_FIELDS = 0x8
OBJECT_POS_X = 0x79C
OBJECT_POS_Y = 0x798
OBJECT_POS_Z = 0x7A0
OBJECT_ROTATION = 0x7A8
NEXT_OBJECT_OFFSET = 0x3C  # Relative to Object Base Address to get next object in the list

OBJECT_DESCRIPTOR_OFFSET = 0x8 # Pointer to the object's descriptor structure (contains display info, power type byte, etc.)

# Unit Field Descriptors (Indices relative to UnitFields Pointer, multiply by 4 for offset)
UNIT_FIELD_HEALTH = 0x18 * 4
UNIT_FIELD_MAXHEALTH = 0x20 * 4
UNIT_FIELD_LEVEL = 0x36 * 4
# Define the start of the power arrays based on the struct
UNIT_FIELD_POWERS = 0x4C # Start of the current power array (UNIT_FIELD_POWERS[7])
UNIT_FIELD_MAXPOWERS = 0x6C # Start of the max power array (UNIT_FIELD_MAXPOWERS[7])
# Specific power indices relative to UnitFields Pointer:
UNIT_FIELD_ENERGY = 0x19 * 4  # Includes Mana, Rage, Energy (Index 1 = POWER_MANA)
UNIT_FIELD_MAXENERGY = 0x21 * 4 # Includes MaxMana, MaxRage, MaxEnergy (Index 1 = MAXPOWER_MANA)
# --- Specific MaxPower fields for clarity/testing ---
UNIT_FIELD_MAXPOWER1 = 0x21 * 4 # Used for MaxMana, MaxRage
UNIT_FIELD_MAXPOWER2 = 0x22 * 4
UNIT_FIELD_MAXPOWER3 = 0x23 * 4 # Potentially used for MaxEnergy
UNIT_FIELD_MAXPOWER4 = 0x24 * 4
UNIT_FIELD_MAXPOWER5 = 0x25 * 4
UNIT_FIELD_MAXPOWER6 = 0x26 * 4
UNIT_FIELD_MAXPOWER7 = 0x27 * 4 # Potentially used for MaxRunicPower
# --- End added fields ---
UNIT_FIELD_SUMMONEDBY = 0xE * 4 # Guid of the summoner
UNIT_FIELD_BYTES_0 = 0x5C # Relative to UnitFields Pointer. Contains Class, Race, etc.
UNIT_FIELD_FLAGS = 0xEC # Relative to UnitFields Pointer
UNIT_FIELD_TARGET_GUID = 0x12 * 4 # Relative to UnitFields Pointer
UNIT_FIELD_POWER_TYPE_BYTE_FROM_DESCRIPTOR = 0x47 # Offset from Descriptor Pointer for the Power Type Byte

# Name Store (For Player Names)
NAME_STORE_BASE = 0x00C5D938 + 0x8 # Base address of the name structure
NAME_MASK_OFFSET = 0x24 # Offset for the mask within the name structure
NAME_BASE_OFFSET = 0x1C # Offset for the base pointer within the name structure
# Corrected offset based on C# example structure reading
# NAME_STRING_OFFSET = 0x20 # Offset for the actual name string within a name entry
NAME_NODE_NEXT_OFFSET = 0xC # Offset to the 'next' pointer within a name node (Changed from 0xC)
NAME_NODE_NAME_OFFSET = 0x20 # Offset to the name string itself within a name node (Based on C# ReadString(current + 0x20))

# --- Lua Interface ---
LUA_STATE = 0x00D3F78C # Pointer to the lua_State*

# --- FrameScript Execute (Simpler Execution) ---
# LUA_FRAMESCRIPT_EXECUTE = 0x00819210 # Args: char* luaCode, char* executionSource = "", int a3 = 0 -> void

# --- Spell Functions & Data ---
SPELL_CAST_SPELL = 0x0080DA40 # Function address for CGGameUI::CastSpell(spellId, 0) - User Provided

# Spell Book (Addresses from user disassembly for 3.3.5a - VERIFIED)
SPELLBOOK_START_ADDRESS = 0x00BE5D88
SPELLBOOK_SPELL_COUNT_ADDRESS = 0x00BE8D9C
SPELLBOOK_SLOT_MAP_ADDRESS = 0x00BE6D88
SPELLBOOK_KNOWN_SPELL_COUNT_ADDRESS = 0x00BE8D98

# --- Cooldowns (Needs RE - VERIFIED ADDRESSES)
SPELL_COOLDOWN_PTR = 0x00D3F5AC # Pointer to cooldown structure
SPELL_C_GET_SPELL_COOLDOWN = 0x00807980 # Function address for GetSpellCooldown(spellId)

# --- Other Globals (VERIFIED)
LAST_TARGET_GUID = 0x00BD07B8
MOUSE_OVER_GUID = 0x00BD07A0
COMBO_POINTS = 0x00BD084D # Static address for player combo points byte
LAST_HARDWARE_ACTION_TIMESTAMP = 0x00B499A4

# Object Offsets (Relative to Object Base Address - VERIFIED)
OBJECT_CASTING_SPELL_ID = 0xA6C
OBJECT_CHANNEL_SPELL_ID = 0xA80

# --- Added from User List (3.3.5a - VERIFIED ADDRESSES) ---
SPELL_C_GET_SPELL_RANGE = 0x00802C30 # Signature needed from IDA.
UNIT_CASTING_ID_OFFSET = 0xC08 # Current spell being cast
UNIT_CHANNEL_ID_OFFSET = 0xC20 # Current spell being channeled

AURA_COUNT_1_OFFSET = 0xDD0
AURA_COUNT_2_OFFSET = 0xC54
AURA_TABLE_1_OFFSET = 0xC50
AURA_TABLE_2_OFFSET = 0xC58
AURA_STRUCT_SIZE = 0x18
AURA_STRUCT_SPELL_ID_OFFSET = 0x8

PLAYER_COMBO_POINTS_STATIC = 0x00BD084D

# --- Combat Log (Needs RE - Tentative) ---
COMBAT_LOG_LIST_MANAGER = 0xADB974 # Updated based on AppendCombatLogEntry disassembly (was 0xC704F0)
# Offsets relative to COMBAT_LOG_LIST_MANAGER value (Based on AppendLinkedListNode analysis 2024-07-19)
COMBAT_LOG_LIST_HEAD_OFFSET = 0x0 # Offset within manager struct to head pointer (Standard)
COMBAT_LOG_LIST_TAIL_OFFSET = 0x4 # Offset within manager struct to tail pointer (Verified)

# --- Combat Log Event Node Structure - Offsets relative to Node Base Address ---
# Node Base Address = ESI in AppendCombatLogEntry / New Node Ptr in AppendLinkedListNode
COMBAT_LOG_EVENT_PREV_OFFSET = 0x0      # Offset within node to previous node pointer (Verified)
COMBAT_LOG_EVENT_NEXT_OFFSET = 0x4      # Offset within node to next node pointer (Verified)
COMBAT_LOG_EVENT_TIMESTAMP_OFFSET = 0x8 # Offset within node to timestamp (Verified from handleCombatEvent)
# COMBAT_LOG_EVENT_DATA_OFFSET = 0xC      # REMOVED - Data starts after node pointers, read whole struct
# COMBAT_LOG_EVENT_DATA_SIZE = 0x58       # REMOVED - Read based on ctypes.sizeof(CombatLogEventNode)

# Pointer potentially related to timestamp/sequence source?
COMBAT_LOG_TIMESTAMP_SOURCE = 0x00CD76AC # (dword_CD76AC)

# Pointer to the next node to be processed by the game internal systems
COMBAT_LOG_NEXT_UNPROCESSED_NODE = 0x00CA1394 # (dword_CA1394)

# --- GameObject Specific Offsets (Needs Verification) ---
# OBJECT_GAMEOBJECT_INFO_PTR = 0x1EC # Removed
# GAMEOBJECT_INFO_NAME_PTR = 0xB4   # Removed

# --- Camera Offsets ---
CAMERA_BASE_PTR_OFFSET = 0x00C7B5A8
CAMERA_OFFSET1 = 0x6B04
CAMERA_OFFSET2 = 0xE8
CAMERA_PITCH_OFFSET = 0x34
CAMERA_YAW_OFFSET = 0x30

# --- Unit Fields Cache (CGUnit_C::m_unitValueCache?) - Needs base pointer ---
# Example: Needs base address to apply offsets like 0x1530 for Level

# --- GUID Management ---

    