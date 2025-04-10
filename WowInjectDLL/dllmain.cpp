// dllmain.cpp : Defines the entry point for the DLL application.
#include "pch.h"
#include <iostream> // For debug output if needed
#include <queue>    // For command queue
#include <mutex>    // For thread safety
#include <string>   // For command strings
#include <vector>   // For processing dequeued commands
#include <chrono>   // For basic timing/sleep in IPC response wait
#include <cstdio>   // For sscanf
#include <cstdint>  // For uint64_t
#include <sstream>  // << ADDED for string building

// Explicitly define EndScene_t function pointer type here
typedef HRESULT(WINAPI* EndScene_t)(LPDIRECT3DDEVICE9 pDevice);

// --- Forward Declarations for Lua ---
struct lua_State; // Opaque Lua state type

// --- Request/Response Queues & Types ---
enum RequestType {
    REQ_UNKNOWN,
    REQ_EXEC_LUA,
    REQ_GET_TIME,         // Deprecated, use GET_TIME_MS
    REQ_GET_TIME_MS,      // New: Get time in milliseconds
    REQ_GET_CD,           // New: Get spell cooldown
    REQ_IS_IN_RANGE,      // New: Check spell range
    REQ_PING,             // New: Simple ping request
    REQ_GET_SPELL_INFO,   // New: Get spell details
    REQ_CAST_SPELL,       // New: Cast spell via internal C function
    REQ_GET_COMBO_POINTS  // New: Get combo points on target
};

// Moved struct Request definition BEFORE its usage in g_requestQueue
struct Request {
    RequestType type = REQ_UNKNOWN;
    std::string data;     // For Lua code or unknown command data
    int spell_id = 0;     // For spell ID related commands (GET_CD, IS_IN_RANGE, GET_SPELL_INFO, CAST_SPELL)
    std::string spell_name; // For spell name related commands (IS_IN_RANGE - old way, maybe remove?)
    std::string unit_id;  // For target unit (IS_IN_RANGE)
    uint64_t target_guid = 0; // For target GUID (CAST_SPELL)
};

// --- Globals ---
std::queue<Request> g_requestQueue;      // Commands from Python -> Main Thread
std::queue<std::string> g_responseQueue; // Results from Main Thread -> Python
std::mutex g_queueMutex;                 // Mutex protecting BOTH queues

EndScene_t oEndScene = nullptr; // Original EndScene function pointer
HMODULE g_hModule = nullptr; // Store the module handle for the DLL
HANDLE g_hPipe = INVALID_HANDLE_VALUE; // Handle for the named pipe
HANDLE g_hIPCThread = nullptr;      // Handle for the IPC thread
volatile bool g_bShutdown = false;   // Flag to signal shutdown

// --- WoW Function Definitions & Pointers (Consolidated) --- 

// --- Addresses (#define) ---
// WoW Specific / Modified
#define WOW_LUA_EXECUTE             0x00819210 // FrameScript_Execute(code, source, 0)
#define WOW_SETFIELD                0x0084E900 // WoW's lua_setfield implementation
#define LUA_RAWGET_HELPER           0x00854510 // WoW C impl for rawget() Lua func
#define WOW_GETGLOBALSTRINGVARIABLE 0x00818010 // WoW helper: getglobal(L, s, char** result) -> bool

// Lua C API (Mapped to WoW implementations)
#define LUA_STATE_PTR_ADDR   0x00D3F78C // Address holding the pointer to lua_State*
#define LUA_PCALL_ADDR       0x0084EC50 // FrameScript_PCall
#define LUA_TONUMBER_ADDR    0x0084E030 // FrameScript_ToNumber
#define LUA_SETTOP_ADDR      0x0084DBF0 // FrameScript__SetTop
#define LUA_TOLSTRING_ADDR   0x0084E0E0 // FrameScript_ToLString
#define LUA_PUSHSTRING_ADDR  0x0084E350 // FrameScript_PushString
#define LUA_PUSHINTEGER_ADDR 0x0084E2D0 // FrameScript_PushInteger
#define LUA_TOINTEGER_ADDR   0x0084E070 // FrameScript_ToInteger
#define LUA_TOBOOLEAN_ADDR   0x0084E0B0 // FrameScript_ToBoolean (UPDATED from user list)
#define LUA_PUSHNIL_ADDR     0x0084E280 // pushNilValue
#define LUA_ISSTRING_ADDR    0x0084DF60 // FrameScript_IsString (UPDATED from user list)
#define LUA_GETTOP_ADDR      0x0084DBD0 // FrameScript_GetTop
#define LUA_ISNUMBER_ADDR    0x0084DF20 // FrameScript_IsNumber
#define LUA_TYPE_ADDR        0x0084DEB0 // lua_type 
#define LUA_LOADBUFFER_ADDR  0x0084F860 // FrameScript_Load (luaL_loadbuffer)
#define LUA_GETFIELD_ADDR    0x0084E590 // WoW's lua_getfield implementation (Added based on user enum list)

// WoW Internal C Functions / Game API
#define WOW_CAST_SPELL_FUNC_ADDR 0x0080DA40 // CastLocalPlayerSpell address
#define LUA_GETSPELLINFO_ADDR    0x00540A30 // lua_GetSpellInfo (WoW's C function called by Lua)

// Static Game Data Addresses
#define COMBO_POINTS_ADDR      0x00BD084D // Static address for player combo points byte


// --- Typedefs ---
// WoW Specific
typedef void (__cdecl* lua_Execute_t)(const char* luaCode, const char* executionSource, int zero);

// Lua C API
typedef int(__cdecl* lua_pcall_t)(lua_State* L, int nargs, int nresults, int errfunc);
typedef double(__cdecl* lua_tonumber_t)(lua_State* L, int idx);
typedef void(__cdecl* lua_settop_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_gettop_t)(lua_State* L);
typedef const char*(__cdecl* lua_tolstring_t)(lua_State* L, int idx, size_t* len);
typedef void(__cdecl* lua_pushstring_t)(lua_State* L, const char* s);
typedef void(__cdecl* lua_pushinteger_t)(lua_State* L, int n);
typedef int(__cdecl* lua_tointeger_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_toboolean_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_isnumber_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_isstring_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_type_t)(lua_State* L, int idx);
typedef int (__cdecl* lua_loadbuffer_t)(lua_State *L, const char *buff, size_t sz, const char *name);
typedef void(__cdecl* lua_pushnil_t)(lua_State* L);
typedef void(__cdecl* lua_getfield_t)(lua_State* L, int idx, const char* k); 

