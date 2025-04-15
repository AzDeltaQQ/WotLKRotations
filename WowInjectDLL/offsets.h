// offsets.h - Central repository for WoW 3.3.5a (12340) addresses and offsets
#pragma once

#include <cstdint>

// Define a namespace to keep offsets organized
// namespace offsets { // Removed namespace for testing

// --- Base Address (Obtained at runtime in dllmain/globals) ---
// extern uintptr_t g_baseAddress; // Referenced via globals.h

// --- WoW Specific / Modified ---
constexpr uintptr_t WOW_LUA_EXECUTE             = 0x00819210; // FrameScript_Execute(code, source, 0)
constexpr uintptr_t WOW_SETFIELD                = 0x0084E900; // WoW's lua_setfield implementation
constexpr uintptr_t LUA_RAWGET_HELPER           = 0x00854510; // WoW C impl for rawget() Lua func
constexpr uintptr_t WOW_GETGLOBALSTRINGVARIABLE = 0x00818010; // WoW helper: getglobal(L, s, char** result) -> bool

// --- Lua C API (Mapped to WoW implementations) ---
constexpr uintptr_t LUA_STATE_PTR_ADDR   = 0x00D3F78C; // Address holding the pointer to lua_State*
constexpr uintptr_t LUA_PCALL_ADDR       = 0x0084EC50; // FrameScript_PCall
constexpr uintptr_t LUA_TONUMBER_ADDR    = 0x0084E030; // FrameScript_ToNumber
constexpr uintptr_t LUA_SETTOP_ADDR      = 0x0084DBF0; // FrameScript__SetTop
constexpr uintptr_t LUA_TOLSTRING_ADDR   = 0x0084E0E0; // FrameScript_ToLString
constexpr uintptr_t LUA_PUSHSTRING_ADDR  = 0x0084E350; // FrameScript_PushString
constexpr uintptr_t LUA_PUSHINTEGER_ADDR = 0x0084E2D0; // FrameScript_PushInteger
constexpr uintptr_t LUA_TOINTEGER_ADDR   = 0x0084E070; // FrameScript_ToInteger
constexpr uintptr_t LUA_TOBOOLEAN_ADDR   = 0x0084E0B0; // FrameScript_ToBoolean
constexpr uintptr_t LUA_PUSHNIL_ADDR     = 0x0084E280; // pushNilValue
constexpr uintptr_t LUA_ISSTRING_ADDR    = 0x0084DF60; // FrameScript_IsString
constexpr uintptr_t LUA_GETTOP_ADDR      = 0x0084DBD0; // FrameScript_GetTop
constexpr uintptr_t LUA_ISNUMBER_ADDR    = 0x0084DF20; // FrameScript_IsNumber
constexpr uintptr_t LUA_TYPE_ADDR        = 0x0084DEB0; // lua_type
constexpr uintptr_t LUA_LOADBUFFER_ADDR  = 0x0084F860; // FrameScript_Load (luaL_loadbuffer)
constexpr uintptr_t LUA_GETFIELD_ADDR    = 0x0084E590; // WoW's lua_getfield implementation

// --- WoW Internal C Functions / Game API ---
constexpr uintptr_t WOW_CAST_SPELL_FUNC_ADDR = 0x0080DA40; // CastLocalPlayerSpell address
constexpr uintptr_t LUA_GETSPELLINFO_ADDR    = 0x00540A30; // lua_GetSpellInfo (WoW's C function called by Lua)

// --- Static Game Data Addresses ---
constexpr uintptr_t COMBO_POINTS_ADDR      = 0x00BD084D; // Static address for player combo points byte

// --- DirectX Hooking Offsets ---
constexpr uintptr_t D3D_PTR_1                       = 0x00C5DF88; // Pointer to D3D structure 1
constexpr uintptr_t D3D_PTR_2                       = 0x397C;     // Offset in structure 1
constexpr uintptr_t D3D_ENDSCENE_VTABLE_OFFSET      = 0xA8;       // Offset in VTable for EndScene (Index 42 * 4 bytes)

// --- Object Manager & Object Struct Offsets (Keeping previous standard ones for now) ---
constexpr uintptr_t STATIC_CLIENT_CONNECTION        = 0x00C79CE0; // Pointer to ClientConnection
constexpr uintptr_t OBJECT_MANAGER_OFFSET           = 0x2ED0;     // Offset within ClientConnection to ObjManager Pointer
constexpr uintptr_t LOCAL_GUID_OFFSET               = 0xC0;       // Offset within ObjManager struct to Player GUID
// Object Descriptors (Example)
constexpr uintptr_t OBJECT_POS_X                    = 0x9B8;      // Object Position X (relative to object base)
constexpr uintptr_t OBJECT_POS_Y                    = 0x9BC;      // Object Position Y
constexpr uintptr_t OBJECT_POS_Z                    = 0x9C0;      // Object Position Z
constexpr uintptr_t OBJECT_ROTATION                 = 0x9C4;      // Object Rotation/Facing (Radians)

// --- Game Functions (Keeping previous standard ones for now) ---
constexpr uintptr_t FIND_OBJECT_BY_GUID_FUNC_ADDR   = 0x004D7350; // CGWorldFrame::Object_RawGetByGuid
constexpr uintptr_t SPELL_CAST_SPELL                = 0x0080B210; // CGGameUI::CastSpell (Might be different from WOW_CAST_SPELL_FUNC_ADDR?)

// --- Player/Target State (Keeping previous standard ones for now) ---
constexpr uintptr_t LOCAL_TARGET_GUID_STATIC        = 0x00BD07A0; // Current Target GUID
// constexpr uintptr_t PLAYER_COMBO_POINTS_STATIC      = 0x00BD07C0; // Old, replaced by COMBO_POINTS_ADDR

// } // namespace offsets // Removed namespace for testing
