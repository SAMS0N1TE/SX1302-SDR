#pragma once
#include "driver/spi_master.h"

/* Call once before lgw_connect/lgw_start. */
int espdev_setup(spi_host_device_t host, int sck, int mosi, int miso, int cs, int hz);
int espdev_set_speed(int hz);
int espdev_get_speed(void);
