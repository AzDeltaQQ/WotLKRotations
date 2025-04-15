// ipc_manager.h
#pragma once

#include "globals.h"

// Starts the named pipe server thread
void StartIPCServer();

// Stops the named pipe server
void StopIPCServer();

// Thread function for handling pipe communication
DWORD WINAPI IPCThread(LPVOID lpParam);

// Parses a raw command string and queues a Request struct
void HandleIPCCommand(const std::string& command);

// Sends a response string back to the client
void SendResponse(const std::string& response); 