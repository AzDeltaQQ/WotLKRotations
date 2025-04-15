// game_state.cpp
#include "game_state.h"
#include "lua_interface.h" // For ExecuteLuaWithResult
#include "offsets.h"       // Need offsets for memory reads & function ptrs
#include "globals.h"
#include <windows.h>
#include <cmath>   // For std::abs, acos
#include <stdio.h> // For sprintf_s
#include <vector>  // For vector math

// Simple memory read function template (Consider a safer implementation)
template <typename T>
T ReadMemory(uintptr_t address) {
    if (address == 0) return T{};
    // Add IsBadReadPtr check for more safety before dereferencing?
    if (IsBadReadPtr((void*)address, sizeof(T))) {
        OutputDebugStringA(("[GameState] ReadMemory Error: Invalid address 0x" + std::to_string(address) + "\n").c_str());
        return T{};
    }
    try {
        return *(reinterpret_cast<T*>(address));
    }
    catch (...) {
        OutputDebugStringA(("[GameState] ReadMemory Exception at address: 0x" + std::to_string(address) + "\n").c_str());
        return T{};
    }
}

// --- Direct Memory Reads ---
uint64_t GetTargetGUID() {
    // Read target GUID directly from static memory address
    uint64_t targetGuid = *(uint64_t*)LOCAL_TARGET_GUID_STATIC; // Removed offsets::
    return targetGuid;
}

int GetComboPoints() {
    // Read combo points directly from static memory address
    BYTE comboPoints = *(BYTE*)COMBO_POINTS_ADDR; // Removed offsets::
    return static_cast<int>(comboPoints);
}

// --- Lua-Based State Reads ---
long long GetCurrentTimeMillis() {
    // Simple Lua execution to get time
    std::string result = ExecuteLuaPCall("return GetTime() * 1000"); // Use renamed function
    try {
        return std::stoll(result);
    } catch (const std::invalid_argument& ia) {
        (void)ia; // Suppress unused variable warning
        // Log error: Could not convert result to long long
        return -1;
    } catch (const std::out_of_range& oor) {
        (void)oor; // Suppress unused variable warning
        // Log error: Result out of range for long long
        return -1;
    }
}

SpellCooldown GetSpellCooldown(int spellId) {
    std::string luaCode = "local startTime, duration, enable = GetSpellCooldown(" + std::to_string(spellId) + "); return string.format(\"%f %f %d\", startTime or 0, duration or 0, enable or 0)";
    std::string result = ExecuteLuaPCall(luaCode); // Use renamed function

    SpellCooldown cd = {0.0, 0.0, 0};
    std::stringstream ss(result);
    std::string segment;
    std::vector<std::string> seglist;

    while(std::getline(ss, segment, ' ')) {
       seglist.push_back(segment);
    }

    if (seglist.size() == 3) {
        try {
            cd.startTime = std::stod(seglist[0]);
            cd.duration = std::stod(seglist[1]);
            cd.enable = std::stoi(seglist[2]);
        } catch (...) {
            // Handle potential conversion errors (e.g., log)
        }
    }
    return cd;
}

// Function to check if a spell is usable (basic range check)
// Note: WoW's IsSpellInRange is complex. This is a simplified Lua check.
// unitId: "player", "target", "focus", etc.
bool IsSpellInRange(const std::string& spellNameOrId, const std::string& unitId) {
    if (unitId.empty()) return false; // Need a unit

    // Try to convert spellNameOrId to an integer ID first
    int spellId = 0;
    try {
        spellId = std::stoi(spellNameOrId);
    } catch (...) {
        // If conversion fails, assume it's a name
    }

    std::string luaCode;
    if (spellId > 0) {
        luaCode = "local inRange = IsSpellInRange(" + std::to_string(spellId) + ", \"" + unitId + "\"); return tostring(inRange == 1)";
    } else {
        // Escape the spell name for Lua string literal
        std::string escapedSpellName = spellNameOrId;
        // Basic escaping: replace backslashes and quotes (add more if needed)
        size_t pos = 0;
        while ((pos = escapedSpellName.find('\\', pos)) != std::string::npos) {
            escapedSpellName.replace(pos, 1, "\\\\");
            pos += 2;
        }
        pos = 0;
        while ((pos = escapedSpellName.find('\"', pos)) != std::string::npos) {
            escapedSpellName.replace(pos, 1, "\\\"");
            pos += 2;
        }
        luaCode = "local inRange = IsSpellInRange(\"" + escapedSpellName + "\", \"" + unitId + "\"); return tostring(inRange == 1)";
    }

    std::string result = ExecuteLuaPCall(luaCode); // Use renamed function
    return result == "true";
}

