// game_actions.h
#pragma once

#include "globals.h"
#include <string>
#include <cstdint>

// Functions for performing actions in the game

// Calls the internal CastSpell function
std::string CastSpell(int spellId, uint64_t targetGuid); 