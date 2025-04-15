// dllmain.cpp : Defines the entry point for the DLL application.
#include "pch.h"
#include "globals.h"
#include "hook_manager.h"
#include "ipc_manager.h"
#include "lua_interface.h"
#include "command_processor.h" // Needed for CommandWorkerThread declaration
#include <windows.h>
#include <stdio.h> // Needed for sprintf_s

// --- Helper Functions ---
// TODO: Consider moving GetBaseAddress elsewhere if needed by other modules
uintptr_t GetBaseAddress() {
    return (uintptr_t)GetModuleHandle(NULL); // Get base address of the host process (Wow.exe)
}

// Forward declaration for worker thread function (if not in a header)
// DWORD WINAPI CommandWorkerThread(LPVOID lpParam); // REMOVED

// --- DLL Entry Point ---
BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
        case DLL_PROCESS_ATTACH:
            DisableThreadLibraryCalls(hModule);
            g_hModule = hModule;
            g_running = true; // Set running flag
            g_baseAddress = GetBaseAddress(); // Store base address

            char log_buf[128];
            sprintf_s(log_buf, sizeof(log_buf), "[WoWInjectDLL] Attached. Base Address: 0x%p\n", (void*)g_baseAddress);
            OutputDebugStringA(log_buf);

            // Initialize Lua state and function pointers
            OutputDebugStringA("[WoWInjectDLL] Initializing Lua...\n");
            if (!InitializeLua()) { // From lua_interface.h
                OutputDebugStringA("[WoWInjectDLL] FATAL: Lua initialization failed! Proceeding anyway...\n");
                // Optionally return FALSE or handle error
            }
            OutputDebugStringA("[WoWInjectDLL] Lua initialization finished.\n");

            // Start IPC server thread
            OutputDebugStringA("[WoWInjectDLL] Starting IPC Server...\n");
            StartIPCServer(); // From ipc_manager.h
            OutputDebugStringA("[WoWInjectDLL] IPC Server started (thread created).\n");

            // Setup the hook
            OutputDebugStringA("[WoWInjectDLL] Initializing Hook...\n");
            InitializeHook(); // From hook_manager.h
            OutputDebugStringA("[WoWInjectDLL] Hook initialization finished.\n");

            OutputDebugStringA("[WoWInjectDLL] DLL_PROCESS_ATTACH finished.\n");
            break;

        case DLL_THREAD_ATTACH:
        case DLL_THREAD_DETACH:
            break;

        case DLL_PROCESS_DETACH:
            OutputDebugStringA("[WoWInjectDLL] Detaching...\n");
            g_running = false; // Signal threads to stop

            // Signal worker thread to wake up and exit (REMOVED)
            // OutputDebugStringA("[WoWInjectDLL] Notifying worker thread to exit...\n");
            // g_requestCv.notify_one();

            // Stop hook first (releases rendering thread quickly)
            ShutdownHook(); // From hook_manager.h

            // Stop IPC server (signals IPC thread, waits)
            StopIPCServer(); // From ipc_manager.h

            // Wait for Worker thread to finish (REMOVED)
            // if (g_workerThreadHandle != nullptr) {
            //     OutputDebugStringA("[WoWInjectDLL] Waiting for Worker thread to terminate...\n");
            //     WaitForSingleObject(g_workerThreadHandle, 2000); // Wait 2 seconds
            //     CloseHandle(g_workerThreadHandle);
            //     g_workerThreadHandle = nullptr;
            //     OutputDebugStringA("[WoWInjectDLL] Worker thread terminated.\n");
            // }

            // TODO: Add any other necessary cleanup here (e.g., Lua shutdown?)

            OutputDebugStringA("[WoWInjectDLL] Detached cleanly.\n");
            break;
    }
    return TRUE;
}

// --- Hook Setup/Removal Implementations (Simplified calls) ---
// The actual Detours logic will be moved to hook_manager.cpp
void SetupHook() {
    InitializeHook();
}

void RemoveHook() {
    ShutdownHook();
} 