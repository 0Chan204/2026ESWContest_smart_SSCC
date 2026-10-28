cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED IDF_TARGET AND NOT DEFINED ENV{IDF_TARGET})
    set(IDF_TARGET "esp32c6" CACHE STRING "ESP-IDF target")
endif()
set(SUPPORTED_TARGETS esp32c6)

# Keep connection details local; never overwrite existing user settings.
if(NOT EXISTS "${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.projbuild")
    configure_file("${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.projbuild.example"
                   "${CMAKE_CURRENT_LIST_DIR}/main/Kconfig.projbuild" COPYONLY)
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(kitchen-light-hood)
