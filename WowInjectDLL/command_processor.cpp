// command_processor.cpp
#include "command_processor.h"
#include "ipc_manager.h"      // For SendResponse
#include "game_state.h"
#include "game_actions.h"
#include "lua_interface.h"
#include "globals.h"
#include <string>
#include <stdexcept>
#include <stdio.h> // For sprintf_s
#include <thread> // Added for sleep_for
#include <chrono> // Added for milliseconds

// Helper function prototypes (if logic becomes complex)
// std::string HandleExecLua(const Request& req);
// std::string HandleGetTime(const Request& req);
// ... etc ...

// --- Worker Thread --- 
/* // REMOVED Worker Thread Logic
DWORD WINAPI CommandWorkerThread(LPVOID lpParam) {
    OutputDebugStringA("[Worker] Thread started.\n");
    while (g_running) {
        Request req;
        {
            // Wait for a request to process
            std::unique_lock<std::mutex> lock(g_queueMutex);
            g_requestCv.wait(lock, [] { return !g_processingQueue.empty() || !g_running; });

            // Check if woken up to exit
            if (!g_running) {
                OutputDebugStringA("[Worker] Exiting due to g_running flag.\n");
                break;
            }

            // Get the request
            if (!g_processingQueue.empty()) { 
                req = g_processingQueue.front();
                g_processingQueue.pop();
            } else {
                 // Spurious wake-up or notified while empty, continue waiting
                continue; 
            }
        } // Unlock mutex

        // Process the command (this queues the response)
        OutputDebugStringA("[Worker] Processing request...\n");
        ProcessCommand(req);
        OutputDebugStringA("[Worker] Finished processing request.\n");
    }
    OutputDebugStringA("[Worker] Thread finished.\n");
    return 0;
}
*/

