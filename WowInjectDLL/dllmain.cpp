// dllmain.cpp : Defines the entry point for the DLL application.
#include "pch.h"
#include <iostream> // For debug output if needed
#include <queue>    // For command queue
#include <mutex>    // For thread safety
#include <string>   // For command strings
#include <vector>   // For processing dequeued commands
#include <chrono>   // For basic timing/sleep in IPC response wait

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
    REQ_GET_TIME
    // Add REQ_GET_CD, REQ_GET_RANGE etc. later
};

struct Request {
    RequestType type = REQ_UNKNOWN;
    std::string data; // For Lua code or parameters like spell ID
    // Could add more fields like unit ID later
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
// Add others like lua_tolstring (0x0084E0E0), lua_pushstring (0x0084E350) etc. as needed from user list

#define LUA_GLOBALSINDEX -10002 // WoW's index for the global table (_G)

// Renamed typedefs
typedef int(__cdecl* lua_pcall_t)(lua_State* L, int nargs, int nresults, int errfunc);
typedef double(__cdecl* lua_tonumber_t)(lua_State* L, int idx);
typedef void(__cdecl* lua_settop_t)(lua_State* L, int idx);
typedef int(__cdecl* lua_gettop_t)(lua_State* L); // Added lua_gettop typedef
// --- ADDED: Signature for FrameScript_Load (0x0084F860) ---
// Returns 0 on success, pushes chunk function onto stack
typedef int (__cdecl* lua_loadbuffer_t)(lua_State *L, const char *buff, size_t sz, const char *name);

// Renamed function pointers
lua_pcall_t lua_pcall = (lua_pcall_t)LUA_PCALL_ADDR;
lua_tonumber_t lua_tonumber = (lua_tonumber_t)LUA_TONUMBER_ADDR;
lua_settop_t lua_settop = (lua_settop_t)LUA_SETTOP_ADDR;
lua_gettop_t lua_gettop = (lua_gettop_t)0x0084DBD0; // Added lua_gettop pointer (Address from FrameScript_GetTop)
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

            switch (req.type) {
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

                case REQ_GET_TIME:
                     // --- APPROACH 6: lua_loadbuffer + lua_pcall --- 
                     if (L && lua_loadbuffer && lua_pcall && lua_gettop && lua_tonumber && lua_settop) { 
                         try {
                             OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing REQ_GET_TIME (Approach 6).\n");
                             
                             int top_before = lua_gettop(L);
                             sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: Lua stack top BEFORE loadbuffer: %d\n", top_before);
                             OutputDebugStringA(log_buffer);
                             
                             // 1. Load the Lua code "return GetTime()"
                             const char* luaCode = "return GetTime()";
                             sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: Calling lua_loadbuffer with code: %s\n", luaCode);
                             OutputDebugStringA(log_buffer);
                             int load_status = lua_loadbuffer(L, luaCode, strlen(luaCode), "WowInjectDLL_GetTime");
 
                             int top_after_get = lua_gettop(L);
                             sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: Load status: %d, Stack top AFTER loadbuffer: %d\n", load_status, top_after_get);
                             OutputDebugStringA(log_buffer);
  
                             // Check if loadbuffer succeeded (status 0) and pushed the function chunk
                             if (load_status == 0 && top_after_get > top_before) {
                                 // 2. Call the loaded chunk
                                 OutputDebugStringA("[WoWInjectDLL] GetTime: Load successful. Calling lua_pcall(L, 0, 1, 0)...\n");
                                 if (lua_pcall(L, 0, 1, 0) == 0) { // Call GetTime(), 0 args, 1 result
                                     double game_time = lua_tonumber(L, -1); // Get result from top of stack
                                     lua_settop(L, -2); // Pop result

                                     // Format response string: "TIME:seconds.fraction"
                                     char time_buf[64];
                                     sprintf_s(time_buf, sizeof(time_buf), "TIME:%.3f", game_time); 
                                     response_str = time_buf;
                                     sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: Got time %.3f. Response: %s\n", game_time, response_str.c_str());
                                     OutputDebugStringA(log_buffer);
                                 } else {
                                     // pcall failed
                                     OutputDebugStringA("[WoWInjectDLL] GetTime: lua_pcall failed!\n");
                                     lua_settop(L, -2); // Pop error message
                                     response_str = "ERROR:GetTime pcall failed";
                                 }
                             } else {
                                 // loadbuffer failed
                                 sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] GetTime: FAILED! lua_loadbuffer failed with status %d.\n", load_status);
                                 OutputDebugStringA(log_buffer);
                                 response_str = "ERROR:GetTime loadbuffer failed";
                                 // Ensure stack is clean (pop error message or chunk if load failed but pushed something)
                                 lua_settop(L, top_before);
                             }
                             // --- END APPROACH 6 --- 
                         } catch (...) {
                             OutputDebugStringA("[WoWInjectDLL] hkEndScene: CRASH during GetTime processing (Approach 6)!\n");
                             response_str = "ERROR:GetTime crash";
                                if (L) lua_settop(L, 0); // Attempt to clear stack on crash
                         }
                     } else {
                          OutputDebugStringA("[WoWInjectDLL] hkEndScene: ERROR - Lua state or required Lua functions (loadbuffer, pcall, gettop, tonumber, settop) null for GetTime!\n");
                          response_str = "ERROR:Lua state/funcs null";
                     }
                     break; // Response generated (or error string)

