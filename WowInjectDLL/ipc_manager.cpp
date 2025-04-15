// ipc_manager.cpp
#include "ipc_manager.h"
#include "globals.h"
#include <iostream>
#include <sstream>
#include <vector>
#include <windows.h>
#include <cstdio> // For sscanf_s

// Global variable definitions might be needed here if not properly externed
// extern std::atomic<bool> g_running;
// extern HANDLE g_hPipe;
// extern std::mutex g_queueMutex;
// extern std::queue<Request> g_requestQueue;

HANDLE g_ipcThreadHandle = nullptr;

void StartIPCServer() {
    g_ipcThreadHandle = CreateThread(nullptr, 0, IPCThread, nullptr, 0, nullptr);
    if (g_ipcThreadHandle == nullptr) {
        OutputDebugStringA("[IPC] Failed to create IPC thread.\n");
    }
}

void StopIPCServer() {
    // Signal thread to stop by setting the global flag
    g_running = false;

    // Unblock ConnectNamedPipe wait by connecting a dummy client
    const WCHAR* pipeNameToSignal = L"\\\\.\\pipe\\WowInjectPipe"; // Consider making PIPE_NAME wide char in globals.h
    HANDLE hDummyClient = CreateFileW(
        pipeNameToSignal,
        GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);

    if (hDummyClient != INVALID_HANDLE_VALUE) {
        OutputDebugStringA("[IPC] Signalling pipe server thread to exit ConnectNamedPipe wait...\n");
        CloseHandle(hDummyClient);
    } else {
        DWORD error = GetLastError();
        // Ignore common errors when the server is already closing/closed
        if (error != ERROR_PIPE_BUSY && error != ERROR_FILE_NOT_FOUND && error != ERROR_PIPE_NOT_CONNECTED) {
            char error_buf[150];
            sprintf_s(error_buf, sizeof(error_buf), "[IPC] CreateFileW to signal pipe failed unexpectedly. Error: %lu\n", error);
            OutputDebugStringA(error_buf);
        }
    }

    // Wait for the IPC thread to actually terminate
    if (g_ipcThreadHandle != nullptr) {
        OutputDebugStringA("[IPC] Waiting for IPC thread to terminate...\n");
        WaitForSingleObject(g_ipcThreadHandle, 2000); // Wait for max 2 seconds
        CloseHandle(g_ipcThreadHandle);
        g_ipcThreadHandle = nullptr;
        OutputDebugStringA("[IPC] IPC thread terminated.\n");
    } else {
        OutputDebugStringA("[IPC] IPC thread handle was already null.\n");
    }

    // Final check on the pipe handle itself
    if (g_hPipe != INVALID_HANDLE_VALUE) {
        OutputDebugStringA("[IPC] Closing remaining pipe handle (if any)...\n");
        DisconnectNamedPipe(g_hPipe); // Attempt disconnect first
        CloseHandle(g_hPipe);
        g_hPipe = INVALID_HANDLE_VALUE;
    }
    OutputDebugStringA("[IPC] Server cleanup finished.\n");
}

