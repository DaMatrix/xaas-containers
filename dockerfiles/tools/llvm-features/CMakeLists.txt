cmake_minimum_required(VERSION 3.13.4)
project(ReplaceTargetFeatures)

find_package(LLVM REQUIRED CONFIG)
message(STATUS "Found LLVM ${LLVM_PACKAGE_VERSION}")
message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")

add_definitions(${LLVM_DEFINITIONS})
include_directories(${LLVM_INCLUDE_DIRS})
link_directories(${LLVM_LIBRARY_DIRS})

add_library(ReplaceTargetFeatures MODULE features-pass.cpp)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fno-rtti")

# old, broken code:
#llvm_config(ReplaceTargetFeatures USE_SHARED Core Passes Support)

# the llvm_config() CMake function provided by LLVM doesn't work correctly with shared libraries:
# when LLVM_DYLIB_COMPONENTS is set to "all", it *only* links against libLLVM.so. this breaks if
# the LLVM installation is using split shared libraries (i.e. separate .so libraries for each LLVM
# module), since it tries to link against a single libLLVM.so (which doesn't exist).
# fortunately, the real llvm-config command-line tool *is* able to account for this, so we'll just
# launch that in a subprocess to get the actual link flags.
execute_process(
    COMMAND "${LLVM_TOOLS_BINARY_DIR}/llvm-config" --libs --link-shared Core Passes Support
    OUTPUT_VARIABLE LLVM_LINK_LIBS
    OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY
)
message(STATUS "Linking against LLVM using: ${LLVM_LINK_LIBS}")
target_link_libraries(ReplaceTargetFeatures PRIVATE ${LLVM_LINK_LIBS})
