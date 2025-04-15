#include "pch.h" // Ensure pch.h is first
// hook_manager.cpp
#include "hook_manager.h"
#include "command_processor.h"
#include "ipc_manager.h"
#include "globals.h"
// #include "offsets.h" // Removed direct include, should come from pch.h
#include "detours.h"
#include <d3d9.h>
#include <stdexcept>
#include <vector>
#include <stdio.h>
#include <mutex>
#include <intrin.h>
#include <cstdio> // Include for sprintf_s

// Define function pointer type for EndScene
typedef HRESULT(APIENTRY* EndScene_t)(LPDIRECT3DDEVICE9);

// Original EndScene function pointer (declared in globals.h, defined in globals.cpp)
// EndScene_t oEndScene = nullptr; // REMOVED definition

// Define D3D offsets (Consider moving to a dedicated offsets.h or globals.h)
#define D3D_PTR_1 0x00C5DF88
#define D3D_PTR_2 0x397C
#define D3D_ENDSCENE_VTABLE_OFFSET 0xA8

void InitializeHook() {
    OutputDebugStringA("[Hook] Initializing EndScene hook...\n");
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
        sprintf_s(buffer, sizeof(buffer), "[Hook] Found EndScene address: 0x%X\n", endSceneAddr);
        OutputDebugStringA(buffer);

        DetourTransactionBegin();
        DetourUpdateThread(GetCurrentThread());
        DetourAttach(&(PVOID&)oEndScene, hkEndScene); // Use the global oEndScene
        LONG error = DetourTransactionCommit();

        if (error == NO_ERROR) {
            OutputDebugStringA("[Hook] EndScene hook attached successfully.\n");
        } else {
             sprintf_s(buffer, sizeof(buffer), "[Hook] Detours failed to attach hook, error: %ld\n", error);
             OutputDebugStringA(buffer);
             oEndScene = nullptr;
        }

    } catch (const std::exception& e) {
        std::string errorMsg = "[Hook] ERROR in InitializeHook (exception): ";
        errorMsg += e.what();
        errorMsg += "\n";
        OutputDebugStringA(errorMsg.c_str());
        oEndScene = nullptr;
    } catch (...) {
        OutputDebugStringA("[Hook] CRITICAL ERROR in InitializeHook: Memory access violation.\n");
         oEndScene = nullptr;
    }
}

void ShutdownHook() {
    if (oEndScene == nullptr) {
        OutputDebugStringA("[Hook] ShutdownHook: Hook not attached or already removed.\n");
        return;
    }
    OutputDebugStringA("[Hook] Removing EndScene hook...\n");
    DetourTransactionBegin();
    DetourUpdateThread(GetCurrentThread());
    DetourDetach(&(PVOID&)oEndScene, hkEndScene);
    DetourTransactionCommit();
    OutputDebugStringA("[Hook] EndScene hook detached.\n");
    oEndScene = nullptr;
}

// Hooked EndScene - Runs in the game's main rendering thread
HRESULT WINAPI hkEndScene(IDirect3DDevice9* pDevice) {
    if (!oEndScene) {
        return E_FAIL; // Original function pointer is null
    }

    if (g_running) { // Check if we are shutting down
        // --- Process Queued Requests ---
        std::vector<Request> requestsToProcess;
        {
            std::lock_guard<std::mutex> lock(g_queueMutex);
            // Move incoming requests from global queue to local vector
            while (!g_requestQueue.empty()) {
                requestsToProcess.push_back(g_requestQueue.front());
                g_requestQueue.pop();
            }
            // NOTE: Responses are NO LONGER fetched or sent here.
            // They are handled by the polling loop in the IPCThread.
        } // Unlock mutex

        // Process requests (calls CommandProcessor)
        if (!requestsToProcess.empty()) {
            for (const auto& req : requestsToProcess) {
                ProcessCommand(req); // Process the command (this queues the response internally)
            }
        }
        // --- Response Sending REMOVED from hook thread ---
        /* // REMOVED
        {
            std::unique_lock<std::mutex> lock(g_queueMutex); // USE UNIQUE_LOCK
            // Check if there are responses to send
            while (!g_responseQueue.empty()) {
                std::string response = g_responseQueue.front();
                g_responseQueue.pop();
                // Unlock before sending to avoid holding lock during potential brief pipe write
                lock.unlock();
                SendResponse(response); // Call SendResponse from ipc_manager.h
                lock.lock(); // Re-lock to check loop condition safely
            }
        }
        */
        // --- End Response Sending ---

    } // End if(g_running)

    // Call the original EndScene function
    return oEndScene(pDevice);
}