// WoW Internal C Functions / Game API
typedef char (__cdecl* CastLocalPlayerSpell_t)(int spellId, int unknownIntArg, uint64_t targetGuid, char unknownCharArg);
typedef int (__cdecl* lua_GetSpellInfo_t)(lua_State* L); // WoW's C implementation


// --- Function Pointers ---
// WoW Specific
lua_Execute_t lua_Execute = (lua_Execute_t)WOW_LUA_EXECUTE;

// Lua C API
lua_pcall_t lua_pcall = (lua_pcall_t)LUA_PCALL_ADDR;
lua_tonumber_t lua_tonumber = (lua_tonumber_t)LUA_TONUMBER_ADDR;
lua_settop_t lua_settop = (lua_settop_t)LUA_SETTOP_ADDR;
lua_gettop_t lua_gettop = (lua_gettop_t)LUA_GETTOP_ADDR; 
lua_tolstring_t lua_tolstring = (lua_tolstring_t)LUA_TOLSTRING_ADDR;
lua_pushstring_t lua_pushstring = (lua_pushstring_t)LUA_PUSHSTRING_ADDR;
lua_pushinteger_t lua_pushinteger = (lua_pushinteger_t)LUA_PUSHINTEGER_ADDR;
lua_tointeger_t lua_tointeger = (lua_tointeger_t)LUA_TOINTEGER_ADDR;
lua_toboolean_t lua_toboolean = (lua_toboolean_t)LUA_TOBOOLEAN_ADDR;
lua_isnumber_t lua_isnumber = (lua_isnumber_t)LUA_ISNUMBER_ADDR;
lua_isstring_t lua_isstring = (lua_isstring_t)LUA_ISSTRING_ADDR; 
lua_type_t lua_type = (lua_type_t)LUA_TYPE_ADDR; 
lua_loadbuffer_t lua_loadbuffer = (lua_loadbuffer_t)LUA_LOADBUFFER_ADDR;
lua_pushnil_t lua_pushnil = (lua_pushnil_t)LUA_PUSHNIL_ADDR;
lua_getfield_t lua_getfield = (lua_getfield_t)LUA_GETFIELD_ADDR;

// WoW Internal C Functions / Game API
CastLocalPlayerSpell_t CastLocalPlayerSpell = (CastLocalPlayerSpell_t)WOW_CAST_SPELL_FUNC_ADDR;
lua_GetSpellInfo_t lua_GetSpellInfo = (lua_GetSpellInfo_t)LUA_GETSPELLINFO_ADDR;


// --- Helper Functions ---
lua_State* GetLuaState() {
    // Read the pointer value from the static address
    DWORD luaStatePtrValue = *(DWORD*)LUA_STATE_PTR_ADDR;
    char log_buf[128];
    sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] GetLuaState: Read pointer value 0x%X from address 0x%X\n", luaStatePtrValue, LUA_STATE_PTR_ADDR);
    OutputDebugStringA(log_buf);
    if (luaStatePtrValue == 0) {
        // Optionally log this only once or rarely
        OutputDebugStringA("[WoWInjectDLL] WARNING: Failed to read Lua State pointer value!\n");
        return nullptr;
    }
    return (lua_State*)luaStatePtrValue;
}


// --- Offsets & Constants --- 
#define D3D_PTR_1 0x00C5DF88
#define D3D_PTR_2 0x397C
#define D3D_ENDSCENE_VTABLE_OFFSET 0xA8 

#define LUA_GLOBALSINDEX -10002 // WoW's index for the global table (_G)

// --- Forward Declarations (Internal) --- 
void SetupHook();
void RemoveHook();
DWORD WINAPI IPCThread(LPVOID lpParam); 
void HandleIPCCommand(const std::string& command); 

