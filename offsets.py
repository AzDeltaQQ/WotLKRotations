      
# Offsets for WoW 3.3.5a build 12340
# Extracted from: https://github.com/johnmoore/WoW-Object-Manager/blob/master/WoWObjMgr/PlayerScan.cs
# User confirmed verification via IDA/reversing for build 12340.

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
NAME_NODE_NEXT_OFFSET = 0xC # Offset to the 'next' pointer within a name node (Verify)
NAME_NODE_NAME_OFFSET = 0x20 # Offset to the name string itself within a name node (Based on C# ReadString(current + 0x20))

# --- Lua Interface ---
LUA_STATE = 0x00D3F78C # Pointer to the lua_State*

# --- Lua C API Function Addresses (User Verified for 12340) ---
# Core Stack/Type Functions
LUA_GETTOP = 0x0084DBD0    # lua_gettop(lua_State *L) -> int
LUA_SETTOP = 0x0084DBF0    # lua_settop(lua_State *L, int index) -> void
LUA_TOLSTRING = 0x0084E0E0 # lua_tolstring(lua_State *L, int index, size_t *len) -> const char*
LUA_TONUMBER = 0x0084E030  # lua_tonumber(lua_State *L, int index) -> lua_Number (double)
LUA_TOINTEGER = 0x0084E070 # lua_tointeger(lua_State* L, int idx) -> int (WoW likely uses this less often than tonumber)
LUA_TOBOOLEAN = 0x0044E2C0 # lua_toboolean(lua_State *L, int index) -> int (0 or 1)
LUA_PUSHSTRING = 0x0084E350 # lua_pushstring(lua_State *L, const char *s) -> void
LUA_PUSHINTEGER = 0x0084DFF0 # lua_pushinteger(lua_State *L, lua_Integer n) -> void (Assuming standard API name)
LUA_PUSHNUMBER = 0x0084E010  # lua_pushnumber(lua_State *L, lua_Number n) -> void (Assuming standard API name)
LUA_PUSHBOOLEAN = 0x0084DFA0 # lua_pushboolean(lua_State *L, int b) -> void (Assuming standard API name)
LUA_PUSHNIL = 0x0084DF90     # lua_pushnil(lua_State *L) -> void (Assuming standard API name)
LUA_POP = 0x0084DC10       # lua_pop(lua_State *L, int n) -> void (Equivalent to settop(L, -n-1))
LUA_TYPE = 0x0084DEB0      # lua_type(lua_State *L, int index) -> int (returns LUA_T* constants)

# Execution Functions
LUA_PCALL = 0x0084EC50       # lua_pcall(lua_State*, int nargs, int nresults, int errfunc) -> int (status code)
LUA_CALL = 0x0084EBE0        # lua_call(lua_State*, int nargs, int nresults) -> void (Use pcall for safety)
LUA_LOADBUFFER = 0x0084F860 # luaL_loadbuffer(lua_State*, char* buff, size_t sz, char* name) -> int (status code)

# Table Functions
LUA_GETFIELD = 0x0084E1C0    # lua_getfield(lua_State *L, int index, const char *k) -> void (Pushes value onto stack)
LUA_SETFIELD = 0x0084E5A0    # lua_setfield(lua_State *L, int index, const char *k) -> void (Pops value from stack)
LUA_GETGLOBAL = 0x0084E200   # lua_getglobal(lua_State *L, const char *name) -> void (Pushes value onto stack)
LUA_SETGLOBAL = 0x0084E5E0   # lua_setglobal(lua_State *L, const char *name) -> void (Pops value from stack)
LUA_NEXT = 0x0084E850       # lua_next(lua_State *L, int index) -> int (Pops key, pushes key,value)

# --- FrameScript Execute (Simpler Execution) ---
LUA_FRAMESCRIPT_EXECUTE = 0x00819210 # Args: char* luaCode, char* executionSource = "", int a3 = 0 -> void