                 // Add cases for REQ_GET_CD, REQ_GET_RANGE etc. here later
                 
                 default:
                    OutputDebugStringA("[WoWInjectDLL] hkEndScene: Processing UNKNOWN request type!\n");
                    response_str = "ERROR:Unknown request";
                    break;
            }

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
            // Ensure correct pipe name here too if changed
             const WCHAR* pipeNameToSignal = L"\\\\.\\pipe\\WowInjectPipe"; // Match the name used in CreateNamedPipeW - FIXED BACKSLASHES
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
    const WCHAR* pipeName = L"\\\\.\\pipe\\WowInjectPipe"; // Corrected name - FIXED BACKSLASHES
    char buffer[1024];
    DWORD bytesRead;
    DWORD bytesWritten;

    while (!g_bShutdown) {
        // Create Pipe Instance for this connection
        g_hPipe = CreateNamedPipeW(
            pipeName, PIPE_ACCESS_DUPLEX, 
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT, 
            1, 1024*16, 1024*16, NMPWAIT_USE_DEFAULT_WAIT, NULL);

        if (g_hPipe == INVALID_HANDLE_VALUE) {
            // Log error and retry
             DWORD error = GetLastError(); 
             char error_buf[100];
             sprintf_s(error_buf, sizeof(error_buf), "[WoWInjectDLL] Failed to create named pipe! Error: %lu\n", error);
             OutputDebugStringA(error_buf); 
             Sleep(1000); 
             continue;
        }

        OutputDebugStringA("[WoWInjectDLL] Pipe created. Waiting for client connection...\n");
        BOOL connected = ConnectNamedPipe(g_hPipe, NULL) ? TRUE : (GetLastError() == ERROR_PIPE_CONNECTED);

        if (!connected) {
             // Log error if not shutting down, clean up handle, retry
             if (!g_bShutdown) { 
                 DWORD error = GetLastError();
                 char error_buf[100];
                 sprintf_s(error_buf, sizeof(error_buf), "[WoWInjectDLL] Failed ConnectNamedPipe. Error: %lu\n", error);
                 OutputDebugStringA(error_buf);
             }
             CloseHandle(g_hPipe);
             g_hPipe = INVALID_HANDLE_VALUE;
             if (!g_bShutdown) Sleep(500); 
             continue; 
        }
        OutputDebugStringA("[WoWInjectDLL] Client connected.\n");

        // Message Loop for this Client
        while (!g_bShutdown) {
            memset(buffer, 0, sizeof(buffer));
            bytesRead = 0;
            BOOL successRead = ReadFile(g_hPipe, buffer, sizeof(buffer) - 1, &bytesRead, NULL);

            if (!successRead || bytesRead == 0) {
                // Handle client disconnect or read error
                DWORD error = GetLastError();
                if (error == ERROR_BROKEN_PIPE) {
                    OutputDebugStringA("[WoWInjectDLL] Client disconnected (Broken Pipe).\n");
                } else if (!g_bShutdown) {
                     char error_buf[100];
                     sprintf_s(error_buf, sizeof(error_buf), "[WoWInjectDLL] ReadFile failed. Error: %lu\n", error);
                     OutputDebugStringA(error_buf);
                }
                break; // Exit inner loop, wait for new connection
            }

            // Process Command & Queue Request
            buffer[bytesRead] = '\0';
            std::string command(buffer);
            HandleIPCCommand(command); // This now queues the request

            // --- Wait for and Send Response ---
            std::string responseToSend = "";
            // Simple polling check for response (can be improved with condition variables)
            // Check for a short time if a response is ready
            bool foundResponse = false;
            for(int i=0; i<5; ++i) { // Check ~5 times over ~50ms
                {
                    std::lock_guard<std::mutex> lock(g_queueMutex);
                    if (!g_responseQueue.empty()) {
                        responseToSend = g_responseQueue.front();
                        g_responseQueue.pop();
                        foundResponse = true;
                        break; // Got response
                    }
                }
                 if (g_bShutdown) break; // Stop waiting if shutting down
                 Sleep(10); // Small delay between checks
            }

            // If no specific response generated (e.g., for EXEC_LUA or if timeout), send default ACK
            if (!foundResponse && !g_bShutdown) {
                 // Optionally send nothing, or a simple ACK
                 // responseToSend = "ACK"; 
                 // Let's send nothing for now if no response queued
                 if (command.rfind("EXEC_LUA:", 0) != 0) { // Only log if NOT exec_lua
                     OutputDebugStringA("[WoWInjectDLL] No response generated/found in time for command. Sending nothing.\n");
                 }
            } else if (g_bShutdown) {
                 responseToSend = ""; // Don't send if shutting down
            }
            
            // Only write if there's something to send
            if (!responseToSend.empty()) {
                bytesWritten = 0;
                BOOL successWrite = WriteFile(
                    g_hPipe,
                    responseToSend.c_str(),
                    (DWORD)responseToSend.length(),
                    &bytesWritten,
                    NULL
                );

                if (!successWrite || bytesWritten != responseToSend.length()) {
                    if (!g_bShutdown) { 
                        DWORD error = GetLastError();
                        char error_buf[100];
                        sprintf_s(error_buf, sizeof(error_buf), "[WoWInjectDLL] WriteFile failed. Error: %lu\n", error);
                        OutputDebugStringA(error_buf);
                    }
                    break; // Exit inner loop on write error
                } else {
                     char log_buf[256];
                     sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] Sent response: [%.100s]...\n", responseToSend.c_str());
                     OutputDebugStringA(log_buf);
                }
            }
            
        } // End message loop for this client

        // Clean up the pipe connection for this client
        OutputDebugStringA("[WoWInjectDLL] Disconnecting pipe instance.\n");
        DisconnectNamedPipe(g_hPipe);
        CloseHandle(g_hPipe);
        g_hPipe = INVALID_HANDLE_VALUE;

    } // End main loop (!g_bShutdown)

    OutputDebugStringA("[WoWInjectDLL] IPC Thread exiting cleanly.\n");
    return 0;
}