// --- Hooked Function --- 
HRESULT WINAPI hkEndScene(LPDIRECT3DDEVICE9 pDevice) {
    if (g_bShutdown) {
        return oEndScene(pDevice); // Pass through if shutting down
    }

    // --- Process Queued Requests (Main Thread Execution Context) --- 
    std::vector<Request> requestsToProcess;
    {
        std::lock_guard<std::mutex> lock(g_queueMutex); // Lock queues
        // Move requests from global queue to local vector
        while (!g_requestQueue.empty()) {
            requestsToProcess.push_back(g_requestQueue.front());
            g_requestQueue.pop();
        }
    } // Mutex automatically unlocked

    // Process the requests that were dequeued
    if (!requestsToProcess.empty()) {
        char log_buffer[256];
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Processing %zu queued requests.\n", requestsToProcess.size());
        OutputDebugStringA(log_buffer);

        lua_State* L = GetLuaState(); // Get Lua state once per frame if needed

        for (const auto& req : requestsToProcess) {
            std::string response_str = ""; // Prepare for potential response

            // Check Lua state validity only if needed by *other* commands
            bool need_lua = (req.type == REQ_EXEC_LUA || req.type == REQ_GET_TIME_MS ||
                             req.type == REQ_GET_CD || req.type == REQ_IS_IN_RANGE ||
                             req.type == REQ_GET_SPELL_INFO); 
            bool need_cast_func = (req.type == REQ_CAST_SPELL);

            if (need_lua && !L) {
                OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state is NULL, cannot process Lua request!\n");
                // Determine appropriate error prefix based on request type
                if (req.type == REQ_EXEC_LUA) response_str = "LUA_RESULT:ERROR:Lua state null"; // Added for EXEC_LUA
                else if (req.type == REQ_GET_CD) response_str = "CD_ERR:Lua state null";
                else if (req.type == REQ_IS_IN_RANGE) response_str = "RANGE_ERR:Lua state null";
                else if (req.type == REQ_GET_SPELL_INFO) response_str = "SPELLINFO_ERR:Lua state null";
                // Add other error prefixes as needed
                else response_str = "ERROR:Lua state null";
            } else if (need_cast_func && !CastLocalPlayerSpell) {
                 OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - CastLocalPlayerSpell function pointer is NULL!\n");
                 response_str = "CAST_ERR:func null";
            } else {
                // Process request if Lua state is valid (or not needed) or cast func is valid
                switch (req.type) {
                    case REQ_PING:
                        OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing REQ_PING.\n");
                        response_str = "PONG"; // Standard ping response
                        break;

                    case REQ_EXEC_LUA:
                        // Ensure required function pointers are valid
                        if (L && lua_loadbuffer && lua_pcall && lua_gettop && lua_tolstring && lua_settop && lua_type && lua_isstring && !req.data.empty()) { 
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Executing Lua: [%.100s]...\n", req.data.c_str()); 
                                OutputDebugStringA(log_buffer);

                                int top_before_load = lua_gettop(L);
                                int load_status = lua_loadbuffer(L, req.data.c_str(), req.data.length(), "WowInjectDLL_Exec");

                                if (load_status == 0) { // Load successful, function is on stack
                                    // Call pcall with 0 arguments, expecting LUA_MULTRET (-1) return values.
                                    // The error handler index (0) means no error handler function.
                                    int pcall_status = lua_pcall(L, 0, -1, 0); // LUA_MULTRET = -1
                                    int results_count = lua_gettop(L) - top_before_load; // How many results are on the stack

                                    if (pcall_status == 0) { // pcall successful
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Lua pcall success. Results count: %d\n", results_count);
                                        OutputDebugStringA(log_buffer);

                                        std::stringstream ss_result;
                                        ss_result << "LUA_RESULT:"; // Start response prefix

                                        if (results_count > 0) {
                                            for (int i = 1; i <= results_count; ++i) {
                                                // Read result from stack (index 1 is the first result)
                                                // Stack index for the i-th result is (top_before_load + i)
                                                int stack_index = top_before_load + i;
                                                size_t len = 0;
                                                const char* str_val = nullptr;

                                                // Attempt to convert the result to string using lua_tolstring
                                                // lua_tolstring works for strings, numbers, booleans (as "true"/"false"), and nil (as "nil")
                                                if (lua_tolstring) {
                                                    str_val = lua_tolstring(L, stack_index, &len);
                                                }

                                                if (str_val) {
                                                    ss_result << std::string(str_val, len);
                                                } else {
                                                    // Fallback if lua_tolstring fails or is null
                                                    // We could use lua_type to provide a type name like "userdata", "function", etc.
                                                    int ltype = lua_type ? lua_type(L, stack_index) : -1;
                                                    sprintf_s(log_buffer, sizeof(log_buffer), "<Type:%d>", ltype);
                                                    ss_result << log_buffer;
                                                }

                                                // Add comma separator if not the last result
                                                if (i < results_count) {
                                                    ss_result << ",";
                                                }
                                            }
                                        } else {
                                             // No return values, result string remains "LUA_RESULT:"
                                        }
                                        response_str = ss_result.str(); // Set the final response string

                                    } else { // pcall failed
                                        // Error message is on the top of the stack
                                        const char* error_msg = "<Unknown pcall error>";
                                        if (lua_isstring && lua_tolstring && lua_isstring(L, -1)) { // Check if error message is string
                                            size_t len = 0;
                                            error_msg = lua_tolstring(L, -1, &len);
                                        }
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Lua pcall failed (%d): %s\n", pcall_status, error_msg ? error_msg : "(no message)");
                                        OutputDebugStringA(log_buffer);
                                        response_str = "LUA_RESULT:ERROR:pcall failed:"; // Send error back
                                        response_str += error_msg ? error_msg : "(no message)";
                                        results_count = 1; // Error message counts as one result on stack for cleanup
                                    }

                                    // Clean up the stack (remove results or error message)
                                    if (lua_settop) {
                                        lua_settop(L, top_before_load); // Restore stack top to before load
                                    }

                                } else { // Load failed
                                    // Error message is on the top of the stack
                                    const char* load_error_msg = "<Unknown load error>";
                                     if (lua_isstring && lua_tolstring && lua_isstring(L, -1)) { // Check if error message is string
                                        size_t len = 0;
                                        load_error_msg = lua_tolstring(L, -1, &len);
                                    }
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Lua loadbuffer failed (%d): %s\n", load_status, load_error_msg ? load_error_msg : "(no message)");
                                    OutputDebugStringA(log_buffer);
                                    response_str = "LUA_RESULT:ERROR:load failed:"; // Send error back
                                    response_str += load_error_msg ? load_error_msg : "(no message)";
                                    // Clean up stack (remove error message)
                                    if (lua_settop) {
                                        lua_settop(L, top_before_load);
                                    }
                                }

                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during lua load/pcall!\n");
                                response_str = "LUA_RESULT:ERROR:Crash during execution";
                                // Attempt to reset stack if possible?
                                if (L && lua_settop) lua_settop(L, 0); // Risky, might be invalid state
                            }
                        } else if (req.data.empty()){
                             OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Empty Lua code for REQ_EXEC_LUA!\n");
                             response_str = "LUA_RESULT:ERROR:Empty code";
                        } else { // Lua state or function pointers null
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for EXEC_LUA!\n");
                            response_str = "LUA_RESULT:ERROR:Lua state/funcs null";
                        }
                        break; // Response string is now set

                    case REQ_GET_TIME: // Keep old case for potential compatibility, but treat as MS
                    case REQ_GET_TIME_MS:
                        // Ensure required function pointers are valid
                        if (L && lua_loadbuffer && lua_pcall && lua_gettop && lua_isnumber && lua_tonumber && lua_settop) { 
                            try {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing REQ_GET_TIME_MS.\n");
                                int top_before = lua_gettop(L);
                                const char* luaCode = "local t = GetTime(); print('[DLL] GetTime() returned type:', type(t)); return t";
                                int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_GetTime");
                                
                                if (load_status == 0 && lua_gettop(L) > top_before) {
                                    if (lua_pcall(L, 0, 1, 0) == 0) { // Call GetTime(), 0 args, 1 result
                                        int result_type_c = lua_type ? lua_type(L, -1) : -1;
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: C API sees type ID %d at stack top.\n", result_type_c);
                                        OutputDebugStringA(log_buffer);

                                        if (lua_isnumber(L, -1)) { // Check if the result is actually a number
                                            double game_time_sec = lua_tonumber(L, -1); // Get result (seconds)
                                            long long game_time_ms = static_cast<long long>(game_time_sec * 1000.0);
                                            lua_settop(L, top_before); // Pop result (restore stack)

                                            char time_buf[64];
                                            sprintf_s(time_buf, sizeof(time_buf), "TIME:%lld", game_time_ms); 
                                            response_str = time_buf;
                                        } else {
                                            OutputDebugStringA("[WoWInjectDLL] GetTime: pcall result was not a number! Check game chat/logs for type.\n");
                                            lua_settop(L, top_before); // Pop non-number result (restore stack)
                                            response_str = "ERROR:GetTime result not number";
                                        }
                                    } else {
                                        const char* err_msg = lua_tolstring ? lua_tolstring(L, -1, NULL) : "(tolstring NULL)";
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: lua_pcall failed! Error: %s\n", err_msg ? err_msg : "(unknown)");
                                        OutputDebugStringA(log_buffer);
                                        lua_settop(L, -2); // Pop error message
                                        response_str = "ERROR:GetTime pcall failed";
                                    }
                                } else {
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: lua_loadbuffer failed with status %d.\n", load_status);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "ERROR:GetTime loadbuffer failed";
                                    lua_settop(L, top_before); // Ensure stack is clean
                                }
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during GetTime processing!\n");
                                response_str = "ERROR:GetTime crash";
                                if (L && lua_settop) lua_settop(L, 0); // Attempt to clear stack
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for GetTime!\n");
                            response_str = "ERROR:Lua state/funcs null";
                        }
                        break; 

                    case REQ_GET_CD:
                        // Ensure required function pointers are valid
                        if (L && lua_loadbuffer && lua_pushinteger && lua_pcall && lua_gettop && lua_isnumber && lua_tonumber && lua_tointeger && lua_settop && lua_tolstring) { 
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Processing REQ_GET_CD for spell %d.\n", req.spell_id);
                                OutputDebugStringA(log_buffer);

                                int top_before = lua_gettop(L);

                                const char* luaCode = "local spellIdArg = ...; return GetSpellCooldown(spellIdArg)";
                                int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_GetCD");

                                if (load_status == 0 && lua_gettop(L) > top_before) {
                                    lua_pushinteger(L, req.spell_id); 

                                    if (lua_pcall(L, 1, 3, 0) == 0) { 
                                        if (lua_isnumber(L, -3) && lua_isnumber(L, -2) && lua_isnumber(L, -1)) { 
                                            double start_sec = lua_tonumber(L, -3);
                                            double duration_sec = lua_tonumber(L, -2);
                                            int enabled = lua_tointeger(L, -1); 

                                            long long start_ms = static_cast<long long>(start_sec * 1000.0);
                                            long long duration_ms = static_cast<long long>(duration_sec * 1000.0);

                                            lua_settop(L, top_before); 

                                            char cd_buf[128];
                                            sprintf_s(cd_buf, sizeof(cd_buf), "CD:%lld,%lld,%d", start_ms, duration_ms, enabled);
                                            response_str = cd_buf;
                                        } else {
                                            OutputDebugStringA("[WoWInjectDLL] GetSpellCooldown: pcall result types invalid (expected num, num, num).\n");
                                            lua_settop(L, top_before); 
                                            response_str = "ERROR:GetSpellCooldown result types invalid";
                                        }
                                    } else {
                                        const char* errorMsg = lua_tolstring ? lua_tolstring(L, -1, NULL) : "(tolstring NULL)";
                                        char err_buf[256];
                                        sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] GetCD: lua_pcall failed! Error: %s\n", errorMsg ? errorMsg : "Unknown Lua error");
                                        OutputDebugStringA(err_buf);
                                        lua_settop(L, top_before); 
                                        response_str = "ERROR:pcall failed"; 
                                    }
                                } else {
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetCD: lua_loadbuffer failed with status %d.\n", load_status);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "ERROR:loadbuffer failed";
                                    lua_settop(L, top_before); 
                                }

                            } catch (const std::exception& e) {
                                std::string errorMsg = "[WoWInjectDLL] ERROR in GetCD processing (exception): ";
                                errorMsg += e.what();
                                errorMsg += "\n"; 
                                OutputDebugStringA(errorMsg.c_str());
                                response_str = "CD_ERR:crash";
                                if (L && lua_settop) lua_settop(L, 0); 
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] CRITICAL ERROR in GetCD processing: Memory access violation.\n");
                                response_str = "CD_ERR:crash";
                                if (L && lua_settop) lua_settop(L, 0); 
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for GetCD!\n");
                            response_str = "CD_ERR:Lua state/funcs null";
                        }
                        break;

                    case REQ_IS_IN_RANGE:
                        // Ensure required function pointers are valid
                        if (L && lua_loadbuffer && lua_pushinteger && lua_pushstring && lua_pcall && lua_gettop && lua_isnumber && lua_tointeger && lua_settop && lua_type && lua_tolstring && lua_GetSpellInfo && lua_pushnil) { 
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Processing REQ_IS_IN_RANGE for spell ID %d, unit '%s'.\n", req.spell_id, req.unit_id.c_str());
                                OutputDebugStringA(log_buffer);

                                int top_before = lua_gettop(L);
                                const char* spellName = nullptr;

                                // Get spell name using lua_GetSpellInfo C function
                                if (lua_GetSpellInfo) {
                                    lua_pushinteger(L, req.spell_id);
                                    int num_results_get_info = lua_GetSpellInfo(L); 
                                    // Name is expected at index 2 relative to stack base BEFORE the call + 1 (for the argument)
                                    // So, relative index is (top_before + 1) + 1 = top_before + 2
                                    if (num_results_get_info >= 1 && lua_type(L, top_before + 2) == 4) { 
                                        spellName = lua_tolstring(L, top_before + 2, NULL);
                                    } else {
                                         sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] lua_GetSpellInfo did not return a string name at index 2 (Type=%d)\n", lua_type(L, top_before + 2));
                                         OutputDebugStringA(log_buffer);
                                    }
                                    lua_settop(L, top_before); // Clean up stack from GetSpellInfo call
                                } else {
                                     OutputDebugStringA("[WoWInjectDLL] lua_GetSpellInfo pointer is NULL!\n");
                                }


                                if (spellName) {
                                    // Found spell name, now call IsSpellInRange via Lua chunk
                                    const char* luaCode = "local sName, uId = ...; return IsSpellInRange(sName, uId)";
                                    int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_RangeWithName");
                                    if (load_status == 0 && lua_gettop(L) > top_before) {
                                        lua_pushstring(L, spellName);           
                                        lua_pushstring(L, req.unit_id.c_str()); 
                                        if (lua_pcall(L, 2, 1, 0) == 0) {
                                            int result = -1;
                                            int result_type = lua_type(L, -1);
                                            if (result_type == 3) { // Number
                                                result = lua_tointeger(L, -1); 
                                            } else if (result_type == 0) { // Nil
                                                OutputDebugStringA("[WoWInjectDLL] IsSpellInRange returned nil. Likely invalid spell/unit/visibility.\n"); 
                                                result = 0; // Treat nil as false (0) for range check
                                            } else if (result_type == 1) { // Boolean (True=1, False=0)
                                                result = lua_toboolean(L, -1);
                                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsSpellInRange returned boolean: %d\n", result);
                                                OutputDebugStringA(log_buffer);
                                            } else { // Unexpected type
                                                 sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsSpellInRange returned unexpected type: %d\n", result_type);
                                                 OutputDebugStringA(log_buffer);
                                                 result = -1; // Indicate error 
                                            }
                                            lua_settop(L, top_before);
                                            char range_buf[64];
                                            sprintf_s(range_buf, sizeof(range_buf), "IN_RANGE:%d", result);
                                            response_str = range_buf;
                                        } else { 
                                            const char* errorMsg = lua_tolstring ? lua_tolstring(L, -1, NULL) : "(tolstring NULL)";
                                            sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsInRange: pcall failed! Error: %s\n", errorMsg ? errorMsg : "Unknown Lua error");
                                            OutputDebugStringA(log_buffer);
                                            lua_settop(L, top_before);
                                            response_str = "RANGE_ERR:pcall failed";
                                        }
                                    } else { 
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsInRange: loadbuffer failed with status %d.\n", load_status);
                                        OutputDebugStringA(log_buffer);
                                        response_str = "RANGE_ERR:loadbuffer failed";
                                        lua_settop(L, top_before);
                                    }

                                } else { 
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsInRange: Failed to get spell name for ID %d.\n", req.spell_id);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "RANGE_ERR:GetSpellInfo failed";
                                }

                            } catch (const std::exception& e) {
                                std::string errorMsg = "[WoWInjectDLL] ERROR in IsInRange processing (exception): ";
                                errorMsg += e.what(); errorMsg += "\n";
                                OutputDebugStringA(errorMsg.c_str());
                                response_str = "RANGE_ERR:crash";
                                if (L && lua_settop) lua_settop(L, 0);
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] CRITICAL ERROR in IsInRange processing: Memory access violation.\n");
                                response_str = "RANGE_ERR:crash";
                                if (L && lua_settop) lua_settop(L, 0);
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for IsInRange!\n");
                            response_str = "RANGE_ERR:Lua state/funcs null";
                        }
                        break;

                    case REQ_GET_SPELL_INFO:
                        // Ensure required function pointers are valid
                        if (L && lua_pushinteger && lua_GetSpellInfo && lua_gettop && lua_tolstring && lua_tonumber && lua_settop && lua_type && lua_isnumber && lua_tointeger) {
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Processing REQ_GET_SPELL_INFO for spell %d.\n", req.spell_id);
                                OutputDebugStringA(log_buffer);

                                int top_before = lua_gettop(L);
                                lua_pushinteger(L, req.spell_id);
                                int num_results = lua_GetSpellInfo(L); 

                                if (num_results > 0) { 
                                     // Indices relative to stack top AFTER GetSpellInfo call (which is top_before + num_results)
                                    // Name = index 2 => top_before + 2
                                    // Rank = index 3 => top_before + 3
                                    // Icon = index 4 => top_before + 4
                                    // Cost = index 5 => top_before + 5
                                    // PowerType = index 7 => top_before + 7
                                    // CastTime = index 8 => top_before + 8
                                    // MinRange = index 9 => top_before + 9
                                    // MaxRange = index 10 ? (Needs verification if it's returned)
                                    
                                    // Check if we got at least 9 results
                                    if (num_results >= 9) { 
                                        const char* name = (lua_type(L, top_before + 2) == 4) ? lua_tolstring(L, top_before + 2, NULL) : "N/A";
                                        const char* rank = (lua_type(L, top_before + 3) == 4) ? lua_tolstring(L, top_before + 3, NULL) : "N/A";
                                        const char* icon = (lua_type(L, top_before + 4) == 4) ? lua_tolstring(L, top_before + 4, NULL) : "N/A";
                                        double cost = lua_isnumber(L, top_before + 5) ? lua_tonumber(L, top_before + 5) : 0.0;       
                                        int powerType = lua_isnumber(L, top_before + 7) ? lua_tointeger(L, top_before + 7) : -1; 
                                        double castTime = lua_isnumber(L, top_before + 8) ? lua_tonumber(L, top_before + 8) : -1.0; 
                                        double minRange = lua_isnumber(L, top_before + 9) ? lua_tonumber(L, top_before + 9) : -1.0; 
                                        
                                        // Attempt to read potential maxRange at index 10
                                        double maxRange = -1.0;
                                        if (num_results >= 10 && lua_isnumber(L, top_before + 10)) {
                                            maxRange = lua_tonumber(L, top_before + 10);
                                        } else {
                                            sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetSpellInfo: MaxRange (index 10) not found or not number (Type=%d). Num results=%d\n", lua_type(L, top_before + 10), num_results);
                                            OutputDebugStringA(log_buffer);
                                        }

                                        char info_buf[1024];
                                        sprintf_s(info_buf, sizeof(info_buf), "SPELLINFO:%s,%s,%.0f,%.1f,%.1f,%s,%.0f,%d",
                                                  (name && strlen(name) > 0) ? name : "N/A",
                                                  (rank && strlen(rank) > 0) ? rank : "N/A",
                                                  castTime,
                                                  minRange,
                                                  maxRange, // Now potentially holds a value
                                                  (icon && strlen(icon) > 0) ? icon : "N/A",
                                                  cost,
                                                  powerType);
                                        response_str = info_buf;
                                    } else {
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetSpellInfo did not return enough results (returned %d, expected >= 9) for spell %d.\n", num_results, req.spell_id);
                                        OutputDebugStringA(log_buffer);
                                        response_str = "SPELLINFO_ERR:GetSpellInfo failed (results)";
                                    }
                                    lua_settop(L, top_before); // Clean up stack

                                } else {
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetSpellInfo did not return any results (returned %d) for spell %d.\n", num_results, req.spell_id);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "SPELLINFO_ERR:GetSpellInfo failed (no results)";
                                }

                            } catch (const std::exception& e) {
                                std::string errorMsg = "[WoWInjectDLL] ERROR in GetSpellInfo processing (exception): ";
                                errorMsg += e.what();
                                errorMsg += "\n";
                                OutputDebugStringA(errorMsg.c_str());
                                response_str = "SPELLINFO_ERR:crash";
                                if (L && lua_settop) lua_settop(L, 0);
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] CRITICAL ERROR in GetSpellInfo processing: Memory access violation.\n");
                                response_str = "SPELLINFO_ERR:crash";
                                if (L && lua_settop) lua_settop(L, 0);
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for GetSpellInfo!\n");
                            response_str = "SPELLINFO_ERR:Lua state/funcs null";
                        }
                        break;

                    case REQ_CAST_SPELL:
                        // Ensure CastLocalPlayerSpell pointer is valid
                        if (CastLocalPlayerSpell) {
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Attempting cast SpellID: %d, TargetGUID: 0x%llX\n", req.spell_id, req.target_guid);
                                OutputDebugStringA(log_buffer);

                                // Call the function: CastLocalPlayerSpell(spellId, unknownIntArg=0, targetGuid, unknownCharArg=0)
                                char result = CastLocalPlayerSpell(req.spell_id, 0, req.target_guid, 0);

                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] CastLocalPlayerSpell returned: %d\n", (int)result);
                                OutputDebugStringA(log_buffer);

                                // Send simple confirmation response
                                char cast_resp_buf[64];
                                // Corrected format: Should be CAST_RESULT based on Python expectation
                                sprintf_s(cast_resp_buf, sizeof(cast_resp_buf), "CAST_RESULT:%d,%d", req.spell_id, (int)result); 
                                response_str = cast_resp_buf;

                            } catch (const std::exception& e) {
                                std::string errorMsg = "[WoWInjectDLL] ERROR during CastSpell call (exception): ";
                                errorMsg += e.what(); errorMsg += "\n";
                                OutputDebugStringA(errorMsg.c_str());
                                response_str = "CAST_RESULT:ERROR:crash"; // Match prefix
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] CRITICAL ERROR during CastSpell call: Memory access violation.\n");
                                response_str = "CAST_RESULT:ERROR:crash"; // Match prefix
                            }
                        } else {
                             OutputDebugStringA("[WoWInjectDLL] ERROR: CastLocalPlayerSpell function pointer is NULL!\n");
                             response_str = "CAST_RESULT:ERROR:func null"; // Match prefix
                        }
                        break;

                    case REQ_GET_COMBO_POINTS:
                        OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing REQ_GET_COMBO_POINTS (Memory Read).\n");
                        try {
                            // Directly read the byte from the static address
                            unsigned char comboPoints = *(reinterpret_cast<unsigned char*>(COMBO_POINTS_ADDR));

                            if (comboPoints > 5) { 
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Warning: Read combo point value %u, which is > 5. Assuming 0.\n", comboPoints);
                                OutputDebugStringA(log_buffer);
                                comboPoints = 0; 
                            }

                            char cp_buf[64];
                            sprintf_s(cp_buf, sizeof(cp_buf), "CP:%d", static_cast<int>(comboPoints));
                            response_str = cp_buf;

                        } catch (const std::exception& e) {
                            std::string errorMsg = "[WoWInjectDLL] ERROR reading combo point memory (exception): ";
                            errorMsg += e.what(); errorMsg += "\n";
                            OutputDebugStringA(errorMsg.c_str());
                            response_str = "CP:-98"; 
                        } catch (...) {
                            OutputDebugStringA("[WoWInjectDLL] CRITICAL ERROR reading combo point memory: Access violation.\n");
                            response_str = "CP:-99"; 
                        }
                        break;

                    default:
                        OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing UNKNOWN request type!\n");
                        response_str = "ERROR:Unknown request";
                        break;
                } // End switch
            } // End if (!response_str.empty()) // Check if error response already set

            // If a response was generated, queue it for the IPC thread
            if (!response_str.empty()) {
                 std::lock_guard<std::mutex> lock(g_queueMutex); // Lock queues
                 g_responseQueue.push(response_str);
            }
        } // End loop through requests
    }

    // --- Other per-frame logic (e.g., ImGui rendering) would go here --- 

    // Call the original EndScene
    return oEndScene(pDevice);
}

