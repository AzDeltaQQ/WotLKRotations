// pch.h: This is a precompiled header file.
// Files listed below are compiled only once, improving build performance for future builds.
// This also affects IntelliSense performance, including code completion and many code browsing features.
// However, files listed here are ALL re-compiled if any one of them is updated between builds.
// Do not add files here that you will be updating frequently as this negates the performance advantage.

#ifndef PCH_H
#define PCH_H

// #define WIN32_LEAN_AND_MEAN             // Exclude rarely-used stuff from Windows headers (Removed due to redefinition warning)
// Windows Header Files
#include <windows.h>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <queue>    // Added back based on globals.h usage
#include <mutex>    // Added back based on globals.h usage
#include <cstdint>  // Added back based on globals.h usage
#include <atomic>   // Added back based on globals.h usage
#include <sstream>

// Define DIRECTINPUT_VERSION before including d3d9.h if necessary
// #define DIRECTINPUT_VERSION 0x0800
#include <d3d9.h> // Required for LPDIRECT3DDEVICE9 and HRESULT

// Include Detours header (ensure it's in your include path)
#include "detours.h"

// Include project headers needed widely
#include "offsets.h" // Included early for global access
#include "globals.h" // Included after offsets

// Add other common headers here

#endif //PCH_H 