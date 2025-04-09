# Minimum CMake version required
cmake_minimum_required(VERSION 3.10)

# Project Name
project(WowInjectDLL LANGUAGES CXX)

# Set C++ standard if desired (optional but good practice)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --- Detours Integration ---
# Define the path to your vendor directory (relative to the main workspace folder)
# Adjust this if you placed the vendor folder elsewhere
set(VENDOR_DIR "${CMAKE_SOURCE_DIR}/vendor")

# Find Detours include directory
find_path(DETOURS_INCLUDE_DIR 
    NAMES detours.h
    PATHS "${VENDOR_DIR}/detours/include"
    DOC "Path to Detours include directory"
    NO_DEFAULT_PATH
)

# Find Detours library (adjust lib.X86 if you built for a different architecture)
find_library(DETOURS_LIBRARY
    NAMES detours.lib
    PATHS "${VENDOR_DIR}/detours/lib.X86" 
    DOC "Path to Detours library file"
    NO_DEFAULT_PATH
)

# Check if Detours was found
if(NOT DETOURS_INCLUDE_DIR)
    message(FATAL_ERROR "Detours include directory not found! Looked in ${VENDOR_DIR}/detours/include")
endif()
if(NOT DETOURS_LIBRARY)
    message(FATAL_ERROR "Detours library (detours.lib) not found! Looked in ${VENDOR_DIR}/detours/lib.X86")
endif()

message(STATUS "Found Detours include: ${DETOURS_INCLUDE_DIR}")
message(STATUS "Found Detours library: ${DETOURS_LIBRARY}")
# --- End Detours Integration ---

# Add the DLL (shared library) target
add_library(${PROJECT_NAME} SHARED 
    dllmain.cpp
    pch.cpp 
    pch.h # Include pch.h here for precompiled header generation
)

# Enable Precompiled Headers RIGHT AFTER add_library
target_precompile_headers(${PROJECT_NAME} PRIVATE pch.h)

# Include directories
target_include_directories(${PROJECT_NAME} PRIVATE 
    # Add the Detours include directory
    ${DETOURS_INCLUDE_DIR} 
    # Add current directory if needed for pch.h discovery
    ${CMAKE_CURRENT_SOURCE_DIR} 
)

# Link necessary libraries
target_link_libraries(${PROJECT_NAME} PRIVATE
    # Add the Detours library
    ${DETOURS_LIBRARY}
    # Add standard Windows libraries needed
    user32.lib # Often needed for Windows API functions
    # d3d9.lib # Might need this if directly calling D3D functions later
)

# Set output directory for the DLL (optional, defaults to build dir)
# set_target_properties(${PROJECT_NAME} PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# Add compile definitions (e.g., for preprocessor macros)
target_compile_definitions(${PROJECT_NAME} PRIVATE
    WIN32_LEAN_AND_MEAN 
    # Add other definitions like _USRDLL, YOURPROJECT_EXPORTS if needed by convention
)

# Ensure correct architecture is targeted (especially for WoW 3.3.5a)
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(WARNING "Building for 64-bit, but WoW 3.3.5a is 32-bit. Ensure your toolchain is set for 32-bit (x86).")
endif() 