// --- Helper Function for Logging (using OutputDebugStringA) ---
void LogToFile(const char* format, ...) { // Renamed to avoid conflict if 'Log' is defined elsewhere
    char buffer[512];
    va_list args;
    va_start(args, format);
    vsnprintf_s(buffer, sizeof(buffer), _TRUNCATE, format, args); // Use vsnprintf_s for safety
    va_end(args);
    OutputDebugStringA(buffer); // Output to debugger
    // Optionally, add code here to write 'buffer' to a log file
}

bool HookDirectX() {
    LogToFile("HookDirectX: Attempting to hook EndScene..."); // Replaced Log

    // Get D3D9 Device pointer using common offsets for WoW 3.3.5a
    // These offsets are standard for this version but might vary slightly
    //DWORD d3dBase = **(DWORD**)(D3D_PTR_1); // Pointer to D3D object
    //DWORD* d3dDevice = *(DWORD**)(d3dBase + D3D_PTR_2); // Pointer to the D3D device vtable
    //DWORD* d3dVTable = (DWORD*)*d3dDevice; // The vtable itself

    // Read pointers carefully to avoid crashes
    DWORD d3dPtr1_val = *(DWORD*)D3D_PTR_1; // Removed offsets::
    if (!d3dPtr1_val) {
        LogToFile("HookDirectX Error: D3D_PTR_1 is null."); // Replaced Log
        return false;
    }
    LogToFile("HookDirectX: D3D_PTR_1 value = 0x%X", d3dPtr1_val); // Replaced Log


    DWORD d3dBase = *(DWORD*)d3dPtr1_val;
     if (!d3dBase) {
        LogToFile("HookDirectX Error: D3D Base pointer (dereferenced from D3D_PTR_1) is null."); // Replaced Log
        return false;
    }
    LogToFile("HookDirectX: D3D Base value = 0x%X", d3dBase); // Replaced Log

    // Introduce temporary pointer to handle potential intermediate null value
    DWORD* temp_d3dDevicePtr = (DWORD*)(d3dBase + D3D_PTR_2); // Removed offsets::
    if (!temp_d3dDevicePtr) {
         LogToFile("HookDirectX Error: Address calculation for D3D Device pointer resulted in NULL."); // Replaced Log
         return false;
    }

    // Now dereference the calculated address
    DWORD* d3dDevice = *(DWORD**)temp_d3dDevicePtr; // Pointer to the D3D device pointer (should point to vtable location)


    if (!d3dDevice) {
        LogToFile("HookDirectX Error: D3D Device pointer (dereferenced from base + D3D_PTR_2) is null."); // Replaced Log
        return false;
    }
    LogToFile("HookDirectX: D3D Device pointer value = 0x%X", d3dDevice); // Replaced Log


    DWORD* d3dVTable = (DWORD*)*d3dDevice; // The vtable itself (should point to the start of the virtual function table)

    if (!d3dVTable) {
        LogToFile("HookDirectX Error: D3D VTable pointer is null."); // Replaced Log
        return false;
    }
    LogToFile("HookDirectX: D3D VTable address = 0x%X", d3dVTable); // Replaced Log

    // Get the address of the original EndScene function from the vtable
    // EndScene is typically at index 42 (0-based), so offset 42 * 4 bytes = 168 bytes
    DWORD endSceneAddress = d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)]; // Removed offsets::
    LogToFile("HookDirectX: Original EndScene address = 0x%X", endSceneAddress); // Replaced Log

    oEndScene = (EndScene_t)endSceneAddress;

    // --- Patch the VTable ---
    // We need to change memory protection to write to the VTable
    DWORD oldProtect;
    if (!VirtualProtect(&d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)], sizeof(DWORD), PAGE_EXECUTE_READWRITE, &oldProtect)) { // Removed offsets::
        LogToFile("HookDirectX Error: Failed to change VTable memory protection. Error code: %d", GetLastError()); // Replaced Log
        return false;
    }

    // Write the address of our hooked function
    d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)] = (DWORD)hkEndScene; // Removed offsets::, Replaced Hooked_EndScene with hkEndScene
    LogToFile("HookDirectX: Patched VTable entry for EndScene with hkEndScene address: 0x%X", (DWORD)hkEndScene); // Replaced Log and Hooked_EndScene

    // Restore the original memory protection
    DWORD tempProtect; // Need a variable for the function call, even if we don't use it
    if (!VirtualProtect(&d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)], sizeof(DWORD), oldProtect, &tempProtect)) { // Removed offsets::
         LogToFile("HookDirectX Warning: Failed to restore VTable memory protection. Error code: %d", GetLastError()); // Replaced Log
         // Not returning false here, as the hook might still work, but it's risky.
    }

    LogToFile("HookDirectX: EndScene hooked successfully!"); // Replaced Log
    return true;
}


