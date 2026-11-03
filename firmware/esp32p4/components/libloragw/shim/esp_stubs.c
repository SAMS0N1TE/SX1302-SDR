/* Stubs for the parts of sx1302_hal this port leaves out.
   - USB/MCU link: the WM1302 here is the SPI version.
   - I2C + STTS751: the temperature sensor I2C is not wired, and lgw_start
     needs a sensor. Report a fixed 25.0 C (used for RSSI compensation only). */
#include <stdint.h>
#include <stdio.h>
#include "loragw_com.h"
#include "loragw_usb.h"
#include "loragw_i2c.h"
#include "loragw_stts751.h"
#include "sx1250_usb.h"
#include "sx1261_usb.h"

#include <time.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_rom_sys.h"

/* wait_ms() in loragw_aux.c uses clock_nanosleep, which newlib on IDF lacks. */
int clock_nanosleep(clockid_t clk, int flags, const struct timespec *req, struct timespec *rem)
{
    (void)clk; (void)flags;
    uint64_t us = (uint64_t)req->tv_sec * 1000000u + (uint64_t)req->tv_nsec / 1000u;
    if (us >= 2000) {
        vTaskDelay(pdMS_TO_TICKS((us + 999) / 1000));
    } else if (us) {
        esp_rom_delay_us((uint32_t)us);
    }
    if (rem) { rem->tv_sec = 0; rem->tv_nsec = 0; }
    return 0;
}

#define NOT_HERE() do { printf("espport: %s not supported (SPI only)\n", __func__); return -1; } while (0)

int lgw_usb_open(const char *p, void **t) { (void)p; (void)t; NOT_HERE(); }
int lgw_usb_close(void *t) { (void)t; NOT_HERE(); }
int lgw_usb_w(void *t, uint8_t m, uint16_t a, uint8_t d) { (void)t; (void)m; (void)a; (void)d; NOT_HERE(); }
int lgw_usb_r(void *t, uint8_t m, uint16_t a, uint8_t *d) { (void)t; (void)m; (void)a; (void)d; NOT_HERE(); }
int lgw_usb_wb(void *t, uint8_t m, uint16_t a, const uint8_t *d, uint16_t s) { (void)t; (void)m; (void)a; (void)d; (void)s; NOT_HERE(); }
int lgw_usb_rb(void *t, uint8_t m, uint16_t a, uint8_t *d, uint16_t s) { (void)t; (void)m; (void)a; (void)d; (void)s; NOT_HERE(); }
int lgw_usb_rmw(void *t, uint16_t a, uint8_t o, uint8_t l, uint8_t d) { (void)t; (void)a; (void)o; (void)l; (void)d; NOT_HERE(); }
int lgw_usb_set_write_mode(lgw_com_write_mode_t w) { (void)w; NOT_HERE(); }
int lgw_usb_flush(void *t) { (void)t; NOT_HERE(); }
uint16_t lgw_usb_chunk_size(void) { return 0; }
int lgw_usb_get_temperature(void *t, float *temp) { (void)t; (void)temp; NOT_HERE(); }

int sx1250_usb_w(void *t, uint8_t m, sx1250_op_code_t o, uint8_t *d, uint16_t s) { (void)t; (void)m; (void)o; (void)d; (void)s; NOT_HERE(); }
int sx1250_usb_r(void *t, uint8_t m, sx1250_op_code_t o, uint8_t *d, uint16_t s) { (void)t; (void)m; (void)o; (void)d; (void)s; NOT_HERE(); }
int sx1261_usb_w(void *t, sx1261_op_code_t o, uint8_t *d, uint16_t s) { (void)t; (void)o; (void)d; (void)s; NOT_HERE(); }
int sx1261_usb_r(void *t, sx1261_op_code_t o, uint8_t *d, uint16_t s) { (void)t; (void)o; (void)d; (void)s; NOT_HERE(); }
int sx1261_usb_set_write_mode(lgw_com_write_mode_t w) { (void)w; NOT_HERE(); }
int sx1261_usb_flush(void *t) { (void)t; NOT_HERE(); }

int i2c_linuxdev_open(const char *path, uint8_t addr, int *fd) { (void)path; (void)addr; *fd = 1; return 0; }
int i2c_linuxdev_close(int fd) { (void)fd; return 0; }
int i2c_linuxdev_read(int fd, uint8_t a, uint8_t r, uint8_t *d) { (void)fd; (void)a; (void)r; *d = 0; return 0; }
int i2c_linuxdev_write(int fd, uint8_t a, uint8_t r, uint8_t d) { (void)fd; (void)a; (void)r; (void)d; return 0; }
int i2c_linuxdev_write_buffer(int fd, uint8_t a, uint8_t *b, uint8_t s) { (void)fd; (void)a; (void)b; (void)s; return 0; }

int stts751_configure(int fd, uint8_t addr) { (void)fd; printf("espport: no temp sensor on this wiring, faking STTS751 at 0x%02X\n", addr); return 0; }
int stts751_get_temperature(int fd, uint8_t addr, float *t) { (void)fd; (void)addr; *t = 25.0f; return 0; }
