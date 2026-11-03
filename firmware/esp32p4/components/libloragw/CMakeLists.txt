set(hal_srcs
    src/loragw_aux.c
    src/loragw_cal.c
    src/loragw_com.c
    src/loragw_debug.c
    src/tinymt32.c
    src/loragw_hal.c
    src/loragw_lbt.c
    src/loragw_reg.c
    src/loragw_spi.c
    src/loragw_ad5338r.c
    src/loragw_sx1250.c
    src/loragw_sx125x.c
    src/loragw_sx1261.c
    src/loragw_sx1302.c
    src/loragw_sx1302_rx.c
    src/loragw_sx1302_timestamp.c
    src/sx1250_com.c
    src/sx1250_spi.c
    src/sx125x_com.c
    src/sx125x_spi.c
    src/sx1261_com.c
    src/sx1261_spi.c
    shim/esp_spidev.c
    shim/esp_stubs.c)

idf_component_register(SRCS ${hal_srcs}
                       INCLUDE_DIRS inc shim
                       PRIV_INCLUDE_DIRS src
                       REQUIRES esp_driver_spi esp_driver_gpio esp_rom)

set_source_files_properties(
    src/loragw_spi.c src/sx1250_spi.c src/sx125x_spi.c src/sx1261_spi.c
    PROPERTIES COMPILE_OPTIONS "-include;${CMAKE_CURRENT_SOURCE_DIR}/shim/esp_spidev.h")

target_compile_options(${COMPONENT_LIB} PRIVATE
    -Wno-error -Wno-error=all -Wno-address -Wno-unused-variable -Wno-unused-but-set-variable -Wno-format
    -Wno-sign-compare -Wno-maybe-uninitialized -Wno-unused-function -Wno-implicit-fallthrough
    -Wno-stringop-truncation -Wno-format-truncation -Wno-array-bounds)
