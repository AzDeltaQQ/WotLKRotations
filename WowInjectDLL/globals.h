// globals.h - Define shared constants, types, and extern declarations
#pragma once

// Include necessary headers that define types used here (e.g., windows, string, queue)
#include "pch.h"
#include <string>
#include <vector>
#include <queue>
#include <mutex>
#include <condition_variable> // Added for worker thread signalling
#include <cstdint>
#include <atomic> // For atomic bool

// Forward declare complex types if needed
struct lua_State;
struct IDirect3DDevice9;

// --- Constants ---
extern const WCHAR* PIPE_NAME;
const DWORD PIPE_TIMEOUT_MS = 5000;
const DWORD PIPE_BUFFER_SIZE = 4096;

// --- Enums ---
enum RequestType {
    REQ_UNKNOWN,
    REQ_EXEC_LUA,
    REQ_GET_TIME_MS,
    REQ_GET_CD,
    REQ_IS_IN_RANGE,
    REQ_PING,
    REQ_GET_SPELL_INFO,
    REQ_CAST_SPELL,
    REQ_GET_COMBO_POINTS,
    REQ_GET_TARGET_GUID,
    REQ_IS_BEHIND_TARGET
};

// --- Structs ---
struct Request {
    RequestType type = REQ_UNKNOWN;
    std::string data;     // For Lua code or unknown command data
    int spell_id = 0;
    std::string spell_name; // Keep for now?
    std::string unit_id;    // For target unit (IS_IN_RANGE)
    uint64_t target_guid = 0;
};

// --- Typedefs ---
typedef HRESULT(WINAPI* EndScene_t)(IDirect3DDevice9* pDevice);
typedef void (__cdecl* lua_Execute_t)(const char* luaCode, const char* executionSource, int zero);
typedef int(__cdecl* lua_pcall_t)(lua_State* L, int nargs, int nresults, int errfunc);
typedef double(__cdecl* lua_tonumber_t)(lua_State* L, int idx);
typedef void(__cdecl* lua_settop_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_gettop_t)(lua_State* L);
typedef const char*(__cdecl* lua_tolstring_t)(lua_State* L, int idx, size_t* len);
typedef void(__cdecl* lua_pushinteger_t)(lua_State* L, int n);
typedef int(__cdecl* lua_tointeger_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_toboolean_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_isnumber_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_isstring_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_type_t)(lua_State* L, int idx);
typedef int (__cdecl* lua_loadbuffer_t)(lua_State *L, const char *buff, size_t sz, const char *name);
typedef void(__cdecl* lua_getfield_t)(lua_State* L, int idx, const char* k);
typedef void(__cdecl* lua_pushstring_t)(lua_State* L, const char* s);
typedef void(__cdecl* lua_pushnil_t)(lua_State* L);
typedef char (__cdecl* CastLocalPlayerSpell_t)(int spellId, int unknownIntArg, uint64_t targetGuid, char unknownCharArg);
// Add other function pointer typedefs from dllmain.cpp here as needed...
typedef void* (__cdecl* findObjectByGuidAndFlags_t)(uint64_t guid, int flags);
typedef bool(__thiscall* IsUnitVectorDifferenceWithinHemisphereFn)(void* pThisObserver, void* pObserved);


// --- Global Variable Declarations (defined in globals.cpp) ---
extern HMODULE g_hModule;
extern std::atomic<bool> g_running; // Use atomic bool for thread safety
extern HANDLE g_hPipe;
extern std::queue<Request> g_requestQueue;      // IPC -> Hook
extern std::queue<std::string> g_responseQueue; // ProcessCommand -> Hook -> IPC
extern std::mutex g_queueMutex;                 // Mutex protecting BOTH queues
extern lua_State* g_luaState;
extern EndScene_t oEndScene; // Original EndScene function pointer
extern HANDLE g_ipcThreadHandle; // Handle for IPC thread

// --- Add WoW Specific Function Pointer Typedefs (Add as needed) ---

// --- Base Address ---
extern uintptr_t g_baseAddress; 