DWORD WINAPI IPCThread(LPVOID lpParam) {
    OutputDebugStringA("[IPC] Thread started. Attempting pipe creation...\n");
    char buffer[PIPE_BUFFER_SIZE];
    DWORD bytesRead;
    BOOL success;

    // Ensure the pipe name constant is defined correctly (e.g., in globals.h/cpp)
    // Define pipe name as wide string here for CreateNamedPipeW
    const WCHAR* pipeNameW = L"\\\\.\\pipe\\WowInjectPipe"; // TODO: Move wide definition to globals.h/cpp

    g_hPipe = CreateNamedPipeW(
        pipeNameW, // Use wide string directly
        PIPE_ACCESS_DUPLEX,
        PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
        1, // Max instances
        sizeof(buffer), // Out buffer size
        sizeof(buffer), // In buffer size
        PIPE_TIMEOUT_MS,
        NULL);

    if (g_hPipe == INVALID_HANDLE_VALUE) {
        DWORD lastError = GetLastError();
        char err_buf[128];
        sprintf_s(err_buf, sizeof(err_buf), "[IPC] Failed to create named pipe! GLE=%lu\n", lastError);
        OutputDebugStringA(err_buf);
        return 1;
    }
    OutputDebugStringA("[IPC] Pipe created successfully. Entering connection loop.\n");

    // Outer loop to wait for connections repeatedly
    while (g_running)
    {
        OutputDebugStringA("[IPC] Waiting for client connection...\n");
        BOOL connected = ConnectNamedPipe(g_hPipe, NULL); // Blocking call

        if (!connected && GetLastError() != ERROR_PIPE_CONNECTED) {
            // If g_running is false, we were likely signalled to stop during the wait
            if (!g_running) {
                 OutputDebugStringA("[IPC] ConnectNamedPipe returned while shutting down.\n");
                 break; // Exit the outer loop
            }
            // Otherwise, it's a real error
            char err_buf[128];
            sprintf_s(err_buf, sizeof(err_buf), "[IPC] ConnectNamedPipe failed. GLE=%d\n", GetLastError());
            OutputDebugStringA(err_buf);
            // Maybe add a small delay before retrying?
            Sleep(100);
            continue; // Try to wait for connection again
        }

        // Check again after ConnectNamedPipe returns
        if (!g_running) {
             OutputDebugStringA("[IPC] Shutting down after client connected.\n");
             break;
        }

        OutputDebugStringA("[IPC] Client connected. Entering communication loop.\n");

        // Inner Communication Loop
        while (g_running)
        {
            // Read Command
            success = ReadFile(
                g_hPipe,
                buffer,
                sizeof(buffer) - 1, // Leave space for null terminator
                &bytesRead,
                NULL);

            if (!success || bytesRead == 0) {
                DWORD error = GetLastError();
                if (error == ERROR_BROKEN_PIPE) {
                    OutputDebugStringA("[IPC] Client disconnected (Broken Pipe).\n");
                } else if (g_running) { // Don't log errors if we are shutting down anyway
                    char err_buf[128];
                    sprintf_s(err_buf, sizeof(err_buf), "[IPC] ReadFile failed. GLE=%d\n", error);
                    OutputDebugStringA(err_buf);
                }
                 break; // Exit inner loop, wait for new connection
            }

            buffer[bytesRead] = '\0'; // Null-terminate the received data
            std::string command(buffer);
            char log_buf[256];
            sprintf_s(log_buf, sizeof(log_buf), "[IPC] Received Raw: [%s]\n", command.c_str());
            OutputDebugStringA(log_buf);

            // Handle the received command (parse and queue)
            HandleIPCCommand(command);

            // --- REINSTATED: Poll for and Send Response --- 
            std::string responseToSend = "";
            bool responseFound = false;
            // Poll for a longer duration (e.g., 50 attempts * 10ms = 500ms total)
            for (int i = 0; i < 50 && g_running; ++i) { // Increased attempts to 50, added g_running check
                {
                    std::lock_guard<std::mutex> lock(g_queueMutex);
                    if (!g_responseQueue.empty()) {
                        responseToSend = g_responseQueue.front();
                        g_responseQueue.pop();
                        responseFound = true;
                        OutputDebugStringA("[IPC] Found response in queue.\n"); 
                        break; // Exit poll loop
                    }
                }
                Sleep(10); // Wait 10ms before polling again
            }

            if (!responseFound && g_running) { // Check g_running again
                // Log warning only if the command wasn't EXEC_LUA (which might not return anything reliably)
                if (command.rfind("EXEC_LUA:", 0) != 0) {
                     sprintf_s(log_buf, sizeof(log_buf), "[IPC] WARNING: No response generated/found for command [%.50s] within ~500ms timeout.\n", command.c_str());
                     OutputDebugStringA(log_buf);
                }
                // Decide if we should send a default timeout response? For now, send nothing.
                // responseToSend = "TIMEOUT:No response"; 
            }

            if (!responseToSend.empty()) {
                SendResponse(responseToSend); // Call SendResponse from IPC thread
            }
            // --- End Response Polling/Sending ---

        } // End inner communication loop

        // Client disconnected or error occurred in inner loop
        OutputDebugStringA("[IPC] Disconnecting server side pipe instance.\n");
        if (!DisconnectNamedPipe(g_hPipe)) {
             if (g_running) { // Don't log error if shutting down
                char err_buf[128];
                sprintf_s(err_buf, sizeof(err_buf), "[IPC] DisconnectNamedPipe failed. GLE=%d\n", GetLastError());
                OutputDebugStringA(err_buf);
             }
        }

    } // End outer connection loop (while g_running)

    // Cleanup when g_running becomes false
    OutputDebugStringA("[IPC] Thread exiting outer loop. Closing pipe handle.\n");
    if (g_hPipe != INVALID_HANDLE_VALUE) {
        // Disconnect may have already happened, but CloseHandle is important
        CloseHandle(g_hPipe);
        g_hPipe = INVALID_HANDLE_VALUE;
    }
    OutputDebugStringA("[IPC] Thread finished.\n");
    return 0;
}

