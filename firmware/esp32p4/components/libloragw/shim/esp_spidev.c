/* ESP-IDF backend for the spidev calls made by sx1302_hal.
   One SPI device, CS driven by hand so a multi-part SPI_IOC_MESSAGE(n)
   keeps CS low across every part, as Linux spidev does with cs_change=0. */
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_rom_sys.h"
#include "linux/spi/spidev.h"
#include "esp_spidev_cfg.h"

#define ESPDEV_FD 77

static spi_device_handle_t s_dev;
static int s_cs = -1;
static int s_hz = 2000000;
static spi_host_device_t s_host = SPI2_HOST;
static int s_ready;

int espdev_setup(spi_host_device_t host, int sck, int mosi, int miso, int cs, int hz)
{
    s_host = host;
    s_cs = cs;
    s_hz = hz;
    spi_bus_config_t bus = {
        .sclk_io_num = sck,
        .mosi_io_num = mosi,
        .miso_io_num = miso,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 16384 + 64,
    };
    esp_err_t e = spi_bus_initialize(host, &bus, SPI_DMA_CH_AUTO);
    if (e != ESP_OK) return e;
    gpio_config_t g = { .pin_bit_mask = 1ULL << cs, .mode = GPIO_MODE_OUTPUT };
    gpio_config(&g);
    gpio_set_level(cs, 1);
    spi_device_interface_config_t dev = {
        .mode = 0,
        .clock_speed_hz = hz,
        .spics_io_num = -1,
        .queue_size = 1,
    };
    e = spi_bus_add_device(host, &dev, &s_dev);
    if (e == ESP_OK) s_ready = 1;
    /* Weakest drive on the outputs: softer edges, less hash in the receiver. */
    gpio_set_drive_capability(sck, GPIO_DRIVE_CAP_0);
    gpio_set_drive_capability(mosi, GPIO_DRIVE_CAP_0);
    gpio_set_drive_capability(cs, GPIO_DRIVE_CAP_0);
    return e;
}

int espdev_set_speed(int hz)
{
    if (!s_ready) return -1;
    spi_bus_remove_device(s_dev);
    spi_device_interface_config_t dev = {
        .mode = 0,
        .clock_speed_hz = hz,
        .spics_io_num = -1,
        .queue_size = 1,
    };
    esp_err_t e = spi_bus_add_device(s_host, &dev, &s_dev);
    if (e == ESP_OK) s_hz = hz;
    return e;
}

int espdev_get_speed(void) { return s_hz; }

int espdev_open(const char *path, int flags, ...)
{
    (void)flags;
    if (!s_ready || path == NULL || strncmp(path, "/dev/spidev", 11) != 0) return -1;
    return ESPDEV_FD;
}

int espdev_close(int fd)
{
    return fd == ESPDEV_FD ? 0 : -1;
}

static int do_xfer(const struct spi_ioc_transfer *k, unsigned n)
{
    int total = 0;
    spi_device_acquire_bus(s_dev, portMAX_DELAY);
    gpio_set_level(s_cs, 0);
    for (unsigned i = 0; i < n; i++) {
        if (k[i].len == 0) continue;
        spi_transaction_t t = {0};
        t.length = (size_t)k[i].len * 8;
        t.tx_buffer = (const void *)(uintptr_t)k[i].tx_buf;
        t.rx_buffer = (void *)(uintptr_t)k[i].rx_buf;
        if (t.rx_buffer) t.rxlength = t.length;
        if (spi_device_polling_transmit(s_dev, &t) != ESP_OK) {
            gpio_set_level(s_cs, 1);
            spi_device_release_bus(s_dev);
            return -1;
        }
        total += (int)k[i].len;
    }
    gpio_set_level(s_cs, 1);
    spi_device_release_bus(s_dev);
    return total;
}

int espdev_ioctl(int fd, unsigned long req, ...)
{
    va_list ap;
    va_start(ap, req);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    if (fd != ESPDEV_FD) return -1;
    if (req > ESPDEV_IOC_MSG_BASE && req < ESPDEV_IOC_MSG_BASE + 16)
        return do_xfer((const struct spi_ioc_transfer *)arg, (unsigned)(req - ESPDEV_IOC_MSG_BASE));
    /* Mode/speed/bit-order setup: the device is fixed at mode 0, MSB first,
       8-bit; the HAL passes an int it does not read back, so leave it alone. */
    (void)arg;
    switch (req) {
    case SPI_IOC_WR_MODE: case SPI_IOC_RD_MODE:
    case SPI_IOC_WR_BITS_PER_WORD: case SPI_IOC_RD_BITS_PER_WORD:
    case SPI_IOC_WR_MAX_SPEED_HZ: case SPI_IOC_RD_MAX_SPEED_HZ:
    case SPI_IOC_WR_LSB_FIRST: case SPI_IOC_RD_LSB_FIRST:
        return 0;
    default: return -1;
    }
}
