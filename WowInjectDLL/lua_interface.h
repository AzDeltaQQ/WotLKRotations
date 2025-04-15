// lua_interface.h
#pragma once

#include "globals.h"
#include <string>
#include <vector>
#include <cstdint> // Include for uint64_t if needed elsewhere

// Forward declaration
struct lua_State;

// Standard Lua Constants (if lua.h is not included)
#define LUA_MULTRET (-1)
#define LUA_TNONE (-1)
#define LUA_TNIL 0
#define LUA_TBOOLEAN 1
#define LUA_TLIGHTUSERDATA 2
#define LUA_TNUMBER 3
#define LUA_TSTRING 4
#define LUA_TTABLE 5
#define LUA_TFUNCTION 6
#define LUA_TUSERDATA 7
#define LUA_TTHREAD 8

// --- Initialization & State --- 
bool InitializeLua();
void ShutdownLua();
lua_State* GetLuaState();

// --- Execution Functions --- 
// Executes Lua using FrameScript_Execute (WoW specific, no return value handling here)
void ExecuteLuaSimple(const std::string& luaCode, const std::string& sourceName = "WowInjectDLL");

// Executes Lua using pcall and returns results concatenated as a string
std::string ExecuteLuaPCall(const std::string& luaCode);

// --- Helper Functions (Consider moving implementation to .cpp or removing) ---
// std::vector<std::string> CallLuaFunction(const std::string& funcName, const std::vector<std::string>& args);
// std::string CallLua(const char* funcName, const char* sig, ...);


// --- Lua API Wrappers (Optional) ---
// Consider adding wrappers for common Lua operations if needed
// Example:
// bool Lua_GetGlobal(const char* name);
// double Lua_GetNumberResult(int stackIndex = -1);
// std::string Lua_GetStringResult(int stackIndex = -1);

// Add other necessary declarations... 