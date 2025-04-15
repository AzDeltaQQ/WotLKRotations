// lua_interface.cpp
#include "lua_interface.h"
#include "globals.h" // Include globals for typedefs and g_luaState
#include "offsets.h" // Include offsets for addresses
#include <stdexcept> // For runtime_error
#include <windows.h> // For OutputDebugStringA
#include <cstdio>    // For sprintf_s
#include <cstdarg>   // For va_list, va_start, va_end
#include <vector>
#include <string>
#include <sstream> // For stringstream

// --- Lua Function Pointers (initialized in InitializeLua) ---
// Using typedefs from globals.h
lua_Execute_t       lua_Execute_ptr = nullptr;
lua_pcall_t         lua_pcall_ptr = nullptr;
lua_tonumber_t      lua_tonumber_ptr = nullptr;
lua_settop_t        lua_settop_ptr = nullptr;
lua_gettop_t        lua_gettop_ptr = nullptr;
lua_tolstring_t     lua_tolstring_ptr = nullptr;
lua_pushstring_t    lua_pushstring_ptr = nullptr; // Note: Typedef missing in globals.h, assumed void(__cdecl*)(lua_State*, const char*)
lua_pushinteger_t   lua_pushinteger_ptr = nullptr;
lua_tointeger_t    lua_tointeger_ptr = nullptr;
lua_toboolean_t     lua_toboolean_ptr = nullptr;
lua_isnumber_t      lua_isnumber_ptr = nullptr;
lua_isstring_t      lua_isstring_ptr = nullptr;
lua_type_t          lua_type_ptr = nullptr;
lua_loadbuffer_t    lua_loadbuffer_ptr = nullptr;
lua_pushnil_t       lua_pushnil_ptr = nullptr; // Note: Typedef missing in globals.h, assumed void(__cdecl*)(lua_State*)
lua_getfield_t      lua_getfield_ptr = nullptr;


// --- Initialization --- 
bool InitializeLua() {
    char log_buf[256];

    // 1. Get Lua State Pointer
    try {
        // Read the pointer to the pointer
        uintptr_t luaStatePtrAddr = LUA_STATE_PTR_ADDR;
        uintptr_t* luaStatePtrPtr = reinterpret_cast<uintptr_t*>(luaStatePtrAddr);
        if (!luaStatePtrPtr) {
            OutputDebugStringA("[Lua] ERROR: LUA_STATE_PTR_ADDR is invalid (0).\n");
            return false;
        }
        // Dereference to get the actual lua_State*
        g_luaState = reinterpret_cast<lua_State*>(*luaStatePtrPtr);

        if (!g_luaState) {
            sprintf_s(log_buf, sizeof(log_buf), "[Lua] ERROR: Failed to get Lua state pointer from address 0x%X (Result was NULL).\n", luaStatePtrAddr);
            OutputDebugStringA(log_buf);
            return false;
        }
         sprintf_s(log_buf, sizeof(log_buf), "[Lua] Successfully obtained Lua state pointer: 0x%p\n", g_luaState);
         OutputDebugStringA(log_buf);

    } catch (...) {
         OutputDebugStringA("[Lua] CRITICAL ERROR: Exception while reading Lua state pointer!\n");
         g_luaState = nullptr;
         return false;
    }

    // 2. Initialize Function Pointers using offsets namespace
    lua_Execute_ptr = (lua_Execute_t)WOW_LUA_EXECUTE;
    lua_pcall_ptr = (lua_pcall_t)LUA_PCALL_ADDR;
    lua_tonumber_ptr = (lua_tonumber_t)LUA_TONUMBER_ADDR;
    lua_settop_ptr = (lua_settop_t)LUA_SETTOP_ADDR;
    lua_gettop_ptr = (lua_gettop_t)LUA_GETTOP_ADDR;
    lua_tolstring_ptr = (lua_tolstring_t)LUA_TOLSTRING_ADDR;
    lua_pushstring_ptr = (lua_pushstring_t)LUA_PUSHSTRING_ADDR;
    lua_pushinteger_ptr = (lua_pushinteger_t)LUA_PUSHINTEGER_ADDR;
    lua_tointeger_ptr = (lua_tointeger_t)LUA_TOINTEGER_ADDR;
    lua_toboolean_ptr = (lua_toboolean_t)LUA_TOBOOLEAN_ADDR;
    lua_isnumber_ptr = (lua_isnumber_t)LUA_ISNUMBER_ADDR;
    lua_isstring_ptr = (lua_isstring_t)LUA_ISSTRING_ADDR;
    lua_type_ptr = (lua_type_t)LUA_TYPE_ADDR;
    lua_loadbuffer_ptr = (lua_loadbuffer_t)LUA_LOADBUFFER_ADDR;
    lua_pushnil_ptr = (lua_pushnil_t)LUA_PUSHNIL_ADDR;
    lua_getfield_ptr = (lua_getfield_t)LUA_GETFIELD_ADDR;

    // Basic check if pointers seem valid (optional)
    if (!lua_Execute_ptr || !lua_pcall_ptr /* ... add others ... */) {
        OutputDebugStringA("[Lua] ERROR: One or more Lua function pointers failed to initialize!\n");
        return false;
    }

    OutputDebugStringA("[Lua] Lua interface initialized successfully.\n");
    return true;
}

