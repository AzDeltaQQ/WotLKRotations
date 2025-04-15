// hook_manager.h
#pragma once

#include "globals.h"

// Initializes the EndScene hook
void InitializeHook();

// Removes the EndScene hook
void ShutdownHook();

// The hooked EndScene function
HRESULT WINAPI hkEndScene(IDirect3DDevice9* pDevice); 