// --- DLL Entry Point --- 
BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
        case DLL_PROCESS_ATTACH:
            DisableThreadLibraryCalls(hModule);
            g_hModule = hModule; 
            g_bShutdown = false;
            // Create the IPC thread first
            g_hIPCThread = CreateThread(nullptr, 0, IPCThread, hModule, 0, nullptr);
            if (!g_hIPCThread) {
                OutputDebugStringA("[WoWInjectDLL] Failed to create IPC thread!\n");
                return FALSE; 
            }
            // Now setup the hook
            SetupHook(); 
            break;
        case DLL_THREAD_ATTACH:
        case DLL_THREAD_DETACH:
            break;
        case DLL_PROCESS_DETACH:
            g_bShutdown = true; // Signal threads to shutdown
            RemoveHook();
            
            // Cleanly shutdown the named pipe (signal the server thread)
             const WCHAR* pipeNameToSignal = L"\\\\.\\pipe\\WowInjectPipe"; 
             HANDLE hDummyClient = CreateFileW(
                 pipeNameToSignal, 
                 GENERIC_WRITE, 
                 0, NULL, OPEN_EXISTING, 0, NULL);

             if (hDummyClient != INVALID_HANDLE_VALUE) {
                  OutputDebugStringA("[WoWInjectDLL] Signalling pipe server thread to exit ConnectNamedPipe wait...\n");
                  CloseHandle(hDummyClient); 
             } else {
                 DWORD error = GetLastError();
                 if (error != ERROR_PIPE_BUSY && error != ERROR_FILE_NOT_FOUND) { 
                    char error_buf[150];
                    sprintf_s(error_buf, sizeof(error_buf), "[WoWInjectDLL] CreateFileW to signal pipe failed unexpectedly. Error: %lu\n", error);
                    OutputDebugStringA(error_buf);
                 }
             }
            
            // Wait for the IPC thread to terminate
            if (g_hIPCThread) {
                 OutputDebugStringA("[WoWInjectDLL] Waiting for IPC thread to terminate...\n");
                 WaitForSingleObject(g_hIPCThread, 5000); 
                 CloseHandle(g_hIPCThread);
                 g_hIPCThread = nullptr;
                 OutputDebugStringA("[WoWInjectDLL] IPC thread terminated.\n");
            }
            OutputDebugStringA("[WoWInjectDLL] Detached.\n");
            break;
    }
    return TRUE;
}

