# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.16)

# Bootstrap a local configuration without overwriting user settings.
if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.projbuild")
    configure_file("${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.projbuild.example"
                   "${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.projbuild" COPYONLY)
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(HomeVIS-induction)
