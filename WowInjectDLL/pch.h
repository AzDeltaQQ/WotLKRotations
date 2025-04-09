#pragma once

#define WIN32_LEAN_AND_MEAN             // Exclude rarely-used stuff from Windows headers
// Windows Header Files
#include <windows.h>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector> // Include vector for potential future use (e.g., command queue)

// Define DIRECTINPUT_VERSION before including d3d9.h if necessary
// #define DIRECTINPUT_VERSION 0x0800 
#include <d3d9.h> // Required for LPDIRECT3DDEVICE9 and HRESULT

// Include Detours header (ensure it's in your include path)
#include "detours.h" 

// Add other common headers here 