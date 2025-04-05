-- warrior_simple.lua
-- Basic example rotation script for PyWoW

-- Define spell IDs (replace with actual IDs if needed)
local BATTLE_SHOUT_ID = 6673
local HEROIC_STRIKE_ID = 78 -- Or your rank

-- Simple logic: Maintain Battle Shout and use Heroic Strike on cooldown (conceptually)
-- In this basic example, we'll just try casting Battle Shout if not active.

-- Check if player has Battle Shout buff
-- Note: UnitBuff requires buff name, not ID, in 3.3.5
local has_battle_shout = false
for i = 1, 40 do
    local name, _, _, _, _, _, _, _, _, spellId = UnitBuff("player", i);
    if not name then break end -- No more buffs
    if spellId == BATTLE_SHOUT_ID then
        has_battle_shout = true
        break
    end
end

-- If player doesn't have Battle Shout and isn't casting, cast it.
if not has_battle_shout and not IsCasting() then
    print("[PyWoW Rotation] Casting Battle Shout")
    CastSpellByID(BATTLE_SHOUT_ID)
    -- Adding a small delay conceptually, though Lua execution is fast
    -- In a real bot, you'd check cooldowns/GCD more carefully
    -- return -- Exit script for this tick after casting
end

-- If target exists and is hostile, maybe use Heroic Strike?
if UnitExists("target") and UnitCanAttack("player", "target") then
    -- Check if Heroic Strike is usable (enough rage, off GCD etc.) - Complex check omitted
    -- For now, just print a message if target exists
    -- print("[PyWoW Rotation] Target exists, consider Heroic Strike")
    -- CastSpellByID(HEROIC_STRIKE_ID)
end

-- print("[PyWoW Rotation] Tick") -- Optional debug print every tick 