// Parses command string and queues a request for the main thread
void HandleIPCCommand(const std::string& command) {
    Request req;
    char log_buffer[256];

    if (command.empty()) {
        OutputDebugStringA("[IPC] Received empty command string.\n");
        return;
    }

    // Trim potential trailing null characters just in case
    std::string trimmed_command = command.c_str();

    if (trimmed_command == "ping") {
        req.type = REQ_PING;
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type PING.\n");
    } else if (trimmed_command == "GET_TIME_MS") {
        req.type = REQ_GET_TIME_MS;
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type GET_TIME_MS.\n");
    } else if (trimmed_command == "GET_COMBO_POINTS") {
         req.type = REQ_GET_COMBO_POINTS;
         sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type GET_COMBO_POINTS.\n");
    } else if (trimmed_command == "GET_TARGET_GUID") {
         req.type = REQ_GET_TARGET_GUID;
         sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type GET_TARGET_GUID.\n");
    } else if (trimmed_command.rfind("EXEC_LUA:", 0) == 0) {
        req.type = REQ_EXEC_LUA;
        if (trimmed_command.length() > 9) {
            req.data = trimmed_command.substr(9);
        }
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type EXEC_LUA. Data size: %zu\n", req.data.length());
    } else if (sscanf_s(trimmed_command.c_str(), "GET_CD:%d", &req.spell_id) == 1) {
        req.type = REQ_GET_CD;
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type GET_CD. SpellID: %d\n", req.spell_id);
    } else if (sscanf_s(trimmed_command.c_str(), "GET_SPELL_INFO:%d", &req.spell_id) == 1) {
        req.type = REQ_GET_SPELL_INFO;
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type GET_SPELL_INFO. SpellID: %d\n", req.spell_id);
    } else if (sscanf_s(trimmed_command.c_str(), "CAST_SPELL:%d,%llu", &req.spell_id, &req.target_guid) == 2) {
        req.type = REQ_CAST_SPELL;
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type CAST_SPELL. SpellID: %d, TargetGUID: 0x%llX\n", req.spell_id, req.target_guid);
    } else if (sscanf_s(trimmed_command.c_str(), "IS_BEHIND_TARGET:%llx", &req.target_guid) == 1) {
        req.type = REQ_IS_BEHIND_TARGET;
        sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type IS_BEHIND_TARGET. TargetGUID: 0x%llX\n", req.target_guid);
    } else {
        char unit_id_buf[64] = {0}; // Increased buffer size slightly
        if (sscanf_s(trimmed_command.c_str(), "IS_IN_RANGE:%d,%63s", &req.spell_id, unit_id_buf, (unsigned)_countof(unit_id_buf)) == 2) {
             req.type = REQ_IS_IN_RANGE;
             req.unit_id = unit_id_buf;
             req.spell_name.clear(); // Ensure old field is clear
             sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Queued request type IS_IN_RANGE. SpellID: %d, UnitID: %s\n", req.spell_id, req.unit_id.c_str());
        } else {
            req.type = REQ_UNKNOWN;
            req.data = trimmed_command; // Store the unknown command
            sprintf_s(log_buffer, sizeof(log_buffer), "[IPC] Unknown command received: [%.100s]\n", trimmed_command.c_str());
        }
    }
    OutputDebugStringA(log_buffer);

    // Queue the request for the main thread (hkEndScene)
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        g_requestQueue.push(req);
    }
}

// Sends a response string back to the client (called by IPC thread)
void SendResponse(const std::string& response) {
    if (g_hPipe == INVALID_HANDLE_VALUE || response.empty()) {
        if (response.empty()) OutputDebugStringA("[IPC] SendResponse called with empty string.\n");
        return;
    }

    DWORD bytesWritten;
    BOOL success = WriteFile(
        g_hPipe,
        response.c_str(),
        response.length() + 1, // Send exact length PLUS the null terminator
        &bytesWritten,
        NULL);

    if (!success || bytesWritten != (response.length() + 1)) { // Check against length + 1
        char err_buf[128];
        sprintf_s(err_buf, sizeof(err_buf), "[IPC] WriteFile failed for response. GLE=%d\n", GetLastError());
        OutputDebugStringA(err_buf);
        // Consider disconnecting if write fails?
        // DisconnectNamedPipe(g_hPipe);
    } else {
         char log_buf[256];
         sprintf_s(log_buf, sizeof(log_buf), "[IPC] Sent response: [%.100s]... (%d bytes)\n", response.c_str(), bytesWritten);
         OutputDebugStringA(log_buf);
         // Flush buffers to ensure data is sent immediately (REINSTATED)
         if (!FlushFileBuffers(g_hPipe)) {
             sprintf_s(log_buf, sizeof(log_buf), "[IPC] FlushFileBuffers failed. GLE=%d\n", GetLastError());
             OutputDebugStringA(log_buf);
         }
    }
} 