// --- Hook Setup/Removal Implementations --- 

void SetupHook() {
    try {
        DWORD base_ptr_val = *(reinterpret_cast<DWORD*>(D3D_PTR_1)); 
        if (!base_ptr_val) throw std::runtime_error("Failed to read base_ptr");
        DWORD pDevice_val = *(reinterpret_cast<DWORD*>(base_ptr_val + D3D_PTR_2));
        if (!pDevice_val) throw std::runtime_error("Failed to read pDevice");
        DWORD pVTable_val = *(reinterpret_cast<DWORD*>(pDevice_val));
        if (!pVTable_val) throw std::runtime_error("Failed to read pVTable");
        DWORD endSceneAddr = *(reinterpret_cast<DWORD*>(pVTable_val + D3D_ENDSCENE_VTABLE_OFFSET));
        if (!endSceneAddr) throw std::runtime_error("Failed to read EndScene address");

        oEndScene = (EndScene_t)endSceneAddr;
        
        char buffer[100];
        sprintf_s(buffer, sizeof(buffer), "[WoWInjectDLL] Found EndScene address: 0x%X\n", endSceneAddr);
        OutputDebugStringA(buffer);

        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());
        DetourAttach(&(PVOID&)oEndScene, hkEndScene);
        LONG error = DetourTransactionCommit();

        if (error == NO_ERROR) {
            OutputDebugStringA("[WoWInjectDLL] EndScene hook attached successfully.\n");
        } else {
             sprintf_s(buffer, sizeof(buffer), "[WoWInjectDLL] Detours failed to attach hook, error: %ld\n", error);
             OutputDebugStringA(buffer);
             oEndScene = nullptr; 
        }

    } catch (const std::exception& e) {
        std::string errorMsg = "[WoWInjectDLL] ERROR in SetupHook (exception): ";
        errorMsg += e.what();
        errorMsg += "\n"; 
        OutputDebugStringA(errorMsg.c_str());
        oEndScene = nullptr; 
    } catch (...) {
        OutputDebugStringA("[WoWInjectDLL] CRITICAL ERROR in SetupHook: Memory access violation.\n");
         oEndScene = nullptr; 
    }
}

