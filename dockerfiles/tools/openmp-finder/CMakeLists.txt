cmake_minimum_required(VERSION 3.13)
project(omp-finder)

find_package(LLVM REQUIRED CONFIG)
message(STATUS "Found LLVM ${LLVM_PACKAGE_VERSION}")
message(STATUS "Using LLVMConfig.cmake in: ${LLVM_DIR}")

add_definitions(${LLVM_DEFINITIONS})
include_directories(${LLVM_INCLUDE_DIRS})
link_directories(${LLVM_LIBRARY_DIRS})

find_package(Clang REQUIRED CONFIG)
message(STATUS "Found Clang ${LLVM_VERSION}") # not a typo, ClangConfig.cmake really does set a variable called LLVM_VERSION
message(STATUS "Using ClangConfig.cmake in: ${CLANG_INSTALL_PREFIX}")

include_directories(${CLANG_INCLUDE_DIRS})

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_executable(omp-finder omp_finder.cpp)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fno-rtti")

target_link_libraries(omp-finder
  #linking against these means that the final executable will link against the shared libraries
  clang
  clang-cpp

  #full enumeration of all the clang components we're actually compiling against
  # clangTooling
  # clangFrontend
  # clangASTMatchers
  # clangAST
  # clangBasic
  # clangSerialization
)

#old, broken code:
# llvm_config(omp-finder USE_SHARED Support FrontendOpenMP)

# the llvm_config() CMake function provided by LLVM doesn't work correctly with shared libraries:
# when LLVM_DYLIB_COMPONENTS is set to "all", it *only* links against libLLVM.so. this breaks if
# the LLVM installation is using split shared libraries (i.e. separate .so libraries for each LLVM
# module), since it tries to link against a single libLLVM.so (which doesn't exist).
# fortunately, the real llvm-config command-line tool *is* able to account for this, so we'll just
# launch that in a subprocess to get the actual link flags.
execute_process(
    COMMAND "${LLVM_TOOLS_BINARY_DIR}/llvm-config" --libs --link-shared Support FrontendOpenMP
    OUTPUT_VARIABLE LLVM_LINK_LIBS
    OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY
)
message(STATUS "Linking against LLVM using: ${LLVM_LINK_LIBS}")
target_link_libraries(omp-finder ${LLVM_LINK_LIBS})
