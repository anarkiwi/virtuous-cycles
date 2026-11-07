cmake_minimum_required(VERSION 3.20)
# C is enabled because LLVM's CMake config probes libffi and libedit with C
# compiles; without it a configure outside the Docker image fails.
project(vc-cxx-cost C CXX)

find_package(Clang REQUIRED CONFIG)
if(NOT LLVM_VERSION_MAJOR EQUAL 20)
  message(FATAL_ERROR "clang 20 is required, found ${LLVM_VERSION}")
endif()
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
option(VC_COVERAGE "Instrument for source-based coverage" OFF)

add_executable(vc-cxx-cost src/main.cc src/extract.cc src/program.cc
                           src/poly.cc)
target_include_directories(vc-cxx-cost SYSTEM PRIVATE ${LLVM_INCLUDE_DIRS}
                                                      ${CLANG_INCLUDE_DIRS})
target_compile_options(vc-cxx-cost PRIVATE -Wall -Wextra -fno-rtti)
target_link_libraries(vc-cxx-cost PRIVATE clang-cpp LLVM)
if(VC_COVERAGE)
  target_compile_options(vc-cxx-cost PRIVATE -fprofile-instr-generate
                                             -fcoverage-mapping)
  target_link_options(vc-cxx-cost PRIVATE -fprofile-instr-generate)
endif()
install(TARGETS vc-cxx-cost DESTINATION ${LLVM_TOOLS_INSTALL_DIR})
install(DIRECTORY include/vc DESTINATION include)