void RemoveHook() {
    if (oEndScene == nullptr) {
        OutputDebugStringA("[WoWInjectDLL] RemoveHook: Hook not attached or already removed.\n");
        return; 
    }
    OutputDebugStringA("[WoWInjectDLL] Removing EndScene hook...\n");
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourDetach(&(PVOID&)oEndScene, hkEndScene);
    DetourTransactionCommit();
    OutputDebugStringA("[WoWInjectDLL] EndScene hook detached.\n");
    oEndScene = nullptr; 
}

// --- IPC Thread Implementation (Named Pipe Server) --- 

DWORD WINAPI IPCThread(LPVOID lpParam) {
    OutputDebugStringA("[WoWInjectDLL] IPC Thread started.\n");
    char buffer[1024 * 4]; // 4KB buffer
    DWORD bytesRead;
    BOOL success;

    g_hPipe = CreateNamedPipeW(
        L"\\\\.\\pipe\\WowInjectPipe",      
        PIPE_ACCESS_DUPLEX,            
        PIPE_TYPE_MESSAGE |            
        PIPE_READMODE_MESSAGE |        
        PIPE_WAIT,                     
        1,                             
        sizeof(buffer),                
        sizeof(buffer),                
        0,                             
        NULL);                         

    if (g_hPipe == INVALID_HANDLE_VALUE) {
        DWORD lastError = GetLastError();
        char err_buf[128];
        sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] Failed to create named pipe! GLE=%lu\n", lastError);
        OutputDebugStringA(err_buf);
        return 1;
    }
    OutputDebugStringA("[WoWInjectDLL] Pipe created. Entering main connection loop.\n");

    // Outer loop to wait for connections repeatedly
    while (!g_bShutdown) 
    { 
        OutputDebugStringA("[WoWInjectDLL] Waiting for client connection...\n");
        BOOL connected = ConnectNamedPipe(g_hPipe, NULL); 
        if (!connected && GetLastError() != ERROR_PIPE_CONNECTED) 
        {
            char err_buf[128];
            sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] ConnectNamedPipe failed. GLE=%d\n", GetLastError());
            OutputDebugStringA(err_buf);
            continue; 
        }
        if (g_bShutdown) break;

        OutputDebugStringA("[WoWInjectDLL] Client connected. Entering communication loop.\n");

        // Inner Communication Loop
        while (!g_bShutdown) 
        { 
            // Read Command
            success = ReadFile(
                g_hPipe,
                buffer,
                sizeof(buffer) - 1, 
                &bytesRead,
                NULL);

            if (!success || bytesRead == 0) {
                if (GetLastError() == ERROR_BROKEN_PIPE) {
                    OutputDebugStringA("[WoWInjectDLL] Client disconnected (Broken Pipe).\n");
                } else {
                    char err_buf[128];
                    sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] ReadFile failed. GLE=%d\n", GetLastError());
                    OutputDebugStringA(err_buf);
                }
                 break; 
            }

            buffer[bytesRead] = '\0'; 
            std::string command(buffer);
            char log_buf[256];
            sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] IPC Received Raw: [%s]\n", command.c_str());
            OutputDebugStringA(log_buf);

            // Handle the received command
            HandleIPCCommand(command);

            // Wait for and Send Response (Polling)
            std::string responseToSend = "";
            bool responseFound = false;
            for (int i = 0; i < 10; ++i) { 
                {
                    std::lock_guard<std::mutex> lock(g_queueMutex);
                    if (!g_responseQueue.empty()) {
                        responseToSend = g_responseQueue.front();
                        g_responseQueue.pop();
                        responseFound = true;
                        break; 
                    }
                }
                if (g_bShutdown) break; 
                Sleep(10); 
            }

            if (!responseFound && !g_bShutdown) {
                // Log warning if no response generated (except for EXEC_LUA without results)
                bool isExecLua = command.rfind("EXEC_LUA:", 0) == 0;
                bool hasLuaResult = !responseToSend.empty() && responseToSend.rfind("LUA_RESULT:", 0) == 0 && responseToSend.length() > 11; // Check if LUA_RESULT: has content

                if (!isExecLua || (isExecLua && !hasLuaResult)) { // Log if not EXEC_LUA OR if it is EXEC_LUA but has no result content
                     sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] IPC WARNING: No response generated/found for command [%.50s] within timeout.\n", command.c_str());
                     OutputDebugStringA(log_buf);
                }
            } 

            if (!responseToSend.empty()) {
                DWORD bytesWritten;
                success = WriteFile(
                    g_hPipe,
                    responseToSend.c_str(),
                    responseToSend.length() + 1, // Include null terminator
                    &bytesWritten,
                    NULL);
                
                if (!success || bytesWritten != (responseToSend.length() + 1)) {
                    char err_buf[128];
                    sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] WriteFile failed for response. GLE=%d\n", GetLastError());
                    OutputDebugStringA(err_buf);
                    break; 
                } else {
                     sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] Sent response: [%.100s]...\n", responseToSend.c_str());
                     OutputDebugStringA(log_buf);
                     if (!FlushFileBuffers(g_hPipe)) {
                         sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] FlushFileBuffers failed. GLE=%d\n", GetLastError());
                         OutputDebugStringA(log_buf);
                     }
                }
            } 
        } // End inner communication loop

        // Client disconnected or error occurred
        OutputDebugStringA("[WoWInjectDLL] Client disconnected or communication loop ended. Disconnecting server side.\n");
        if (!DisconnectNamedPipe(g_hPipe)) 
        {
            char err_buf[128];
            sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] DisconnectNamedPipe failed. GLE=%d\n", GetLastError());
            OutputDebugStringA(err_buf);
        }

    } // End outer connection loop

    // Cleanup when g_bShutdown becomes true
    OutputDebugStringA("[WoWInjectDLL] IPC Thread exiting due to shutdown signal. Closing pipe handle.\n");
    if (g_hPipe != INVALID_HANDLE_VALUE) {
        DisconnectNamedPipe(g_hPipe); 
        CloseHandle(g_hPipe);
        g_hPipe = INVALID_HANDLE_VALUE;
    }
    return 0;
}

