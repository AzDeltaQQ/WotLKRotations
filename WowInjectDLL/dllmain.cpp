// dllmain.cpp : Defines the entry point for the DLL application.
#include "pch.h"
#include <iostream> // For debug output if needed
#include <queue>    // For command queue
#include <mutex>    // For thread safety
#include <string>   // For command strings
#include <vector>   // For processing dequeued commands
#include <chrono>   // For basic timing/sleep in IPC response wait
#include <cstdio>   // For sscanf

// Explicitly define EndScene_t function pointer type here
typedef HRESULT(WINAPI* EndScene_t)(LPDIRECT3DDEVICE9 pDevice);

// --- Forward Declarations for Lua ---
struct lua_State; // Opaque Lua state type

// --- Globals --- 
EndScene_t oEndScene = nullptr; // Original EndScene function pointer
HMODULE g_hModule = nullptr; // Store the module handle for the DLL
HANDLE g_hPipe = INVALID_HANDLE_VALUE; // Handle for the named pipe
HANDLE g_hIPCThread = nullptr;      // Handle for the IPC thread
volatile bool g_bShutdown = false;   // Flag to signal shutdown

// --- Request/Response Queues & Types ---
enum RequestType {
    REQ_UNKNOWN,
    REQ_EXEC_LUA,
    REQ_GET_TIME,         // Deprecated, use GET_TIME_MS
    REQ_GET_TIME_MS,      // New: Get time in milliseconds
    REQ_GET_CD,           // New: Get spell cooldown
    REQ_IS_IN_RANGE,      // New: Check spell range
    REQ_PING              // New: Simple ping request
};

struct Request {
    RequestType type = REQ_UNKNOWN;
    std::string data;     // For Lua code
    int spell_id = 0;     // For spell-related commands
    std::string unit_id;  // For target unit
    // Could add more fields like item_id later
};

std::queue<Request> g_requestQueue;      // Commands from Python -> Main Thread
std::queue<std::string> g_responseQueue; // Results from Main Thread -> Python
std::mutex g_queueMutex;                 // Mutex protecting BOTH queues

// --- WoW Function Definitions & Pointers --- 
// Address for WoW 3.3.5a (12340)
#define WOW_LUA_EXECUTE 0x00819210
// Function Signature (__cdecl calling convention)
typedef void (__cdecl* lua_Execute_t)(const char* luaCode, const char* executionSource, int zero);
// Global variable to hold the function pointer
lua_Execute_t lua_Execute = (lua_Execute_t)WOW_LUA_EXECUTE;

// Lua C API Functions (Corrected addresses for 3.3.5a Build 12340 based on user input)
// NOTE: Calling conventions assumed to be __cdecl, verify if necessary
#define LUA_STATE_PTR_ADDR 0x00D3F78C // Correct address holding the pointer to lua_State for 3.3.5a (12340)
#define LUA_PCALL_ADDR     0x0084EC50 // FrameScript_PCall
#define LUA_TONUMBER_ADDR  0x0084E030 // FrameScript_ToNumber
#define LUA_SETTOP_ADDR    0x0084DBF0 // FrameScript__SetTop
#define LUA_TOLSTRING_ADDR 0x0084E0E0 // FrameScript_ToLString
#define LUA_PUSHSTRING_ADDR 0x0084E350 // FrameScript_PushString
#define LUA_GETGLOBAL_ADDR 0x00818010 // WoW helper: FrameScript_GetGlobal(L, name)
#define LUA_PUSHINTEGER_ADDR 0x0084E2D0 // FrameScript_PushInteger
#define LUA_TOINTEGER_ADDR 0x0084E070 // FrameScript_ToInteger
#define LUA_TOBOOLEAN_ADDR 0x0044E2C0 // FrameScript_ToBoolean (Matches FrameScript list)
#define LUA_ISNUMBER_ADDR 0x0084DF20 // FrameScript__IsNumber (From User List)
#define LUA_ISBOOLEAN_ADDR 0x0084DFA0 // FrameScript_IsBoolean (Not in lists, assumed correct for now)