// --- Command Processing Logic --- 
// Processes a single command and queues the response
void ProcessCommand(const Request& req) {
    std::string result = ""; // Initialize result string
    char log_buffer[256]; // For logging

    try {
        sprintf_s(log_buffer, sizeof(log_buffer), "[CmdProc] Processing Type: %d\n", req.type);
        OutputDebugStringA(log_buffer);

        switch (req.type) {
            case REQ_PING:
                result = "PONG";
                break;
            case REQ_EXEC_LUA:
                {
                    std::string luaResult = ExecuteLuaPCall(req.data);
                    // Check if ExecuteLuaPCall already returned an error string
                    if (luaResult.rfind("LUA_RESULT:ERROR:", 0) == 0) {
                        result = luaResult; // Use the error string directly
                    } else {
                        // Otherwise, prepend the success prefix
                        result = "LUA_RESULT:" + (luaResult.empty() ? "nil" : luaResult);
                    }
                }
                break;
            case REQ_GET_TIME_MS:
                {
                    long long time_ms = GetCurrentTimeMillis();
                    result = "TIME_MS:" + std::to_string(time_ms);
                }
                break;
            case REQ_GET_CD:
                {
                    SpellCooldown cd = GetSpellCooldown(req.spell_id);
                    // Format: CD:<start_ms>,<duration_ms>,<enabled_int>
                    long long start_ms = static_cast<long long>(cd.startTime * 1000.0);
                    long long duration_ms = static_cast<long long>(cd.duration * 1000.0);
                    char cd_buf[128];
                    sprintf_s(cd_buf, sizeof(cd_buf), "CD:%lld,%lld,%d", start_ms, duration_ms, cd.enable);
                    result = cd_buf;
                }
                break;
            case REQ_IS_IN_RANGE:
                {
                    // IsSpellInRange takes string for spell, convert ID
                    bool inRange = IsSpellInRange(std::to_string(req.spell_id), req.unit_id);
                    result = std::string("IN_RANGE:") + (inRange ? "1" : "0");
                }
                break;
            case REQ_GET_SPELL_INFO:
                {
                    // Get individual pieces of info using the GetSpellInfo function
                    std::string name = GetSpellInfo(req.spell_id, "name");
                    std::string rank = GetSpellInfo(req.spell_id, "rank");
                    std::string icon = GetSpellInfo(req.spell_id, "icon");
                    std::string costStr = GetSpellInfo(req.spell_id, "cost");
                    std::string powerTypeStr = GetSpellInfo(req.spell_id, "powerType");
                    std::string castTimeStr = GetSpellInfo(req.spell_id, "castTime");
                    std::string minRangeStr = GetSpellInfo(req.spell_id, "minRange");
                    std::string maxRangeStr = GetSpellInfo(req.spell_id, "maxRange");

                    // Convert numeric strings (handle potential errors, default to 0 or -1)
                    double cost = 0.0; try { cost = std::stod(costStr); } catch (...) {}
                    int powerType = -1; try { powerType = std::stoi(powerTypeStr); } catch (...) {}
                    double castTime = -1.0; try { castTime = std::stod(castTimeStr); } catch (...) {}
                    double minRange = -1.0; try { minRange = std::stod(minRangeStr); } catch (...) {}
                    double maxRange = -1.0; try { maxRange = std::stod(maxRangeStr); } catch (...) {}

                    // Format exactly like dllmain.cpp
                    // SPELL_INFO:<name>|<rank>|<castTime_ms>|<minRange>|<maxRange>|<icon>|<cost>|<powerType>
                    char info_buf[1024];
                     sprintf_s(info_buf, sizeof(info_buf), "SPELL_INFO:%s|%s|%.0f|%.1f|%.1f|%s|%.0f|%d",
                               (name.empty() || name == "nil") ? "N/A" : name.c_str(),
                               (rank.empty() || rank == "nil") ? "N/A" : rank.c_str(),
                               castTime, // Assuming GetSpellInfo returns ms or needs conversion
                               minRange,
                               maxRange,
                               (icon.empty() || icon == "nil") ? "N/A" : icon.c_str(),
                               cost,
                               powerType);
                    result = info_buf;
                }
                break;
            case REQ_CAST_SPELL:
                result = CastSpell(req.spell_id, req.target_guid);
                break;
            case REQ_GET_COMBO_POINTS:
                {
                    int cp = GetComboPoints();
                    char cp_buf[64];
                    sprintf_s(cp_buf, sizeof(cp_buf), "CP:%d", cp);
                    result = cp_buf;
                }
                break;
            case REQ_GET_TARGET_GUID:
                {
                    uint64_t guid = GetTargetGUID();
                    char guid_buf[128];
                    // Ensure the format matches Python expectation (0xHEX)
                    sprintf_s(guid_buf, sizeof(guid_buf), "TARGET_GUID:0x%llX", guid);
                    result = guid_buf;
                }
                break;
            case REQ_IS_BEHIND_TARGET:
                result = IsBehindTarget(req.target_guid);
                break;
            case REQ_UNKNOWN:
            default:
                result = "ERR:Unknown command type";
                sprintf_s(log_buffer, sizeof(log_buffer), "[CmdProc] Received unknown command type: %d\n", req.type);
                OutputDebugStringA(log_buffer);
                break;
        }
    } catch (const std::exception& e) {
        result = "ERR:Exception processing command - " + std::string(e.what());
        OutputDebugStringA(("[CmdProc] Exception: " + std::string(e.what()) + "\n").c_str());
    } catch (...) {
        result = "ERR:Unknown exception processing command";
        OutputDebugStringA("[CmdProc] Unknown exception processing command.\n");
    }

    // Queue the result (including errors) for sending by the hook thread
    if (!result.empty()) {
        // Ensure result string is properly formatted (should be handled per-case now)
        char log_buf_resp[256]; // Separate buffer for response logging
        sprintf_s(log_buf_resp, sizeof(log_buf_resp), "[CmdProc] Queuing response: [%.100s]...\n", result.c_str());
        OutputDebugStringA(log_buf_resp);

        {
            std::lock_guard<std::mutex> lock(g_queueMutex);
            g_responseQueue.push(result); // Push the generated result onto the global queue
        }
    } else {
         OutputDebugStringA("[CmdProc] Warning: Empty result generated for request, nothing to queue.\n");
    }
} 