// Function to get spell info (example: Rank)
// Returns an empty string on failure or if info not found
std::string GetSpellInfo(int spellId, const std::string& infoType /* = "rank" */) {
     // Example Lua to get spell rank. Adapt infoType for other details.
     std::string luaCode = "local name, rank = GetSpellInfo(" + std::to_string(spellId) + ");";
    if (infoType == "rank") {
        luaCode += " return rank";
    } else if (infoType == "name") {
        luaCode += " return name";
    } else {
        // Add more info types as needed (e.g., cost, castTime, texture)
        luaCode += " return nil"; // Default to nil if infoType is unknown
    }

    std::string result = ExecuteLuaPCall(luaCode); // Use renamed function
    return result; // Return the direct string result from Lua
}

// --- Internal Function-Based State Reads ---

// Define Vector3 struct for position calculations
struct Vector3 {
    float X, Y, Z;
};

// Helper to read position
Vector3 GetUnitPosition(void* unitPtr) {
    Vector3 pos = {0.0f, 0.0f, 0.0f};
    if (unitPtr) {
        try {
            pos.X = ReadMemory<float>((uintptr_t)unitPtr + OBJECT_POS_X); // Removed offsets::
            pos.Y = ReadMemory<float>((uintptr_t)unitPtr + OBJECT_POS_Y); // Removed offsets::
            pos.Z = ReadMemory<float>((uintptr_t)unitPtr + OBJECT_POS_Z); // Removed offsets::
        } catch (...) { /* Handle error */ }
    }
    return pos;
}

// Helper to read rotation (facing)
float GetUnitRotation(void* unitPtr) {
    if (unitPtr) {
        try {
            return ReadMemory<float>((uintptr_t)unitPtr + OBJECT_ROTATION); // Removed offsets::
        } catch (...) { /* Handle error */ }
    }
    return 0.0f;
}