void HandleIPCCommand(const std::string& command) {
    // Log the raw received command first
    char log_buffer[1024];
    sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] IPC Received Raw: [%s]\n", command.c_str());
    OutputDebugStringA(log_buffer);

    Request req; // Create request object

    // --- Command Parsing --- 
    if (command == "ping") {
        OutputDebugStringA("[WoWInjectDLL] Parsed command: ping\n");
        // For ping, we can directly queue a response (doesn't need main thread)
         std::lock_guard<std::mutex> lock(g_queueMutex);
         g_responseQueue.push("pong"); // Queue pong response immediately
         return; // Don't queue a request for main thread
    }
    else if (command.rfind("EXEC_LUA:", 0) == 0) { // Check if starts with EXEC_LUA:
        req.type = REQ_EXEC_LUA;
        req.data = command.substr(9); // Extract code after "EXEC_LUA:"
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Parsed: EXEC_LUA. Code: [%.100s]...\n", req.data.c_str());
        OutputDebugStringA(log_buffer);
    } 
    else if (command == "GET_TIME") {
        req.type = REQ_GET_TIME;
        OutputDebugStringA("[WoWInjectDLL] Parsed: GET_TIME\n");
    }
    // Add parsing for GET_CD, GET_RANGE etc. here later
    // else if (command.rfind("GET_CD:", 0) == 0) { ... }
    else {
        req.type = REQ_UNKNOWN;
        req.data = command;
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Unknown command received: [%s]\n", command.c_str());
        OutputDebugStringA(log_buffer);
        // Optionally queue an error response immediately?
        // std::lock_guard<std::mutex> lock(g_queueMutex);
        // g_responseQueue.push("ERROR:Unknown command");
        // return; // Or queue the unknown request? Let's queue it for now.
    }

    // --- Queue the request for the main thread --- 
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        g_requestQueue.push(req);
        sprintf_s(log_buffer, sizeof(log_buffer), "[WoWInjectDLL] Queued request type %d. Queue size: %zu\n", (int)req.type, g_requestQueue.size());
        OutputDebugStringA(log_buffer);
    } // Mutex unlocked here
} 