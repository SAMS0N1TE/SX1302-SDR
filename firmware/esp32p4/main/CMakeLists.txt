idf_component_register(SRCS "main.c" "p25_sync.c"
                       INCLUDE_DIRS "."
                       REQUIRES libloragw esp_driver_uart esp_driver_gpio esp_timer esp_rom)

target_link_options(${COMPONENT_LIB} INTERFACE "-Wl,--wrap=sx1250_calibrate")