std::string IsBehindTarget(uint64_t targetGuid) {
    char log_buffer[256];

    // Function pointer types
    typedef void* (__cdecl* findObjectByGuidAndFlags_t)(uint64_t guid, int flags);
    typedef bool(__thiscall* IsUnitVectorDifferenceWithinHemisphereFn)(void* pThisObserver, void* pObserved);

    // Function addresses (Using known working addresses from old code)
    const findObjectByGuidAndFlags_t findObjectByGuidAndFlags = (findObjectByGuidAndFlags_t)0x004D4DB0; 
    const IsUnitVectorDifferenceWithinHemisphereFn isUnitVectorDifferenceWithinHemisphere = (IsUnitVectorDifferenceWithinHemisphereFn)0x0071BC50; 

    // Object Manager related addresses/offsets from offsets.h (Verified)
    const uintptr_t CLIENT_CONNECTION_ADDR = STATIC_CLIENT_CONNECTION; // Removed offsets::
    const uintptr_t OBJECT_MANAGER_OFFSET_VAL = OBJECT_MANAGER_OFFSET; // Removed offsets::, Renamed to avoid conflict with macro
    const uintptr_t LOCAL_GUID_OFFSET_VAL = LOCAL_GUID_OFFSET; // Removed offsets::, Renamed to avoid conflict with macro

    // Pointers to player and target objects
    void* pPlayer = nullptr;
    void* pTarget = nullptr;
    uint64_t playerGuid = 0;

    try {
        OutputDebugStringA("[GameState|IsBehind] Entering function.\n");
        // Check function pointer validity
        if (!findObjectByGuidAndFlags) {
            OutputDebugStringA("[GameState|IsBehind] Error: findObjectByGuidAndFlags pointer NULL.\n");
            return "[ERROR:findObjectFunc null]";
        }
        if (!isUnitVectorDifferenceWithinHemisphere) { // Check the other crucial function pointer too
             OutputDebugStringA("[GameState|IsBehind] Error: isUnitVectorDifferenceWithinHemisphere pointer NULL.\n");
             return "[ERROR:HemisphereFunc null]";
        }

        // Get Player GUID dynamically
        OutputDebugStringA("[GameState|IsBehind] Reading ClientConnection...\n");
        uintptr_t clientConnection = ReadMemory<uintptr_t>(CLIENT_CONNECTION_ADDR);
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] ClientConnection: 0x%p\n", (void*)clientConnection);
        OutputDebugStringA(log_buffer);
        if (!clientConnection) {
            OutputDebugStringA("[GameState|IsBehind] Error: ClientConnection NULL.\n");
            return "[ERROR:CC null]";
        }

        OutputDebugStringA("[GameState|IsBehind] Reading ObjectManager base...\n");
        uintptr_t objMgrBase = ReadMemory<uintptr_t>(clientConnection + OBJECT_MANAGER_OFFSET_VAL); // Use renamed var
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] ObjectManager Base: 0x%p\n", (void*)objMgrBase);
        OutputDebugStringA(log_buffer);
        if (!objMgrBase) {
             OutputDebugStringA("[GameState|IsBehind] Error: ObjectManager base NULL.\n");
            return "[ERROR:OM null]";
        }

        OutputDebugStringA("[GameState|IsBehind] Reading Player GUID...\n");
        playerGuid = ReadMemory<uint64_t>(objMgrBase + LOCAL_GUID_OFFSET_VAL); // Use renamed var
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Player GUID: 0x%llX\n", playerGuid);
        OutputDebugStringA(log_buffer);
        if (playerGuid == 0) {
            OutputDebugStringA("[GameState|IsBehind] Error: Player GUID is 0.\n");
            return "[ERROR:PlayerGUID 0]";
        }

        // Find Player object pointer
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Calling findObjectByGuidAndFlags for Player (GUID: 0x%llX)...\n", playerGuid);
        OutputDebugStringA(log_buffer);
        pPlayer = findObjectByGuidAndFlags(playerGuid, 1);
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Player object pointer: 0x%p\n", pPlayer);
        OutputDebugStringA(log_buffer);
        if (!pPlayer) {
            sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Error: Player object not found (GUID: 0x%llX).\n", playerGuid);
            OutputDebugStringA(log_buffer);
            return "[ERROR:PlayerLookup fail]";
        }

        // Find Target object pointer
        if (targetGuid == 0) {
             OutputDebugStringA("[GameState|IsBehind] Error: Target GUID is 0.\n");
             return "[ERROR:TargetGUID 0]";
        }
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Calling findObjectByGuidAndFlags for Target (GUID: 0x%llX)...\n", targetGuid);
        OutputDebugStringA(log_buffer);
        pTarget = findObjectByGuidAndFlags(targetGuid, 1);
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Target object pointer: 0x%p\n", pTarget);
        OutputDebugStringA(log_buffer);
        if (!pTarget) {
             sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Error: Target object not found (GUID: 0x%llX).\n", targetGuid);
             OutputDebugStringA(log_buffer);
            return "[ERROR:TargetLookup fail]";
        }

        // --- Perform the check using the game's function ---
        // Function pointer type defined above
        // Function address defined above
        // Function pointer validity checked above

        // *** Implement the dual-call logic from the old code ***
        bool result = false;
        try {
            sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Calling isUnitVectorDifferenceWithinHemisphere(pTarget=0x%p, pPlayer=0x%p)...\n", pTarget, pPlayer);
            OutputDebugStringA(log_buffer);
            bool observedInFrontHemisphere_TargetObserver = isUnitVectorDifferenceWithinHemisphere(pTarget, pPlayer);
            sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Result 1 (TgtObs->PlayerInFront): %d\n", observedInFrontHemisphere_TargetObserver);
            OutputDebugStringA(log_buffer);

            sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Calling isUnitVectorDifferenceWithinHemisphere(pPlayer=0x%p, pTarget=0x%p)...\n", pPlayer, pTarget);
            OutputDebugStringA(log_buffer);
            bool observedInFrontHemisphere_PlayerObserver = isUnitVectorDifferenceWithinHemisphere(pPlayer, pTarget);
            sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Result 2 (PlayerObs->TgtInFront): %d\n", observedInFrontHemisphere_PlayerObserver);
            OutputDebugStringA(log_buffer);
            
            // Calculate final result based on the two checks
            result = (!observedInFrontHemisphere_TargetObserver && observedInFrontHemisphere_PlayerObserver);

            sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Final Result: %d\n", result);
            OutputDebugStringA(log_buffer);

        } catch (...) {
             OutputDebugStringA("[GameState|IsBehind] Check Error: Access violation during isUnitVectorDifferenceWithinHemisphere call.\n");
             return "[ERROR:AV checking position]";
        }

        // Format response based on 'result' boolean
        sprintf_s(log_buffer, sizeof(log_buffer), "[IS_BEHIND_TARGET_OK:%d]", result ? 1 : 0);
        OutputDebugStringA("[GameState|IsBehind] Returning successfully.\n"); // Added success log
        return std::string(log_buffer);

    } catch (const std::exception& e) {
        sprintf_s(log_buffer, sizeof(log_buffer), "[GameState|IsBehind] Exception: %s\n", e.what());
        OutputDebugStringA(log_buffer);
        return "[ERROR:Exception]";
    } catch (...) {
        // Catch potential memory access violations during object lookups etc.
        OutputDebugStringA("[GameState|IsBehind] CRITICAL ERROR: Unhandled exception or Memory access violation.\n");
        return "[ERROR:UnhandledCrash]";
    }
} 