// Parses command string and queues a request for the main thread
void HandleIPCCommand(const std::string& command) {
    Request req;
    char log_buffer[256];

    if (command == "ping") {
        req.type = REQ_PING;
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type PING.\n");
    } else if (command == "GET_TIME_MS") {
        req.type = REQ_GET_TIME_MS;
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type GET_TIME_MS.\n");
    } else if (command == "GET_COMBO_POINTS") { 
         req.type = REQ_GET_COMBO_POINTS;
         sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type GET_COMBO_POINTS.\n");
    } else if (command.rfind("EXEC_LUA:", 0) == 0) {
        req.type = REQ_EXEC_LUA;
        req.data = command.substr(9);
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type EXEC_LUA. Data size: %zu\n", req.data.length());
    } else if (sscanf_s(command.c_str(), "GET_CD:%d", &req.spell_id) == 1) {
        req.type = REQ_GET_CD;
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type GET_CD. SpellID: %d\n", req.spell_id);
    } else if (sscanf_s(command.c_str(), "GET_SPELL_INFO:%d", &req.spell_id) == 1) {
        req.type = REQ_GET_SPELL_INFO;
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type GET_SPELL_INFO. SpellID: %d\n", req.spell_id);
    } else {
        char unit_id_buf[33] = {0};
        if (sscanf_s(command.c_str(), "IS_IN_RANGE:%d,%32s", &req.spell_id, unit_id_buf, (unsigned)_countof(unit_id_buf)) == 2) {
             req.type = REQ_IS_IN_RANGE;
             req.unit_id = unit_id_buf;
             req.spell_name.clear(); 
             sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type IS_IN_RANGE. SpellID: %d, UnitID: %s\n", req.spell_id, req.unit_id.c_str());
        } else {
            if (sscanf_s(command.c_str(), "CAST_SPELL:%d", &req.spell_id) == 1) {
                 req.type = REQ_CAST_SPELL;
                 req.target_guid = 0; 
                 sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type CAST_SPELL. SpellID: %d, TargetGUID: 0\n", req.spell_id);
            }
            else if (sscanf_s(command.c_str(), "CAST_SPELL:%d,%llu", &req.spell_id, &req.target_guid) == 2) {
                 req.type = REQ_CAST_SPELL;
                 sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type CAST_SPELL. SpellID: %d, TargetGUID: %llu (0x%llX)\n", req.spell_id, req.target_guid, req.target_guid);
            }
            else {
                req.type = REQ_UNKNOWN;
                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Unknown command received: [%.100s]\n", command.c_str());
                req.data = command;
            }
        }
    } 
    OutputDebugStringA(log_buffer);

    // Queue the request
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        g_requestQueue.push(req);
    }
} 