// Function to unhook DirectX (restore original function)
bool UnhookDirectX() {
    if (!oEndScene) {
        LogToFile("UnhookDirectX: Not hooked or already unhooked."); // Replaced Log
        return true; // Nothing to do
    }

     LogToFile("UnhookDirectX: Attempting to unhook EndScene..."); // Replaced Log

    // Get D3D9 Device pointer again
    DWORD d3dPtr1_val = *(DWORD*)D3D_PTR_1; // Removed offsets::
    if (!d3dPtr1_val) { LogToFile("UnhookDirectX Error: D3D_PTR_1 is null."); return false; } // Replaced Log
    DWORD d3dBase = *(DWORD*)d3dPtr1_val;
    if (!d3dBase) { LogToFile("UnhookDirectX Error: D3D Base pointer is null."); return false; } // Replaced Log
     DWORD* temp_d3dDevicePtr = (DWORD*)(d3dBase + D3D_PTR_2); // Removed offsets::
     if (!temp_d3dDevicePtr) { LogToFile("UnhookDirectX Error: Address calculation for D3D Device pointer resulted in NULL."); return false;} // Replaced Log
     DWORD* d3dDevice = *(DWORD**)temp_d3dDevicePtr;
    if (!d3dDevice) { LogToFile("UnhookDirectX Error: D3D Device pointer is null."); return false; } // Replaced Log
    DWORD* d3dVTable = (DWORD*)*d3dDevice;
    if (!d3dVTable) { LogToFile("UnhookDirectX Error: D3D VTable pointer is null."); return false; } // Replaced Log

    LogToFile("UnhookDirectX: D3D VTable address = 0x%X", d3dVTable); // Replaced Log
    LogToFile("UnhookDirectX: Original EndScene address to restore = 0x%X", oEndScene); // Replaced Log


    // --- Patch the VTable back ---
    DWORD oldProtect;
    if (!VirtualProtect(&d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)], sizeof(DWORD), PAGE_EXECUTE_READWRITE, &oldProtect)) { // Removed offsets::
        LogToFile("UnhookDirectX Error: Failed to change VTable memory protection. Error code: %d", GetLastError()); // Replaced Log
        return false; // Critical failure
    }

    // Write the original EndScene address back
    d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)] = (DWORD)oEndScene; // Removed offsets::
     LogToFile("UnhookDirectX: Restored original EndScene address in VTable."); // Replaced Log

    // Restore the original memory protection
    DWORD tempProtect;
     if (!VirtualProtect(&d3dVTable[D3D_ENDSCENE_VTABLE_OFFSET / sizeof(DWORD)], sizeof(DWORD), oldProtect, &tempProtect)) { // Removed offsets::
         LogToFile("UnhookDirectX Warning: Failed to restore VTable memory protection. Error code: %d", GetLastError()); // Replaced Log
    }

    oEndScene = nullptr; // Mark as unhooked
    LogToFile("UnhookDirectX: EndScene unhooked successfully."); // Replaced Log
    return true;
} 