void ShutdownLua() {
    g_luaState = nullptr;
    // Nullify function pointers (optional, good practice)
    lua_Execute_ptr = nullptr;
    lua_pcall_ptr = nullptr;
    // ... nullify others ...
    OutputDebugStringA("[Lua] Lua interface shut down.\n");
}

lua_State* GetLuaState() {
    return g_luaState;
}

// Simple execution without return value handling
void ExecuteLuaSimple(const std::string& luaCode, const std::string& sourceName) {
    if (!g_luaState || !lua_Execute_ptr) {
        OutputDebugStringA("[Lua] Error in ExecuteLuaSimple: Lua not initialized.\n");
        return;
    }
    try {
        lua_Execute_ptr(luaCode.c_str(), sourceName.c_str(), 0);
    } catch (...) {
         OutputDebugStringA("[Lua] CRITICAL ERROR: Exception during lua_Execute_ptr call!\n");
    }
}

// Executes Lua code using pcall and returns the result as a string
std::string ExecuteLuaPCall(const std::string& luaCode) {
    OutputDebugStringA("[Lua][PCall] Enter ExecuteLuaPCall.\n"); // Log Entry
    if (!g_luaState || !lua_loadbuffer_ptr || !lua_pcall_ptr || !lua_gettop_ptr || !lua_settop_ptr || !lua_tolstring_ptr) {
        OutputDebugStringA("[Lua][PCall] ERROR: Lua state or function pointers NULL.\n"); // Log Error
        return "LUA_RESULT:ERROR:Not Initialized";
    }

    std::string resultString;
    OutputDebugStringA("[Lua][PCall] Getting stack top...\n"); // Log Step
    int topBefore = lua_gettop_ptr(g_luaState);
    OutputDebugStringA("[Lua][PCall] Stack top before: "); // Log Step
    OutputDebugStringA(std::to_string(topBefore).c_str());
    OutputDebugStringA("\n");

    try {
        // Load the string chunk
        OutputDebugStringA("[Lua][PCall] Calling lua_loadbuffer_ptr...\n"); // Log Step
        int loadStatus = lua_loadbuffer_ptr(g_luaState, luaCode.c_str(), luaCode.length(), "=WowInjectDLL");
        OutputDebugStringA("[Lua][PCall] lua_loadbuffer_ptr finished. Status: "); // Log Step
        OutputDebugStringA(std::to_string(loadStatus).c_str());
        OutputDebugStringA("\n");

        if (loadStatus != 0) {
            size_t len;
            OutputDebugStringA("[Lua][PCall] Load failed. Getting error message...\n"); // Log Step
            const char* errorMsg = lua_tolstring_ptr(g_luaState, -1, &len);
            resultString = "LUA_RESULT:ERROR:LoadError:";
            resultString += (errorMsg ? errorMsg : "Unknown load error");
            OutputDebugStringA("[Lua][PCall] Load error message: "); // Log Step
            OutputDebugStringA(errorMsg ? errorMsg : "NULL");
            OutputDebugStringA("\n");
            OutputDebugStringA("[Lua][PCall] Cleaning stack after load error...\n"); // Log Step
            lua_settop_ptr(g_luaState, topBefore); // Clean up stack
            OutputDebugStringA("[Lua][PCall] Returning load error.\n"); // Log Exit
            return resultString;
        }

        // Execute the chunk using pcall
        OutputDebugStringA("[Lua][PCall] Calling lua_pcall_ptr...\n"); // Log Step
        int callStatus = lua_pcall_ptr(g_luaState, 0, LUA_MULTRET, 0); // LUA_MULTRET allows multiple return values
        OutputDebugStringA("[Lua][PCall] lua_pcall_ptr finished. Status: "); // Log Step
        OutputDebugStringA(std::to_string(callStatus).c_str());
        OutputDebugStringA("\n");

        if (callStatus != 0) {
            size_t len;
            OutputDebugStringA("[Lua][PCall] PCall failed. Getting error message...\n"); // Log Step
            const char* errorMsg = lua_tolstring_ptr(g_luaState, -1, &len);
            resultString = "LUA_RESULT:ERROR:PCallError:";
            resultString += (errorMsg ? errorMsg : "Unknown pcall error");
            OutputDebugStringA("[Lua][PCall] PCall error message: "); // Log Step
            OutputDebugStringA(errorMsg ? errorMsg : "NULL");
            OutputDebugStringA("\n");
            OutputDebugStringA("[Lua][PCall] Cleaning stack after pcall error...\n"); // Log Step
            lua_settop_ptr(g_luaState, topBefore); // Clean up stack
            OutputDebugStringA("[Lua][PCall] Returning pcall error.\n"); // Log Exit
            return resultString;
        }

        // Process return values
        OutputDebugStringA("[Lua][PCall] PCall success. Getting result count...\n"); // Log Step
        int nresults = lua_gettop_ptr(g_luaState) - topBefore;
        OutputDebugStringA("[Lua][PCall] Result count: "); // Log Step
        OutputDebugStringA(std::to_string(nresults).c_str());
        OutputDebugStringA("\n");

        if (nresults <= 0) {
            resultString = ""; // No return value, represent as empty string
            OutputDebugStringA("[Lua][PCall] No results found.\n"); // Log Step
        } else {
            OutputDebugStringA("[Lua][PCall] Processing results...\n"); // Log Step
            // Concatenate all return values into a single string, separated by comma
            // This matches the old behavior somewhat but might need adjustment based on Python parsing
            for (int i = 1; i <= nresults; ++i) {
                 size_t len;
                 // Use luaL_tolstring equivalent if available, otherwise basic lua_tolstring
                 const char* val = lua_tolstring_ptr(g_luaState, topBefore + i, &len);
                 if (val) {
                     resultString += val;
                 } else {
                      // Handle non-string results (e.g., numbers, booleans) - convert them?
                      // For now, append type name or just "nil"
                      int type = lua_type_ptr(g_luaState, topBefore + i);
                      if (type == LUA_TNUMBER && lua_isnumber_ptr(g_luaState, topBefore + i)) {
                          resultString += std::to_string(lua_tonumber_ptr(g_luaState, topBefore + i));
                      } else if (type == LUA_TBOOLEAN) {
                          resultString += lua_toboolean_ptr(g_luaState, topBefore + i) ? "true" : "false";
                      } else {
                         resultString += "nil"; // Or lua_typename(L, type)
                      }
                 }
                 if (i < nresults) {
                     resultString += ","; // Separator
                 }
            }
            OutputDebugStringA("[Lua][PCall] Finished processing results.\n"); // Log Step
        }

    } catch (...) {
        OutputDebugStringA("[Lua][PCall] CRITICAL EXCEPTION during execution!\n"); // Log Error
        resultString = "LUA_RESULT:ERROR:Exception during Lua execution";
        // Attempt to clean stack even after exception
        try {
            OutputDebugStringA("[Lua][PCall] Attempting stack cleanup after exception...\n"); // Log Step
            lua_settop_ptr(g_luaState, topBefore);
        } catch(...) {
            OutputDebugStringA("[Lua][PCall] EXCEPTION during stack cleanup!\n"); // Log Error
        }
        OutputDebugStringA("[Lua][PCall] Returning exception error.\n"); // Log Exit
        return resultString;
    }

    // Clean up the Lua stack
    OutputDebugStringA("[Lua][PCall] Cleaning stack before exit...\n"); // Log Step
    lua_settop_ptr(g_luaState, topBefore);
    OutputDebugStringA("[Lua][PCall] Exiting ExecuteLuaPCall successfully.\n"); // Log Exit
    return resultString;
}

// CallLuaFunction and CallLua are more complex and less used currently.
// Keeping CallLua structure for potential future use or reference.
std::vector<std::string> CallLuaFunction(const std::string& funcName, const std::vector<std::string>& args) {
    // TODO: Implement this if needed, requires robust arg parsing/pushing
    OutputDebugStringA("[Lua] CallLuaFunction not fully implemented.\n");
    return {}; // Placeholder
}

std::string CallLua(const char* funcName, const char* sig, ...) {
     // TODO: Re-implement this carefully using stored function pointers
     //       Needs proper stack management and error checking.
     //       Consider using a safer approach than varargs.
     OutputDebugStringA("[Lua] CallLua (varargs) is deprecated/unimplemented.\n");
     return "ERR:CallLua unimplemented"; // Placeholder
} 