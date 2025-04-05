-- rogue_level2.lua
-- Very basic example for a low-level rogue

-- Define Spell IDs (Replace with correct rank ID if needed)
local SINISTER_STRIKE_ID = 1752 -- Rank 1 Sinister Strike

-- Check if we have a hostile target
if UnitExists("target") and UnitCanAttack("player", "target") then
    -- Check if Sinister Strike is usable (enough energy, off GCD etc.) - Complex checks omitted
    -- Check if we are not currently casting/channeling
    if not IsCasting() then
        -- print("[PyWoW Rotation] Using Sinister Strike")
        CastSpellByID(SINISTER_STRIKE_ID)
    end
end

-- print("[PyWoW Rotation] Rogue Tick") -- Optional debug 