#define LUA_GLOBALSINDEX -10002 // WoW's index for the global table (_G)

// Renamed typedefs
typedef int(__cdecl* lua_pcall_t)(lua_State* L, int nargs, int nresults, int errfunc);
typedef double(__cdecl* lua_tonumber_t)(lua_State* L, int idx);
typedef void(__cdecl* lua_settop_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_gettop_t)(lua_State* L); // Added lua_gettop typedef
typedef const char*(__cdecl* lua_tolstring_t)(lua_State* L, int idx, size_t* len);
typedef void(__cdecl* lua_pushstring_t)(lua_State* L, const char* s);
typedef void(__cdecl* lua_getglobal_t)(lua_State* L, const char* name); // FrameScript_GetGlobal
typedef void(__cdecl* lua_pushinteger_t)(lua_State* L, int n);
typedef int(__cdecl* lua_tointeger_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_toboolean_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_isnumber_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_isboolean_t)(lua_State* L, int idx);

// --- ADDED: Type checking functions ---
typedef int(__cdecl* lua_type_t)(lua_State* L, int idx);

// --- ADDED: Signature for FrameScript_Load (0x0084F860) ---
// Returns 0 on success, pushes chunk function onto stack
typedef int (__cdecl* lua_loadbuffer_t)(lua_State *L, const char *buff, size_t sz, const char *name);

// Renamed function pointers
lua_pcall_t lua_pcall = (lua_pcall_t)LUA_PCALL_ADDR;
lua_tonumber_t lua_tonumber = (lua_tonumber_t)LUA_TONUMBER_ADDR;
lua_settop_t lua_settop = (lua_settop_t)LUA_SETTOP_ADDR;
lua_gettop_t lua_gettop = (lua_gettop_t)0x0084DBD0; // Added lua_gettop pointer (Address from FrameScript_GetTop)
lua_tolstring_t lua_tolstring = (lua_tolstring_t)LUA_TOLSTRING_ADDR;
lua_pushstring_t lua_pushstring = (lua_pushstring_t)LUA_PUSHSTRING_ADDR;
lua_getglobal_t lua_getglobal = (lua_getglobal_t)LUA_GETGLOBAL_ADDR;
lua_pushinteger_t lua_pushinteger = (lua_pushinteger_t)LUA_PUSHINTEGER_ADDR;
lua_tointeger_t lua_tointeger = (lua_tointeger_t)LUA_TOINTEGER_ADDR;
lua_toboolean_t lua_toboolean = (lua_toboolean_t)LUA_TOBOOLEAN_ADDR;
lua_isnumber_t lua_isnumber = (lua_isnumber_t)LUA_ISNUMBER_ADDR;
lua_isboolean_t lua_isboolean = (lua_isboolean_t)LUA_ISBOOLEAN_ADDR;

// --- ADDED: Pointers for type checking ---
lua_type_t lua_type = (lua_type_t)0x0084DEB0; // From User C# List

// --- ADDED: Pointer for FrameScript_Load ---
lua_loadbuffer_t lua_loadbuffer = (lua_loadbuffer_t)0x0084F860;

// Helper to get Lua state
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


// --- Offsets --- 
#define D3D_PTR_1 0x00C5DF88
#define D3D_PTR_2 0x397C
#define D3D_ENDSCENE_VTABLE_OFFSET 0xA8 

