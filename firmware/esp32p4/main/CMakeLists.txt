idf_component_register(SRCS "main.c"
                       INCLUDE_DIRS "."
                       REQUIRES libloragw esp_driver_uart esp_driver_gpio esp_timer esp_rom)