# --- Spell Functions & Data ---
SPELL_CAST_SPELL = 0x0080DA40 # Function address for CGGameUI::CastSpell(spellId, 0)

# Spell Book (Addresses from user disassembly for 3.3.5a - VERIFIED)
SPELLBOOK_START_ADDRESS = 0x00BE5D88 # Array of spell IDs or pointers? Needs structure check via IDA if reading directly.
SPELLBOOK_SPELL_COUNT_ADDRESS = 0x00BE8D9C # Max number of spell slots?
SPELLBOOK_SLOT_MAP_ADDRESS = 0x00BE6D88 # Mapping or related spell ID array? Seems like the list of known IDs.
SPELLBOOK_KNOWN_SPELL_COUNT_ADDRESS = 0x00BE8D98 # Number of known spells from disassembly? Seems correct.

# --- Cooldowns (Needs RE to determine structure/function usage - VERIFIED ADDRESSES) ---
SPELL_COOLDOWN_PTR = 0x00D3F5AC # Pointer to cooldown structure (needs investigation via IDA)
SPELL_C_GET_SPELL_COOLDOWN = 0x00807980 # Function address for GetSpellCooldown(spellId) -> returns cooldown info. Signature needed from IDA.

# --- Other Globals (VERIFIED) ---
# CURRENT_TARGET_GUID = 0x00BD07B0 # Already defined as LOCAL_TARGET_GUID_STATIC
LAST_TARGET_GUID = 0x00BD07B8
MOUSE_OVER_GUID = 0x00BD07A0
COMBO_POINTS = 0x00BD084D # Static address for player combo points byte
LAST_HARDWARE_ACTION_TIMESTAMP = 0x00B499A4

# Object Offsets (Relative to Object Base Address - VERIFIED)
OBJECT_CASTING_SPELL_ID = 0xA6C
OBJECT_CHANNEL_SPELL_ID = 0xA80

# --- Added from User List (3.3.5a - VERIFIED ADDRESSES) ---

# Lua Spell Functions (Addresses of the C functions backing the Lua API calls)
# These would be called via Lua C API (pcall etc.), not directly via shellcode usually
# unless you replicate the argument setup exactly.
# LUA_GET_SPELL_COOLDOWN = 0x00540E80 (Functionality provided by SPELL_C_GET_SPELL_COOLDOWN)
# LUA_GET_SPELL_INFO = 0x00540A30

# Direct Spell Functions (Potentially callable via C injection/calling convention - VERIFIED ADDRESSES)
SPELL_C_GET_SPELL_RANGE = 0x00802C30 # Signature needed from IDA.

# Unit Casting/Channeling Info (Offsets relative to Unit Base Address - VERIFIED)
UNIT_CASTING_ID_OFFSET = 0xC08 # Current spell being cast
UNIT_CHANNEL_ID_OFFSET = 0xC20 # Current spell being channeled

# Aura Information (Offsets relative to Unit Base Address - VERIFIED)
# Finding the start and size of the aura structures is key.
AURA_COUNT_1_OFFSET = 0xDD0 # Often maximum auras possible?
AURA_COUNT_2_OFFSET = 0xC54 # Often current active auras? Needs IDA check.
AURA_TABLE_1_OFFSET = 0xC50 # Pointer to array/list of Aura structs (Ptr to Ptr?)
AURA_TABLE_2_OFFSET = 0xC58 # Alternative pointer? Needs IDA check.
AURA_STRUCT_SIZE = 0x18 # Size of each aura structure (Verify with IDA)
AURA_STRUCT_SPELL_ID_OFFSET = 0x8 # Offset within the Aura struct for Spell ID (Verify with IDA)
# Other aura struct offsets needed from IDA: CasterGUID (0x10?), Duration, ExpirationTime, Stacks (0xD?), Flags (0xC?)

# Player Specific (Offsets likely static or relative to known base - VERIFIED)
PLAYER_COMBO_POINTS_STATIC = 0x00BD084D # Direct address to read combo points (usually a byte)

    