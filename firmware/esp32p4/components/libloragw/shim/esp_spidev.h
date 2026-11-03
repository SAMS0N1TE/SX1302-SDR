/* Force-included into the HAL's *_spi.c files only. Routes their
   open/ioctl/close on "/dev/spidev*" to the ESP-IDF SPI master. */
#pragma once
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>

int espdev_open(const char *path, int flags, ...);
int espdev_ioctl(int fd, unsigned long req, ...);
int espdev_close(int fd);

#define open  espdev_open
#define ioctl espdev_ioctl
#define close espdev_close
