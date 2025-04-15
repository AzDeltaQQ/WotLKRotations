// game_state.h
#pragma once

#include "globals.h"
#include <string>
#include <cstdint>
#include <vector>
#include <sstream>

// --- Structs ---
struct SpellCooldown {
    double startTime = 0.0;
    double duration = 0.0;
    int enable = 0; // Or bool?
};

// Functions for reading game state information

// Gets the current target's GUID from static memory
uint64_t GetTargetGUID();

// Gets the current combo points from static memory
int GetComboPoints();

// Gets the current in-game time in milliseconds via Lua
std::string GetTimeMsLua();

// Gets spell cooldown info via Lua
std::string GetSpellCooldownLua(int spellId);

// Gets spell info via Lua
std::string GetSpellInfoLua(int spellId);

// Checks if a spell is in range of a unit via Lua
std::string IsSpellInRangeLua(int spellId, const std::string& unitId);

// Checks if the player is behind the target GUID
std::string IsBehindTarget(uint64_t targetGuid);

// --- Functions for reading game state information ---

// --- Direct Memory Reads ---
uint64_t GetTargetGUID();
int GetComboPoints();

// --- Lua-Based State Reads ---
long long GetCurrentTimeMillis();
SpellCooldown GetSpellCooldown(int spellId);
bool IsSpellInRange(const std::string& spellNameOrId, const std::string& unitId);
std::string GetSpellInfo(int spellId, const std::string& infoType = "rank");
bool IsPlayerBehindUnit(const std::string& unitId);

// --- Internal Function-Based State Reads ---
std::string IsBehindTarget(uint64_t targetGuid); // This one uses internal funcs

// Consider adding declarations for internal helpers if needed elsewhere
// struct Vector3; 
// Vector3 GetUnitPosition(void* unitPtr);
// float GetUnitRotation(void* unitPtr); 