// --- Forward Declarations --- 
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

            // Check Lua state validity for commands that need it
            bool need_lua = (req.type == REQ_EXEC_LUA || req.type == REQ_GET_TIME_MS || req.type == REQ_GET_CD || req.type == REQ_IS_IN_RANGE);
            if (need_lua && !L) {
                OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state is NULL, cannot process Lua request!\n");
                response_str = "ERROR:Lua state null";
                // Still need to push the response
            } else {
                // Process request if Lua state is valid (or not needed)
                switch (req.type) {
                    case REQ_PING:
                        OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing REQ_PING.\n");
                        response_str = "PONG"; // Standard ping response
                        break;

                    case REQ_EXEC_LUA:
                        if (lua_Execute && !req.data.empty()) { 
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Executing Lua: [%.100s]...\n", req.data.c_str()); 
                                OutputDebugStringA(log_buffer);
                                lua_Execute(req.data.c_str(), "WowInjectDLL", 0); // Use lua_Execute
                                // No response needed for EXEC_LUA
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during lua_Execute!\n");
                            }
                        } else if (req.data.empty()){
                             OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Empty Lua code for REQ_EXEC_LUA!\n");
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - lua_Execute function pointer is null!\n");
                        }
                        break; // No response for EXEC_LUA

                    case REQ_GET_TIME: // Keep old case for potential compatibility, but treat as MS
                    case REQ_GET_TIME_MS:
                        if (L && lua_loadbuffer && lua_pcall && lua_gettop && lua_tonumber && lua_settop) { 
                            try {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing REQ_GET_TIME_MS.\n");
                                int top_before = lua_gettop(L);
                                const char* luaCode = "local t = GetTime(); print('[DLL] GetTime() returned type:', type(t)); return t";
                                int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_GetTime");
                                
                                if (load_status == 0 && lua_gettop(L) > top_before) {
                                    if (lua_pcall(L, 0, 1, 0) == 0) { // Call GetTime(), 0 args, 1 result
                                        // --- ADDED: C-API Type Logging ---
                                        int result_type_c = -1; // Default invalid type
                                        if (lua_type) { // Check if lua_type pointer is valid
                                            result_type_c = lua_type(L, -1); // Get type of value at top of stack
                                            sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: C API sees type ID %d at stack top.\n", result_type_c);
                                            OutputDebugStringA(log_buffer);
                                        }
                                        // --- End Modified Logging ---

                                        if (lua_isnumber(L, -1)) { // Check if the result is actually a number
                                            double game_time_sec = lua_tonumber(L, -1); // Get result (seconds)
                                            long long game_time_ms = static_cast<long long>(game_time_sec * 1000.0);
                                            lua_settop(L, top_before); // Pop result (restore stack)

                                            // Format response string: "TIME:<milliseconds>"
                                            char time_buf[64];
                                            sprintf_s(time_buf, sizeof(time_buf), "TIME:%lld", game_time_ms); 
                                            response_str = time_buf;
                                        } else {
                                            OutputDebugStringA("[WoWInjectDLL] GetTime: pcall result was not a number! Check game chat/logs for type.\n");
                                            lua_settop(L, top_before); // Pop non-number result (restore stack)
                                            response_str = "ERROR:GetTime result not number";
                                        }
                                    } else {
                                        const char* err_msg = lua_tolstring(L, -1, NULL);
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: lua_pcall failed! Error: %s\n", err_msg ? err_msg : "(unknown)");
                                        OutputDebugStringA(log_buffer);
                                        lua_settop(L, -2); // Pop error message
                                        response_str = "ERROR:GetTime pcall failed";
                                    }
                                } else {
                                    // loadbuffer failed
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: lua_loadbuffer failed with status %d.\n", load_status);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "ERROR:GetTime loadbuffer failed";
                                    lua_settop(L, top_before); // Ensure stack is clean
                                }
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during GetTime processing!\n");
                                response_str = "ERROR:GetTime crash";
                                if (L) lua_settop(L, 0); // Attempt to clear stack
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for GetTime!\n");
                            response_str = "ERROR:Lua state/funcs null";
                        }
                        break; 

                    case REQ_GET_CD:
                        if (L && lua_loadbuffer && lua_pcall && lua_gettop && lua_tonumber && lua_settop && lua_isnumber && lua_isboolean && lua_toboolean) {
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Processing REQ_GET_CD for spell %d.\n", req.spell_id);
                                OutputDebugStringA(log_buffer);
                                int top_before = lua_gettop(L);

                                // Construct Lua code: "local s,d,e = GetSpellCooldown(...); return s,d,e"
                                char luaCode[128];
                                sprintf_s(luaCode, sizeof(luaCode), "local s,d,e = GetSpellCooldown(%d); return s,d,e", req.spell_id);
                                
                                int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_GetCD");
                                
                                if (load_status == 0 && lua_gettop(L) > top_before) {
                                    if (lua_pcall(L, 0, 3, 0) == 0) { // Call GetSpellCooldown(), 0 args, 3 results
                                        // Check stack top to ensure we got 3 results (or fewer if spell invalid)
                                        int top_after = lua_gettop(L);
                                        int results_count = top_after - top_before;

                                        long long start_ms = 0;
                                        long long duration_ms = 0;
                                        int enabled_int = 0; // 0=on cooldown, 1=ready (or invalid spell)
                                        bool success = true;

                                        // GetSpellCooldown returns: startTime, duration, enabled
                                        // Stack indices are relative to top: -3, -2, -1

                                        // Enabled (Top, index -1)
                                        if (results_count >= 1 && lua_isboolean(L, -1)) { // 3rd return val is boolean 'enabled' (1 if ready)
                                            enabled_int = lua_toboolean(L, -1);
                                        } else if (results_count >= 1) { // If not boolean, likely nil (spell invalid or no cooldown) -> treat as ready
                                            enabled_int = 1; // Default to ready if not boolean
                                        } else {
                                            success = false; // Not enough results
                                        }

                                        // Duration (Index -2)
                                        if (success && results_count >= 2 && lua_isnumber(L, -2)) {
                                            duration_ms = static_cast<long long>(lua_tonumber(L, -2));
                                        } else if (success && results_count >= 2) {
                                             // Not a number, invalid cooldown? Set duration to 0.
                                             duration_ms = 0;
                                        } else if (results_count < 2) {
                                            success = false;
                                        }

                                        // Start Time (Index -3)
                                        if (success && results_count >= 3 && lua_isnumber(L, -3)) {
                                            start_ms = static_cast<long long>(lua_tonumber(L, -3));
                                        } else if (success && results_count >= 3) {
                                             // Not a number, invalid cooldown? Set start to 0.
                                             start_ms = 0;
                                        } else if (results_count < 3) {
                                            success = false;
                                        }

                                        // Pop all results regardless of success
                                        lua_settop(L, top_before); 

                                        if (success) {
                                            // Format response string: "CD:<start_ms>,<duration_ms>,<enabled_int>"
                                            char cd_buf[128];
                                            sprintf_s(cd_buf, sizeof(cd_buf), "CD:%lld,%lld,%d", start_ms, duration_ms, enabled_int);
                                            response_str = cd_buf;
                                        } else {
                                            OutputDebugStringA("[WoWInjectDLL] GetCD: Failed to parse pcall results correctly.\n");
                                            response_str = "CD_ERR:Result parse failed";
                                        }
                                    } else {
                                        const char* err_msg = lua_tolstring(L, -1, NULL);
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetCD: lua_pcall failed! Error: %s\n", err_msg ? err_msg : "(unknown)");
                                        OutputDebugStringA(log_buffer);
                                        lua_settop(L, -2); // Pop error message
                                        response_str = "CD_ERR:pcall failed";
                                    }
                                } else {
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetCD: lua_loadbuffer failed with status %d.\n", load_status);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "CD_ERR:loadbuffer failed";
                                    lua_settop(L, top_before); // Ensure stack is clean
                                }
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during GetCD processing!\n");
                                response_str = "CD_ERR:crash";
                                if (L) lua_settop(L, 0); // Attempt to clear stack
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for GetCD!\n");
                            response_str = "CD_ERR:Lua state/funcs null";
                        }
                        break;

                    case REQ_IS_IN_RANGE:
                        if (L && lua_loadbuffer && lua_pcall && lua_gettop && lua_isnumber && lua_settop) { // Note: IsSpellInRange returns number (0/1) or nil
                            try {
                                sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] hkEndScene: Processing REQ_IS_IN_RANGE for spell %d, unit '%s'.\n", req.spell_id, req.unit_id.c_str());
                                OutputDebugStringA(log_buffer);
                                int top_before = lua_gettop(L);

                                // Construct Lua code: "return IsSpellInRange(<spell_id_or_name>, <unit_id>)"
                                // Passing spell ID is generally safer than name lookup
                                char luaCode[128];
                                // Escape the unit_id string just in case, although typically "target", "player" etc.
                                sprintf_s(luaCode, sizeof(luaCode), "return IsSpellInRange(%d, \"%s\")", req.spell_id, req.unit_id.c_str());
                                
                                int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_Range");
                                
                                if (load_status == 0 && lua_gettop(L) > top_before) {
                                    if (lua_pcall(L, 0, 1, 0) == 0) { // Call IsSpellInRange(), 0 args, 1 result
                                        int range_result = -1; // Default to error/invalid
                                        if (lua_isnumber(L, -1)) { // Check if result is 0 or 1
                                            range_result = static_cast<int>(lua_tonumber(L, -1));
                                        } else { // Result is likely nil (invalid spell/unit)
                                            OutputDebugStringA("[WoWInjectDLL] IsInRange: Result was nil (invalid spell/unit?).\n");
                                            range_result = -1; // Map nil to -1
                                        }
                                        lua_settop(L, -2); // Pop result (or nil)

                                        // Format response string: "IN_RANGE:<result>"
                                        char range_buf[64];
                                        sprintf_s(range_buf, sizeof(range_buf), "IN_RANGE:%d", range_result);
                                        response_str = range_buf;
                                    } else {
                                        const char* err_msg = lua_tolstring(L, -1, NULL);
                                        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsInRange: lua_pcall failed! Error: %s\n", err_msg ? err_msg : "(unknown)");
                                        OutputDebugStringA(log_buffer);
                                        lua_settop(L, -2); // Pop error message
                                        response_str = "RANGE_ERR:pcall failed";
                                    }
                                } else {
                                    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IsInRange: lua_loadbuffer failed with status %d.\n", load_status);
                                    OutputDebugStringA(log_buffer);
                                    response_str = "RANGE_ERR:loadbuffer failed";
                                    lua_settop(L, top_before); // Ensure stack is clean
                                }
                            } catch (...) {
                                OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during IsInRange processing!\n");
                                response_str = "RANGE_ERR:crash";
                                if (L) lua_settop(L, 0); // Attempt to clear stack
                            }
                        } else {
                            OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions null for IsInRange!\n");
                            response_str = "RANGE_ERR:Lua state/funcs null";
                        }
                        break;

                    default:
                        OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing UNKNOWN request type!\n");
                        response_str = "ERROR:Unknown request";
                        break;
                } // End switch
            } // End else (Lua state check)

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
            g_hModule = hModule; // Store module handle
            g_bShutdown = false;
            // Create the IPC thread first
            g_hIPCThread = CreateThread(nullptr, 0, IPCThread, hModule, 0, nullptr);
            if (!g_hIPCThread) {
                OutputDebugStringA("[WoWInjectDLL] Failed to create IPC thread!\n");
                return FALSE; // Abort attachment
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
            // --- Revert Pipe Name ---
             const WCHAR* pipeNameToSignal = L"\\\\.\\pipe\\WowInjectPipe"; // FIXED BACKSLASHES
             HANDLE hDummyClient = CreateFileW(
                 pipeNameToSignal, 
                 GENERIC_WRITE, // Only need write access to connect/signal
                 0, NULL, OPEN_EXISTING, 0, NULL);

             if (hDummyClient != INVALID_HANDLE_VALUE) {
                  // Successfully opened the pipe, indicating the server might be waiting in ConnectNamedPipe
                  OutputDebugStringA("[WoWInjectDLL] Signalling pipe server thread to exit ConnectNamedPipe wait...\n");
                  CloseHandle(hDummyClient); 
             } else {
                 // This is expected if the server already passed ConnectNamedPipe or closed the handle.
                 DWORD error = GetLastError();
                 if (error != ERROR_PIPE_BUSY && error != ERROR_FILE_NOT_FOUND) { // Ignore errors indicating server is past waiting or pipe is gone
                    char error_buf[150];
                    sprintf_s(error_buf, sizeof(error_buf), "[WoWInjectDLL] CreateFileW to signal pipe failed unexpectedly. Error: %lu\n", error);
                    OutputDebugStringA(error_buf);
                 }
             }
            
            // Wait for the IPC thread to terminate
            if (g_hIPCThread) {
                 OutputDebugStringA("[WoWInjectDLL] Waiting for IPC thread to terminate...\n");
                 WaitForSingleObject(g_hIPCThread, 5000); // Wait max 5 seconds
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
        // FIXED: Use reinterpret_cast for pointer conversions
        DWORD base_ptr_val = *(reinterpret_cast<DWORD*>(D3D_PTR_1)); 
        if (!base_ptr_val) throw std::runtime_error("Failed to read base_ptr");
        DWORD pDevice_val = *(reinterpret_cast<DWORD*>(base_ptr_val + D3D_PTR_2));
        if (!pDevice_val) throw std::runtime_error("Failed to read pDevice");
        DWORD pVTable_val = *(reinterpret_cast<DWORD*>(pDevice_val));
        if (!pVTable_val) throw std::runtime_error("Failed to read pVTable");
        DWORD endSceneAddr = *(reinterpret_cast<DWORD*>(pVTable_val + D3D_ENDSCENE_VTABLE_OFFSET));
        if (!endSceneAddr) throw std::runtime_error("Failed to read EndScene address");

        // Removed unused cast expression
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
        errorMsg += "\n"; // Append newline
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

    // --- REMOVED: Explicit Security Attributes --- 
    /*
    SECURITY_DESCRIPTOR sd;
    SECURITY_ATTRIBUTES sa;

    InitializeSecurityDescriptor(&sd, SECURITY_DESCRIPTOR_REVISION);
    if (!SetSecurityDescriptorDacl(&sd, TRUE, NULL, FALSE)) {
        DWORD lastError = GetLastError();
        char err_buf[128];
        sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] Failed to set NULL DACL! GLE=%lu\n", lastError);
        OutputDebugStringA(err_buf);
        return 2; 
    }

    sa.nLength = sizeof(SECURITY_ATTRIBUTES);
    sa.lpSecurityDescriptor = &sd;
    sa.bInheritHandle = FALSE; 
    */
    // --- End Removed Security Attributes Setup ---

    // Create the named pipe
    // --- Revert Pipe Name and Max Instances, Remove Security Attributes --- 
    g_hPipe = CreateNamedPipeW(
        L"\\\\.\\pipe\\WowInjectPipe",      // Pipe name (WCHAR*) - FIXED BACKSLASHES
        PIPE_ACCESS_DUPLEX,            // Read/write access
        PIPE_TYPE_MESSAGE |            // Message type pipe
        PIPE_READMODE_MESSAGE |        // Message-read mode
        PIPE_WAIT,                     // Blocking mode
        1,                             // Max. instances - Reverted to 1 like reference
        sizeof(buffer),                // Output buffer size
        sizeof(buffer),                // Input buffer size
        0,                             // Default timeout
        NULL);                         // Default security attributes - Reverted

    if (g_hPipe == INVALID_HANDLE_VALUE) {
        // --- ADDED: Log GetLastError() ---
        DWORD lastError = GetLastError();
        char err_buf[128];
        sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] Failed to create named pipe! GLE=%lu\n", lastError);
        OutputDebugStringA(err_buf);
        //OutputDebugStringA("[WoWInjectDLL] Failed to create named pipe!\n"); // Original message commented out
        return 1;
    }
    OutputDebugStringA("[WoWInjectDLL] Pipe created. Waiting for client connection...\n");

    // Wait for the client to connect
    if (ConnectNamedPipe(g_hPipe, NULL) ? TRUE : (GetLastError() == ERROR_PIPE_CONNECTED)) {
        OutputDebugStringA("[WoWInjectDLL] Client connected.\n");

        // --- Communication Loop --- 
        while (!g_bShutdown) {
            // --- Read Command --- 
            success = ReadFile(
                g_hPipe,
                buffer,
                sizeof(buffer) - 1, // Leave space for null terminator
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
                // Assume client disconnected, wait for new connection?
                // For simplicity, break the loop for now.
                 break; 
            }

            buffer[bytesRead] = '\0'; // Null-terminate the received data
            std::string command(buffer);
            char log_buf[256];
            sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] IPC Received Raw: [%s]\n", command.c_str());
            OutputDebugStringA(log_buf);

            // Handle the received command (Parse and queue request)
            HandleIPCCommand(command);

            // --- MODIFIED: Wait for and Send Response (Polling) ---
            std::string responseToSend = "";
            bool responseFound = false;
            // Poll for a short duration (e.g., up to 100ms) for a response to appear
            for (int i = 0; i < 10; ++i) { // Check 10 times with 10ms sleep
                {
                    std::lock_guard<std::mutex> lock(g_queueMutex);
                    if (!g_responseQueue.empty()) {
                        responseToSend = g_responseQueue.front();
                        g_responseQueue.pop();
                        responseFound = true;
                        break; // Found response, exit polling loop
                    }
                }
                if (g_bShutdown) break; // Stop polling if shutting down
                Sleep(10); // Wait briefly before next check
            }

            if (!responseFound && !g_bShutdown) {
                // If no response was found after polling, log it (unless it was EXEC_LUA)
                if (command.rfind("EXEC_LUA:", 0) != 0) {
                    sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] IPC WARNING: No response generated for command [%s] within timeout.\n", command.substr(0, 50).c_str());
                    OutputDebugStringA(log_buf);
                    // Optionally send a default error/timeout response? 
                    // responseToSend = "ERROR:Timeout"; 
                }
            } 
            // --- End Response Wait ---

            if (!responseToSend.empty()) {
                DWORD bytesWritten;
                success = WriteFile(
                    g_hPipe,
                    responseToSend.c_str(),
                    (DWORD)responseToSend.length(),
                    &bytesWritten,
                    NULL);
                
                if (!success || bytesWritten != responseToSend.length()) {
                    char err_buf[128];
                    sprintf_s(err_buf, sizeof(err_buf), "[WoWInjectDLL] WriteFile failed. GLE=%d\n", GetLastError());
                    OutputDebugStringA(err_buf);
                    // Handle write error, maybe client disconnected?
                    break; 
                } else {
                     sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] Sent response: [%s]...\n", responseToSend.substr(0, 100).c_str());
                     OutputDebugStringA(log_buf);
                }
            } 
            // Introduce a small delay if no response was sent to prevent busy-waiting?
            // else { Sleep(1); }

        } // End while loop
    } else {
        OutputDebugStringA("[WoWInjectDLL] Failed to connect to client.\n");
    }

    // Cleanup
    OutputDebugStringA("[WoWInjectDLL] IPC Thread exiting. Closing pipe handle.\n");
    if (g_hPipe != INVALID_HANDLE_VALUE) {
        DisconnectNamedPipe(g_hPipe); // Disconnect client if connected
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
    } else if (command.rfind("EXEC_LUA:", 0) == 0) { // Check if starts with EXEC_LUA:
        req.type = REQ_EXEC_LUA;
        req.data = command.substr(9); // Get the Lua code part
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type EXEC_LUA. Data size: %zu\n", req.data.length());
    } else if (sscanf_s(command.c_str(), "GET_CD:%d", &req.spell_id) == 1) {
        req.type = REQ_GET_CD;
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type GET_CD. SpellID: %d\n", req.spell_id);
    } else {
        // Buffer for unit_id, assuming max length 32
        char unit_id_buf[33] = {0}; 
        if (sscanf_s(command.c_str(), "IS_IN_RANGE:%d,%32s", &req.spell_id, unit_id_buf, (unsigned)_countof(unit_id_buf)) == 2) {
            req.type = REQ_IS_IN_RANGE;
            req.unit_id = unit_id_buf;
            sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type IS_IN_RANGE. SpellID: %d, UnitID: %s\n", req.spell_id, req.unit_id.c_str());
        } else {
            req.type = REQ_UNKNOWN;
            sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Unknown command received: [%s]\n", command.substr(0, 100).c_str());
            // Pass unknown command data for potential error response
            req.data = command;
        }
    }
    OutputDebugStringA(log_buffer);

    // Queue the request
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        g_requestQueue.push(req);
    }
} 