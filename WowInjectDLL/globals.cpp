// globals.cpp - Define global variables
#include "globals.h"

// --- Constants Definitions ---
const WCHAR* PIPE_NAME = L"\\\\.\\pipe\\WowInjectPipe";

// --- Global Variable Definitions ---
HMODULE g_hModule = nullptr;
std::atomic<bool> g_running(false); // Initialize atomic bool
HANDLE g_hPipe = INVALID_HANDLE_VALUE;
std::queue<Request> g_requestQueue;
std::queue<std::string> g_responseQueue;
std::mutex g_queueMutex;
lua_State* g_luaState = nullptr;
EndScene_t oEndScene = nullptr;

uintptr_t g_baseAddress = 0;