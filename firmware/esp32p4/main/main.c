/* SX1302 (Seeed WM1302 in a Heltec HT-HC01P debug board) on the ESP32-P4-NANO.
   Semtech sx1302_hal runs unchanged over a spidev shim. Console on UART0.

   Wiring (debug-board header -> Nano):
     CLK  -> GPIO2    MISO -> GPIO3    MOSI -> GPIO6    CS -> GPIO53
     RESET (SX1302_RESET, active high) -> GPIO23
     INT   (SX1262_RESET, active low)  -> GPIO22, held low (its CSN is not broken out)

   Commands: see help. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_timer.h"
#include "esp_rom_crc.h"
#include "esp_rom_sys.h"
#include "loragw_hal.h"
#include "loragw_reg.h"
#include "loragw_com.h"
#include "loragw_aux.h"
#include "esp_spidev_cfg.h"

#define PIN_SCK   2
#define PIN_MOSI  6
#define PIN_MISO  3
#define PIN_CS    53
#define PIN_RST   23
#define PIN_1262_RST 22

#define CAP_SIZE 0x4000

static const uint32_t s_fs[32] = {4e6, 4e6, 4e6, 4e6, 4e6, 4e6, 4e6, 0, 0, 1e6, 125e3, 125e3, 125e3, 125e3, 125e3, 125e3, 125e3, 125e3, 8e6, 125e3, 125e3, 125e3, 0, 32e6, 32e6, 0, 32e6, 32e6, 0, 32e6, 32e6, 32e6};
static uint8_t s_buf[CAP_SIZE];
static uint32_t s_rf0 = 904300000, s_rf1 = 905000000;
static int s_started;
static uint32_t s_cal_anchor;

/* Only the image-rejection calibration table selection changes. The RF
   synthesizer and channelizer still receive the requested frequencies. */
extern int __real_sx1250_calibrate(uint8_t chain, uint32_t hz);
int __wrap_sx1250_calibrate(uint8_t chain, uint32_t hz)
{
    return __real_sx1250_calibrate(chain, s_cal_anchor ? s_cal_anchor : hz);
}

static void hw_reset(void)
{
    gpio_config_t g = { .pin_bit_mask = (1ULL << PIN_RST) | (1ULL << PIN_1262_RST), .mode = GPIO_MODE_OUTPUT };
    gpio_config(&g);
    gpio_set_level(PIN_1262_RST, 0);
    gpio_set_level(PIN_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(100));
    gpio_set_level(PIN_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(100));
}

static int read_version(void)
{
    int32_t v = -1;
    if (lgw_reg_r(SX1302_REG_COMMON_VERSION_VERSION, &v) != LGW_REG_SUCCESS) return -1;
    return (int)v;
}

static int configure(void)
{
    struct lgw_conf_board_s b = {0};
    b.lorawan_public = true;
    b.clksrc = 0;
    b.full_duplex = false;
    b.com_type = LGW_COM_SPI;
    strcpy(b.com_path, "/dev/spidev0.0");
    if (lgw_board_setconf(&b) != LGW_HAL_SUCCESS) return -1;

    struct lgw_conf_rxrf_s rf = {0};
    rf.enable = true;
    rf.type = LGW_RADIO_TYPE_SX1250;
    rf.rssi_offset = -215.4f;
    rf.freq_hz = s_rf0;
    rf.tx_enable = true;
    if (lgw_rxrf_setconf(0, &rf) != LGW_HAL_SUCCESS) return -2;
    rf.freq_hz = s_rf1;
    rf.tx_enable = false;
    if (lgw_rxrf_setconf(1, &rf) != LGW_HAL_SUCCESS) return -3;

    static const int32_t ifs[8] = {-400000, -200000, 0, -400000, -200000, 0, 200000, 400000};
    static const uint8_t rfc[8] = {0, 0, 0, 1, 1, 1, 1, 1};
    for (int i = 0; i < 8; i++) {
        struct lgw_conf_rxif_s ifc = {0};
        ifc.enable = true;
        ifc.rf_chain = rfc[i];
        ifc.freq_hz = ifs[i];
        if (lgw_rxif_setconf(i, &ifc) != LGW_HAL_SUCCESS) return -10 - i;
    }
    return 0;
}

static int do_start(void)
{
    int e = configure();
    if (e) { printf("configure failed %d\n", e); return e; }
    int64_t t0 = esp_timer_get_time();
    e = lgw_start();
    printf("lgw_start -> %d in %lld ms\n", e, (esp_timer_get_time() - t0) / 1000);
    s_started = (e == LGW_HAL_SUCCESS);
    return e;
}

/* One-shot capture into s_buf, as test_loragw_capture_ram.c does. */
static int capture_at_rate(int src, int wrap, uint32_t fs, int second)
{
    uint16_t period = fs ? (uint16_t)(32e6 / fs - 1) : 0;
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_ENABLE, 1);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTUREWRAP, wrap);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_RAMCONFIG, second >= 0);
    if (second >= 0) lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_B_SOURCEMUX, second);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_A_SOURCEMUX, src);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_PERIOD_0_CAPTUREPERIOD, period & 0xFF);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_PERIOD_1_CAPTUREPERIOD, (period >> 8) & 0xFF);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 1);
    if (wrap) return 0;
    /* Stay off the SPI bus while the RAM fills; SPI edges couple into the receiver. */
    if (fs) {
        uint32_t us = (uint32_t)(4096.0 * 1e6 / fs) + 500;
        if (us > 3000) vTaskDelay(pdMS_TO_TICKS(us / 1000 + 1));
        else esp_rom_delay_us(us);
    }
    int32_t done = 0;
    int64_t t0 = esp_timer_get_time();
    while (!done && esp_timer_get_time() - t0 < 500000) {
        lgw_reg_r(SX1302_REG_CAPTURE_RAM_STATUS_CAPCOMPLETE, &done);
    }
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 0);
    if (!done) return -1;
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
    int e = lgw_mem_rb(0, s_buf, CAP_SIZE, false);
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
    return e;
}

static int capture(int src, int wrap)
{
    return capture_at_rate(src, wrap, s_fs[src & 31], -1);
}

/* One-shot capture with deliberate SPI load while the RAM fills:
   mode 0 quiet, 1 single-register polls, 2 1 KB bursts from the RX buffer
   (0x4000, page 0), 3 1 KB bursts from the capture RAM (page 1). */
static uint8_t s_junk[1024];
static int s_load_bytes = 1024;
static int ring_wptr(void);

static int capture_load(int src, int mode)
{
    uint32_t fs = s_fs[src & 31];
    if (!fs) return -1;
    if ((mode == 6 || mode == 7) && (fs != 125000 || espdev_get_speed() != 16000000)) return -3;
    uint16_t period = (uint16_t)(32e6 / fs - 1);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_ENABLE, 1);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTUREWRAP, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_RAMCONFIG, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_A_SOURCEMUX, src);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_PERIOD_0_CAPTUREPERIOD, period & 0xFF);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_PERIOD_1_CAPTUREPERIOD, (period >> 8) & 0xFF);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 1);
    int64_t t0 = esp_timer_get_time(), fill = (int64_t)(4096.0 * 1e6 / fs);
    long n = 0;
    while (esp_timer_get_time() - t0 < fill) {
        uint8_t v;
        if (mode == 1) lgw_com_r(LGW_SPI_MUX_TARGET_SX1302, 0x5606, &v);
        else if (mode == 2) lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, 0x4000, s_junk, (uint16_t)s_load_bytes);
        else if (mode == 3) {
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
            lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, 0x3C00, s_junk, (uint16_t)s_load_bytes);
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
        } else if (mode == 6 || mode == 7) {
            /* At 125 kS/s a 1 KiB read at 16 MHz spans about 65 writer
               positions. Leave 256 words before each half boundary. */
            int w = ring_wptr();
            if (w < 0 || (w & 2047) >= 1792) continue;
            int half = (w >> 11) ^ (mode == 7);
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
            lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, half * 8192 + 4096, s_junk, (uint16_t)s_load_bytes);
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
        } else if (mode == 4) {
            /* page 1 held for as long as a burst of s_load_bytes would take, no reads */
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
            esp_rom_delay_us((uint32_t)(s_load_bytes * 8LL * 1000000 / espdev_get_speed()));
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
            esp_rom_delay_us(100);
        } else if (mode == 5) {
            /* page 1, then 4-byte reads spread over the same time */
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
            for (int k = 0; k < s_load_bytes / 4; k++) lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, 0x3C00 + 4 * k, s_junk, 4);
            lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
            esp_rom_delay_us(100);
        } else { esp_rom_delay_us(100); continue; }
        n++;
    }
    int32_t done = 0;
    int64_t t1 = esp_timer_get_time();
    while (!done && esp_timer_get_time() - t1 < 200000) lgw_reg_r(SX1302_REG_CAPTURE_RAM_STATUS_CAPCOMPLETE, &done);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 0);
    if (!done) return -2;
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
    int e = lgw_mem_rb(0, s_buf, CAP_SIZE, false);
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
    printf("capx src %d mode %d: %ld transactions during fill\n", src, mode, n);
    return e;
}

/* One-shot capture in 2k x 64 mode with two sources. */
static int capture2(int sa, int sb)
{
    uint32_t fs = s_fs[sa & 31];
    if (!fs) return -1;
    uint16_t period = (uint16_t)(32e6 / fs - 1);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_ENABLE, 1);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTUREWRAP, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_RAMCONFIG, 1);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_A_SOURCEMUX, sa);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_B_SOURCEMUX, sb);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_PERIOD_0_CAPTUREPERIOD, period & 0xFF);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_PERIOD_1_CAPTUREPERIOD, (period >> 8) & 0xFF);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 1);
    uint32_t us = (uint32_t)(4096.0 * 1e6 / fs) + 500;
    if (us > 3000) vTaskDelay(pdMS_TO_TICKS(us / 1000 + 1)); else esp_rom_delay_us(us);
    int32_t done = 0;
    int64_t t0 = esp_timer_get_time();
    while (!done && esp_timer_get_time() - t0 < 500000) lgw_reg_r(SX1302_REG_CAPTURE_RAM_STATUS_CAPCOMPLETE, &done);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_RAMCONFIG, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_SOURCE_B_SOURCEMUX, 0);
    printf("cap2 %d %d: done %ld after %lld us\n", sa, sb, (long)done, esp_timer_get_time() - t0 + us);
    if (!done) return -2;
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
    int e = lgw_mem_rb(0, s_buf, CAP_SIZE, false);
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
    return e;
}

/* Load a small program into the AGC MCU (a PIC16-style core, 4096 x 14-bit
   words; the upper two bits store popcount(op) modulo four; this test can
   force bit 15 to exercise the parity flag). The test program counts in file register 0x1B, which
   the host reads as AGC status (0x5781):
       000 CLRF 0x1B / 001 CLRF 0x22 / 002 DECFSZ 0x22,F / 003 GOTO 002
       004 INCF 0x1B,F / 005 GOTO 002
   One count every 256 x 3 + 3 = 771 instruction cycles. */
static uint8_t s_img[8192];

static uint16_t pic_word(uint16_t op, int b15)
{
    op &= 0x3FFF;
    int p = __builtin_parity(op);
    return op | (uint16_t)(p << 14) | (uint16_t)(b15 << 15);
}

static void mcu_test(int b15)
{
    static const uint16_t prog[] = {0x019B, 0x01A2, 0x0BA2, 0x2802, 0x0A9B, 0x2802};
    for (int i = 0; i < 4096; i++) {
        uint16_t w = i < (int)(sizeof prog / 2) ? pic_word(prog[i], b15) : pic_word(0x3FFF, 1);
        s_img[2 * i] = w & 0xFF;
        s_img[2 * i + 1] = w >> 8;
    }
    int32_t v = 0;
    lgw_reg_w(SX1302_REG_AGC_MCU_CTRL_MCU_CLEAR, 1);
    lgw_reg_w(SX1302_REG_AGC_MCU_CTRL_HOST_PROG, 1);
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
    lgw_mem_wb(0x0000, s_img, sizeof s_img);
    lgw_mem_rb(0x0000, s_buf, sizeof s_img, false);
    int same = !memcmp(s_img, s_buf, sizeof s_img);
    lgw_reg_w(SX1302_REG_AGC_MCU_CTRL_HOST_PROG, 0);
    lgw_reg_w(SX1302_REG_AGC_MCU_CTRL_MCU_CLEAR, 0);
    lgw_reg_r(SX1302_REG_AGC_MCU_CTRL_PARITY_ERROR, &v);
    printf("mcutest bit15=%d: readback %s, parity error %ld\n", b15, same ? "ok" : "MISMATCH", (long)v);
    /* sample the status register, unwrap the 8-bit count */
    int64_t t0 = esp_timer_get_time(), tl = t0;
    int32_t s = 0, prev = -1;
    long total = 0, changes = 0;
    while (esp_timer_get_time() - t0 < 200000) {
        lgw_reg_r(SX1302_REG_AGC_MCU_MCU_AGC_STATUS_MCU_AGC_STATUS, &s);
        if (prev >= 0 && s != prev) { total += (s - prev) & 0xFF; changes++; tl = esp_timer_get_time(); }
        if (prev < 0) printf("first status 0x%02lX\n", (long)s);
        prev = s;
    }
    double dt = (tl - t0) / 1e6;
    printf("status changed %ld times, %ld counts in %.3f s -> %.0f counts/s -> %.2f M instruction cycles/s\n",
           changes, total, dt, dt > 0 ? total / dt : 0, dt > 0 ? total / dt * 771 / 1e6 : 0);
}

static void stats(int src)
{
    int fmt16 = (src >= 2 && src <= 6) || src == 9;
    int fmt8 = (src >= 10 && src <= 17);
    double si = 0, sq = 0, pi = 0, pq = 0;
    int n = CAP_SIZE / 4, distinct = 0, changes = 0;
    uint32_t prev = 0;
    for (int i = 0; i < CAP_SIZE; i += 4) {
        double I, Q;
        if (fmt8) { I = (int8_t)s_buf[i + 3]; Q = (int8_t)s_buf[i + 1]; }
        else { I = (int16_t)(s_buf[i + 2] | s_buf[i + 3] << 8); Q = (int16_t)(s_buf[i] | s_buf[i + 1] << 8); }
        si += I; sq += Q; pi += I * I; pq += Q * Q;
        uint32_t w = s_buf[i] | s_buf[i + 1] << 8 | s_buf[i + 2] << 16 | (uint32_t)s_buf[i + 3] << 24;
        if (i && w != prev) changes++;
        prev = w;
    }
    /* distinct 32-bit words among the first 256 */
    for (int a = 0; a < 256; a++) {
        uint32_t wa; memcpy(&wa, s_buf + a * 4, 4);
        int seen = 0;
        for (int b = 0; b < a && !seen; b++) { uint32_t wb; memcpy(&wb, s_buf + b * 4, 4); seen = (wa == wb); }
        distinct += !seen;
    }
    si /= n; sq /= n;
    double ri = sqrt(pi / n - si * si), rq = sqrt(pq / n - sq * sq);
    printf("src %2d fs %8lu %s meanI %8.1f meanQ %8.1f rmsI %8.1f rmsQ %8.1f chg %4d/%d dist256 %3d  w0..3 %02X%02X%02X%02X %02X%02X%02X%02X %02X%02X%02X%02X %02X%02X%02X%02X\n",
           src, (unsigned long)s_fs[src], fmt8 ? "i8 " : fmt16 ? "i16" : "raw", si, sq, ri, rq, changes, n - 1, distinct,
           s_buf[3], s_buf[2], s_buf[1], s_buf[0], s_buf[7], s_buf[6], s_buf[5], s_buf[4],
           s_buf[11], s_buf[10], s_buf[9], s_buf[8], s_buf[15], s_buf[14], s_buf[13], s_buf[12]);
}

static void b64_dump(int src)
{
    static const char t[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    printf("B64BEGIN %d %lu %u %lu %lu\n", src, (unsigned long)s_fs[src], CAP_SIZE, (unsigned long)s_rf0, (unsigned long)s_rf1);
    char line[80];
    int col = 0;
    for (int i = 0; i < CAP_SIZE; i += 3) {
        uint32_t v = s_buf[i] << 16 | (i + 1 < CAP_SIZE ? s_buf[i + 1] << 8 : 0) | (i + 2 < CAP_SIZE ? s_buf[i + 2] : 0);
        line[col++] = t[(v >> 18) & 63];
        line[col++] = t[(v >> 12) & 63];
        line[col++] = i + 1 < CAP_SIZE ? t[(v >> 6) & 63] : '=';
        line[col++] = i + 2 < CAP_SIZE ? t[v & 63] : '=';
        if (col >= 76) { line[col] = 0; puts(line); col = 0; }
    }
    if (col) { line[col] = 0; puts(line); }
    puts("B64END");
}

static void ring(int src, int polls, int us)
{
    if (capture(src, 1)) { puts("ring start failed"); return; }
    int64_t t0 = esp_timer_get_time();
    int32_t lo = 0, hi = 0, done = 0, plo = -1, phi = -1;
    for (int i = 0; i < polls; i++) {
        lgw_reg_r(SX1302_REG_CAPTURE_RAM_LAST_RAM_ADDR_0_LASTRAMADDR, &lo);
        lgw_reg_r(SX1302_REG_CAPTURE_RAM_LAST_RAM_ADDR_1_LASTRAMADDR, &hi);
        lgw_reg_r(SX1302_REG_CAPTURE_RAM_STATUS_CAPCOMPLETE, &done);
        if (lo != plo || hi != phi || i == 0 || i == polls - 1)
            printf("t %7lld us  addr0 0x%02lX addr1 0x%02lX  done %ld\n", esp_timer_get_time() - t0, (long)lo, (long)hi, (long)done);
        plo = lo; phi = hi;
        if (us) esp_rom_delay_us(us);
    }
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTUREWRAP, 0);
}

/* 12-bit capture-RAM write pointer (word index). Read hi/lo/hi to avoid tearing. */
#define REG_LASTRAMADDR 0x6006 /* lo byte, then hi nibble at 0x6007 */
#define RING_WORDS 4096

static int ring_wptr(void)
{
    uint8_t a[2], b[2];
    for (int tries = 0; tries < 4; tries++) {
        if (lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, REG_LASTRAMADDR, a, 2)) return -1;
        if (lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, REG_LASTRAMADDR, b, 2)) return -1;
        int wa = ((a[1] & 15) << 8) | a[0], wb = ((b[1] & 15) << 8) | b[0];
        int d = (wb - wa) & (RING_WORDS - 1);
        if (d < 512) return wb;   /* both reads agree to within normal motion */
    }
    return -2;
}

/* Freeze a 2k-pair IF ring when the loaded two-chain AGC detector latches
   an event. The PC can request the frozen RAM image after the burst ends. */
static bool s_event_ready;

static void watch_event(int mask, int post_us, int timeout_ms)
{
    s_event_ready = false;
    if (!s_started || mask < 1 || mask > 3 || post_us < 0 || post_us > 14000 ||
        timeout_ms < 1 || timeout_ms > 60000) {
        puts("WATCH invalid parameters or radio stopped");
        return;
    }
    int32_t status = 0;
    int trigger = -1, stop = -1, matched = 0;
    if (capture_at_rate(12, 1, 125000, 15)) { puts("WATCH arm error"); return; }
    vTaskDelay(pdMS_TO_TICKS(20)); /* one full 16.384 ms pre-trigger window */
    int error = lgw_reg_r(SX1302_REG_AGC_MCU_MCU_AGC_STATUS_MCU_AGC_STATUS, &status);
    bool stale = (status >> 4) & mask;
    if (!error && !stale) {
        puts("WATCH ARMED"); fflush(stdout);
        int64_t end = esp_timer_get_time() + 1000LL * timeout_ms;
        while (esp_timer_get_time() < end) {
            error = lgw_reg_r(SX1302_REG_AGC_MCU_MCU_AGC_STATUS_MCU_AGC_STATUS, &status);
            if (error) break;
            matched = (status >> 4) & mask;
            if (matched) {
                trigger = ring_wptr();
                esp_rom_delay_us(post_us);
                break;
            }
            vTaskDelay(1);
        }
    }
    error |= lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 0);
    stop = ring_wptr();
    error |= lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTUREWRAP, 0);
    error |= lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_RAMCONFIG, 0);
    if (error || stale || !matched || trigger < 0 || stop < 0) {
        printf("WATCH end error=%d stale=%d matched=%d trigger=%d stop=%d\n",error,stale,matched,trigger,stop);
        return;
    }
    error = lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
    if (!error) error = lgw_mem_rb(0, s_buf, CAP_SIZE, false);
    error |= lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
    s_event_ready = !error;
    printf("WATCH frozen=%d mask=%d trigger=%d stop=%d\n",s_event_ready,matched,trigger & 2047,stop & 2047);
}

/* Continuous read of the capture ring in wrap mode. Reads [rd, wptr) each
   pass; a lap is flagged when the time since the last read implies the
   writer could have overtaken us (> ring size minus a margin). */
static uint8_t s_chunk[RING_WORDS * 4];

/* Binary I/Q frames to the host over UART0 (see docs/stream-protocol.md).
   12-byte header: "SX", version, type, u16 seq, u16 len, u32 first sample
   index; then payload; then CRC-32 over bytes 2..11+len. */
#define FR_IQ8  0x10
#define FR_IQ16 0x11
#define FR_GAP  0x12
#define FR_STALE 0x13
#define FR_PAIR8 0x14
#define FR_END  0x1F
static uint8_t s_frame[12 + 4096 + 4];
static uint16_t s_seq;

static void put32(uint8_t *p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

static void send_frame(uint8_t type, uint32_t index, const uint8_t *pl, uint16_t len)
{
    s_frame[0] = 'S'; s_frame[1] = 'X'; s_frame[2] = 1; s_frame[3] = type;
    s_frame[4] = s_seq; s_frame[5] = s_seq >> 8; s_seq++;
    s_frame[6] = len; s_frame[7] = len >> 8;
    put32(s_frame + 8, index);
    if (pl != s_frame + 12 && len) memcpy(s_frame + 12, pl, len);
    uint32_t crc = esp_rom_crc32_le(0, s_frame + 2, 10 + len);
    put32(s_frame + 12 + len, crc);
    uart_write_bytes(UART_NUM_0, s_frame, 16 + len);
}

/* chunk: samples to let accumulate before touching the SPI bus again.
   Every SPI transaction during capture adds phase hash to the samples,
   so the reader sleeps instead of polling the write pointer. */
static int s_chunk_target = 1024;

/* The capture engine does not write while SPI reads the capture RAM: samples
   that arrive during a burst are lost and the pointer moves on. Keep each
   burst short so the engine's buffer covers it. */
static int s_burst = 1024, s_gap_us = 0;

/* Page register 0x5600 holds only the 2-bit page; write it directly. With
   s_page_per_burst set, page 1 is selected around each burst only. */
static int s_page_per_burst = 0;
#define REG_PAGE 0x5600

static void ring_read(int word, uint8_t *dst, int words)
{
    int bytes = words * 4, addr = word * 4;
    if (!s_page_per_burst) lgw_com_w(LGW_SPI_MUX_TARGET_SX1302, REG_PAGE, 1);
    while (bytes > 0) {
        int n = bytes < s_burst ? bytes : s_burst;
        if (s_page_per_burst) lgw_com_w(LGW_SPI_MUX_TARGET_SX1302, REG_PAGE, 1);
        lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, (uint16_t)addr, dst, (uint16_t)n);
        if (s_page_per_burst) lgw_com_w(LGW_SPI_MUX_TARGET_SX1302, REG_PAGE, 0);
        addr += n; dst += n; bytes -= n;
        if (bytes > 0 && s_gap_us) esp_rom_delay_us(s_gap_us);
    }
    if (!s_page_per_burst) lgw_com_w(LGW_SPI_MUX_TARGET_SX1302, REG_PAGE, 0);
}

/* A write the engine missed leaves the word from one lap earlier, so a word
   equal to the one read at the same position last lap is counted as stale. */
static uint32_t s_lap[RING_WORDS];
static uint32_t s_stale_mod[64], s_stale_off[64], s_runs[32];

static void print_hist(const char *name, const uint32_t *h, int n)
{
    printf("%s:", name);
    for (int i = 0; i < n; i++) if (h[i]) printf(" %d:%lu", i, (unsigned long)h[i]);
    printf("\n");
}

#include "p25_sync.h"

static void stream(int src, int ms, int baud, uint32_t fs, int pack_iq8, int second)
{
    if (!fs) { puts("no fs for that source"); return; }
    const int dual = second >= 0;
    const bool sync = p25_active();
    const int stride = dual ? 2 : 1; /* 32-bit RAM words per sample instant */
    const int capacity = RING_WORDS / stride;
    int fmt8 = pack_iq8 || (src >= 10 && src <= 17);
    if (baud) {
        printf("PCSTREAM %d %lu %d %s\n", src, (unsigned long)fs, baud, dual ? "pair8" : fmt8 ? "iq8" : "iq16");
        fflush(stdout);
        uart_wait_tx_done(UART_NUM_0, pdMS_TO_TICKS(200));
        vTaskDelay(pdMS_TO_TICKS(200));
        uart_set_baudrate(UART_NUM_0, baud);
        vTaskDelay(pdMS_TO_TICKS(50));
        s_seq = 0;
    }
    if (capture_at_rate(src, 1, fs, second)) { puts("ring start failed"); return; }
    int rd = ring_wptr();
    if (rd < 0) rd = 0;
    /* In 2k x 64 mode the counter advances once per pair. Bit 11
       continues counting through the physical 2048-pair wrap. */
    rd &= capacity - 1;
    uint32_t index = 0;
    memset(s_lap, 0xA5, sizeof s_lap);
    memset(s_stale_mod, 0, sizeof s_stale_mod);
    memset(s_stale_off, 0, sizeof s_stale_off);
    memset(s_runs, 0, sizeof s_runs);
    long long stale = 0, laps_seen = 0;
    int run = 0;
    (void)laps_seen;
    int64_t tuart = 0;
    int64_t t0 = esp_timer_get_time(), tlast = t0, tspi = 0, tread = t0;
    long long words = 0, reads = 0, laps = 0, bad = 0, bogus = 0;
    int maxav = 0;
    double p = 0;
    long long np = 0;
    /* Phase continuity: with a CW tone every step arg(x[n] conj x[n-1]) is the
       same; a lost/duplicated sample at a read boundary shows as a jump. */
    float pI = 0, pQ = 0, ref = 0;
    int have_prev = 0, have_ref = 0;
    long long jumps_in = 0, jumps_edge = 0, steps = 0;
    double step_sum = 0;
    while (esp_timer_get_time() - t0 < (int64_t)ms * 1000) {
        int64_t wait_us = (int64_t)((double)s_chunk_target * 1e6 / fs) - (esp_timer_get_time() - tread);
        if (wait_us > 1500) { vTaskDelay(pdMS_TO_TICKS(wait_us / 1000)); continue; }
        if (wait_us > 0) esp_rom_delay_us((uint32_t)wait_us);
        int w = ring_wptr();               /* page 0 */
        if (w < 0) { bad++; continue; }
        w &= capacity - 1;
        int64_t now = esp_timer_get_time();
        int av = (w - rd) & (capacity - 1);
        double expect = (double)(now - tread) * fs / 1e6;  /* words written since our last read */
        if ((double)(now - tlast) * fs / 1e6 > capacity - 256 / stride) {
            /* Overrun: resync to the writer and tell the host how much was lost. */
            laps++;
            if (sync) p25_gap((uint32_t)expect);
            uint32_t lost = (uint32_t)expect;
            if (baud) { uint8_t g[4]; put32(g, lost); send_frame(FR_GAP, index, g, 4); }
            index += lost;
            rd = w; tread = now; tlast = now; have_prev = 0;
            continue;
        }
        tlast = now;
        if (av < 32) continue;
        if (av > expect * 1.25 + 64) { bogus++; continue; }  /* pointer went backwards or jumped */
        if (av > maxav) maxav = av;
        int64_t ts = esp_timer_get_time();
        int first = av;
        if (rd + first > capacity) first = capacity - rd;
        ring_read(rd * stride, s_chunk, first * stride);
        if (first < av) ring_read(0, s_chunk + first * 4 * stride, (av - first) * stride);
        tread = now;
        tspi += esp_timer_get_time() - ts;
        int run_start = -1;
        for (int k = 0; k <= av; k++) {
            int is_stale = 0;
            if (k < av) {
                int pos = (rd + k) & (capacity - 1);
                const uint8_t *sample = s_chunk + k * 4 * stride;
                uint32_t *prior = s_lap + pos * stride;
                is_stale = words + k >= capacity && !memcmp(prior, sample, 4 * stride);
                memcpy(prior, sample, 4 * stride);
                if (sync) p25_push((int8_t)sample[3],(int8_t)sample[1],sample[4],is_stale);
                if (is_stale) {
                    stale++;
                    s_stale_mod[pos & 63]++;
                    s_stale_off[k < 63 ? k : 63]++;
                    if (run_start < 0) run_start = k;
                    run++;
                }
            }
            if (!is_stale && run) {
                s_runs[run < 31 ? run : 31]++;
                if (baud) {
                    /* erasure: these samples are left over from the previous lap */
                    uint8_t e[6];
                    put32(e, index + run_start); e[4] = run; e[5] = run >> 8;
                    send_frame(FR_STALE, index + run_start, e, 6);
                }
                run = 0;
                run_start = -1;
            }
        }
        if (sync) p25_chunk(av);
        (void)laps_seen;
        /* The wide reader needs this CPU time to drain the ring before wrap. */
        for (int i = 0; !pack_iq8 && !dual && i < av * 4; i += 4) {
            double I, Q;
            if (fmt8) { I = (int8_t)s_chunk[i + 3]; Q = (int8_t)s_chunk[i + 1]; }
            else { I = (int16_t)(s_chunk[i + 2] | s_chunk[i + 3] << 8); Q = (int16_t)(s_chunk[i] | s_chunk[i + 1] << 8); }
            p += I * I + Q * Q; np++;
            if (have_prev) {
                float re = (float)I * pI + (float)Q * pQ, im = (float)Q * pI - (float)I * pQ;
                float st = atan2f(im, re);
                if (!have_ref && steps > 256) { ref = (float)(step_sum / steps); have_ref = 1; }
                if (have_ref) {
                    float d = fabsf(st - ref);
                    if (d > (float)M_PI) d = 2.0f * (float)M_PI - d;
                    if (d > 0.6f) { if (i == 0) jumps_edge++; else jumps_in++; }
                }
                step_sum += st; steps++;
            }
            pI = (float)I; pQ = (float)Q; have_prev = 1;
        }
        if (baud) {
            int64_t tu = esp_timer_get_time();
            int per = fmt8 && !dual ? 2048 : 1024;        /* samples per frame, 4 KB max */
            for (int s0 = 0; s0 < av; s0 += per) {
                int n = av - s0 < per ? av - s0 : per;
                uint8_t *o = s_frame + 12;
                const uint8_t *in = s_chunk + s0 * 4 * stride;
                if (fmt8) {
                    for (int k = 0; k < n * stride; k++) { o[2 * k] = in[4 * k + 3]; o[2 * k + 1] = in[4 * k + 1]; }
                    send_frame(dual ? FR_PAIR8 : FR_IQ8, index + s0, s_frame + 12, (uint16_t)(n * 2 * stride));
                } else {
                    for (int k = 0; k < n; k++) {
                        o[4 * k] = in[4 * k + 2]; o[4 * k + 1] = in[4 * k + 3];
                        o[4 * k + 2] = in[4 * k]; o[4 * k + 3] = in[4 * k + 1];
                    }
                    send_frame(FR_IQ16, index + s0, s_frame + 12, (uint16_t)(n * 4));
                }
            }
            tuart += esp_timer_get_time() - tu;
        }
        index += av;
        rd = (rd + av) & (capacity - 1);
        words += av; reads++;
    }
    int64_t dt = esp_timer_get_time() - t0;
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTURESTART, 0);
    lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_CAPTUREWRAP, 0);
    if (dual) lgw_reg_w(SX1302_REG_CAPTURE_RAM_CAPTURE_CFG_RAMCONFIG, 0);
    if (baud) {
        uint8_t e[24];
        put32(e, (uint32_t)words); put32(e + 4, (uint32_t)(words >> 32));
        put32(e + 8, (uint32_t)laps); put32(e + 12, (uint32_t)bogus);
        put32(e + 16, (uint32_t)(dt / 1000)); put32(e + 20, fs);
        send_frame(FR_END, index, e, sizeof e);
        uart_wait_tx_done(UART_NUM_0, pdMS_TO_TICKS(3000));
        vTaskDelay(pdMS_TO_TICKS(300));
        uart_set_baudrate(UART_NUM_0, 115200);
        vTaskDelay(pdMS_TO_TICKS(100));
        printf("uart busy %.0f%%\n", tuart * 100.0 / dt);
    }
    printf("stream src %d fs %lu spi %d Hz: %lld words in %lld ms = %.1f kS/s (%.1f%% of fs), reads %lld, max avail %d, laps %lld, bogus %lld, bad ptr %lld, spi busy %.0f%%",
           src, (unsigned long)fs, espdev_get_speed(), words, dt / 1000, words * 1000.0 / dt, words * 1e8 / dt / fs, reads, maxav, laps, bogus, bad,
           tspi * 100.0 / dt);
    if (np) printf(", mean |iq|^2 %.1f", p / np);
    puts("");
    printf("stale: %lld words (%.3f%%) equal to last lap, burst %d B, chunk %d\n",
           stale, words > capacity ? stale * 100.0 / (words - capacity) : 0.0, s_burst, s_chunk_target);
    if (stale) {
        print_hist("stale by ring pos mod 64", s_stale_mod, 64);
        print_hist("stale by offset in read", s_stale_off, 64);
        print_hist("stale run lengths", s_runs, 32);
    }
    if (steps) {
        double mean = step_sum / steps;
        printf("phase: mean step %.4f rad = %+.1f Hz, jumps >0.6 rad: %lld at read edges (of %lld edges), %lld inside\n",
               mean, mean * fs / (2 * M_PI), jumps_edge, reads, jumps_in);
    }
}

static void spi_bench(void)
{
    int64_t t0 = esp_timer_get_time();
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 1);
    int e = lgw_mem_rb(0, s_buf, CAP_SIZE, false);
    lgw_reg_w(SX1302_REG_COMMON_PAGE_PAGE, 0);
    int64_t dt = esp_timer_get_time() - t0;
    printf("spi %d Hz: 16 KB read %lld us (%.2f Mb/s) err %d, crc %08lX, version 0x%02X\n", espdev_get_speed(), dt,
           CAP_SIZE * 8.0 / dt, e, (unsigned long)esp_rom_crc32_le(0, s_buf, CAP_SIZE), read_version());
}

static void handle(char *line)
{
    char *argv[6] = {0};
    int argc = 0;
    for (char *p = strtok(line, " \t\r\n"); p && argc < 6; p = strtok(NULL, " \t\r\n")) argv[argc++] = p;
    if (!argc) return;
    const char *c = argv[0];
    if (strcmp(c, "event") && strcmp(c, "ver") && strcmp(c, "help")) s_event_ready = false;
    if (!strcmp(c, "help")) {
        puts("probetune <rfA_hz> <rfB_hz> <calibration_hz>");
        puts("watch <mask> <post_us> <timeout_ms> | event (requires loaded AGC latch)");
        puts("p25self | p25scan <ms> [NAC] | p25mix <ms> <digital_amplitude> <seed>");
        puts("pcdual <srcA> <srcB> <ms> <baud> (125000 pairs/s)");
        puts("wide <125000|200000|250000> <ms> [baud] (radio A, iq8)");
        puts("ver | start | stop | tune <hz0> [hz1] | spi <hz> | cap <src> [b64] | sweep | ring <src> [polls] [us]\n"
             "stream <src> [ms] | pcstream <src> [ms] [baud] | chunk [n] | rd <addr> | wr <addr> <val> | rdb <addr> <n>");
    } else if (!strcmp(c, "p25self")) {
        if (!p25_begin(0, 0)) { puts("sync allocation failed"); return; }
        p25_self();
        p25_end(false, -1);
    } else if ((!strcmp(c, "p25scan") && (argc == 2 || argc == 3)) || (!strcmp(c, "p25mix") && argc == 4)) {
        int ms = atoi(argv[1]);
        int amplitude = argc == 4 ? atoi(argv[2]) : 0;
        unsigned seed = argc == 4 ? strtoul(argv[3], NULL, 0) : 0;
        if (ms < 4000 || ms > 600000 || amplitude < 0 || amplitude > 100) {
            puts("sync duration 4000..600000 ms, digital amplitude 0..100 counts"); return;
        }
        int nac = argc == 4 ? 0x293 : -1;
        if (argc == 3) {
            char *end;
            long value = strtol(argv[2], &end, 0);
            if (*end || value < 0 || value > 0xFFF) { puts("invalid 12-bit NAC"); return; }
            nac = (int)value;
        }
        if (!p25_begin(amplitude, seed)) { puts("sync allocation failed"); return; }
        stream(12, ms, 0, 125000, 1, 18);
        p25_end(true, nac);
    } else if (!strcmp(c, "watch") && argc == 4) {
        watch_event(atoi(argv[1]), atoi(argv[2]), atoi(argv[3]));
    } else if (!strcmp(c, "event")) {
        if (s_event_ready) b64_dump(12); else puts("no frozen event");
    } else if (!strcmp(c, "ver")) {
        int v = read_version();
        printf("SX1302 version 0x%02X (v%d.%d)\n", v & 0xFF, (v >> 4) & 15, v & 15);
    } else if (!strcmp(c, "start")) {
        do_start();
    } else if (!strcmp(c, "stop")) {
        printf("lgw_stop -> %d\n", lgw_stop());
        s_started = 0;
    } else if ((!strcmp(c, "tune") && argc >= 2) ||
               (!strcmp(c, "probetune") && argc == 4)) {
        uint32_t anchor = !strcmp(c, "probetune") ? strtoul(argv[3], NULL, 0) : 0;
        if (!strcmp(c, "probetune") && (anchor == 0 || !strcmp(argv[3], "0"))) {
            puts("probetune needs a calibration-table frequency"); return;
        }
        s_rf0 = strtoul(argv[1], NULL, 0);
        s_rf1 = argc >= 3 ? strtoul(argv[2], NULL, 0) : s_rf0 + 700000;
        if (s_started) { lgw_stop(); s_started = 0; }
        hw_reset();
        s_cal_anchor = anchor;
        if (anchor) printf("probe RX %lu %lu calibration %lu\n", (unsigned long)s_rf0, (unsigned long)s_rf1, (unsigned long)anchor);
        do_start();
        s_cal_anchor = 0;
    } else if (!strcmp(c, "spi") && argc >= 2) {
        int e = espdev_set_speed(atoi(argv[1]));
        if (e) printf("set speed failed %d\n", e);
        spi_bench();
    } else if (!strcmp(c, "cap") && argc >= 2) {
        int src = atoi(argv[1]) & 31;
        int64_t t0 = esp_timer_get_time();
        int e = capture(src, 0);
        printf("capture %d -> %d in %lld us\n", src, e, esp_timer_get_time() - t0);
        if (!e) { stats(src); if (argc >= 3) b64_dump(src); }
    } else if (!strcmp(c, "sweep")) {
        for (int s = 0; s < 32; s++) {
            if (!s_fs[s]) { printf("src %2d fs 0 (skipped)\n", s); continue; }
            if (capture(s, 0)) printf("src %2d capture timeout\n", s);
            else stats(s);
        }
    } else if (!strcmp(c, "ring") && argc >= 2) {
        ring(atoi(argv[1]) & 31, argc >= 3 ? atoi(argv[2]) : 200, argc >= 4 ? atoi(argv[3]) : 0);
    } else if (!strcmp(c, "capx") && argc >= 3) {
        int src = atoi(argv[1]) & 31;
        int e = capture_load(src, atoi(argv[2]));
        if (!e) { stats(src); if (argc >= 4) b64_dump(src); }
        else printf("capx failed %d\n", e);
    } else if (!strcmp(c, "burst")) {
        if (argc >= 2) { int n = atoi(argv[1]) & ~3; s_burst = n < 4 ? 4 : n > 1024 ? 1024 : n; }
        if (argc >= 3) s_gap_us = atoi(argv[2]);
        if (argc >= 4) s_page_per_burst = atoi(argv[3]) != 0;
        printf("burst %d bytes, gap %d us, page per burst %d\n", s_burst, s_gap_us, s_page_per_burst);
    } else if (!strcmp(c, "mcutest")) {
        mcu_test(argc >= 2 ? atoi(argv[1]) & 1 : 0);
        puts("AGC MCU now runs the test program; 'tune 904300000 905000000' restores the gateway firmware");
    } else if (!strcmp(c, "cap2") && argc >= 3) {
        int sa = atoi(argv[1]) & 31, sb = atoi(argv[2]) & 31;
        int e = capture2(sa, sb);
        if (!e && argc >= 4) b64_dump(sa);
        else if (e) printf("cap2 failed %d\n", e);
    } else if (!strcmp(c, "capxsize") && argc >= 2) {
        int n = atoi(argv[1]);
        s_load_bytes = n < 4 ? 4 : n > 1024 ? 1024 : n;
        printf("capx burst %d bytes\n", s_load_bytes);
    } else if (!strcmp(c, "chunk")) {
        if (argc >= 2) {
            int n = atoi(argv[1]);
            s_chunk_target = n < 32 ? 32 : n > RING_WORDS - 512 ? RING_WORDS - 512 : n;
        }
        printf("chunk %d samples\n", s_chunk_target);
    } else if (!strcmp(c, "stream") && argc >= 2) {
        int src = atoi(argv[1]) & 31;
        stream(src, argc >= 3 ? atoi(argv[2]) : 2000, 0, s_fs[src], 0, -1);
    } else if (!strcmp(c, "pcstream") && argc >= 2) {
        int src = atoi(argv[1]) & 31;
        stream(src, argc >= 3 ? atoi(argv[2]) : 10000, argc >= 4 ? atoi(argv[3]) : 3000000, s_fs[src], 0, -1);
    } else if (!strcmp(c, "wide") && argc >= 3) {
        int fs = atoi(argv[1]);
        if (fs != 125000 && fs != 200000 && fs != 250000) { puts("use 125000, 200000 or 250000"); return; }
        stream(9, atoi(argv[2]), argc >= 4 ? atoi(argv[3]) : 0, fs, 1, -1);
    } else if (!strcmp(c, "pcdual") && argc == 5) {
        int a = atoi(argv[1]), b = atoi(argv[2]);
        if (a < 10 || a > 17 || b < 10 || b > 17) { puts("use sources 10..17"); return; }
        stream(a, atoi(argv[3]), atoi(argv[4]), 125000, 0, b);
    } else if (!strcmp(c, "rd") && argc >= 2) {
        uint8_t v = 0;
        int e = lgw_com_r(LGW_SPI_MUX_TARGET_SX1302, (uint16_t)strtoul(argv[1], NULL, 0), &v);
        printf("rd 0x%04lX = 0x%02X (%d)\n", strtoul(argv[1], NULL, 0), v, e);
    } else if (!strcmp(c, "wr") && argc >= 3) {
        int e = lgw_com_w(LGW_SPI_MUX_TARGET_SX1302, (uint16_t)strtoul(argv[1], NULL, 0), (uint8_t)strtoul(argv[2], NULL, 0));
        printf("wr -> %d\n", e);
    } else if (!strcmp(c, "rdb") && argc >= 3) {
        uint16_t a = (uint16_t)strtoul(argv[1], NULL, 0);
        int n = atoi(argv[2]);
        if (n > 256) n = 256;
        uint8_t b[256];
        int e = lgw_com_rb(LGW_SPI_MUX_TARGET_SX1302, a, b, (uint16_t)n);
        printf("rdb 0x%04X x%d (%d):", a, n, e);
        for (int i = 0; i < n; i++) printf("%s%02X", i % 16 ? " " : "\n  ", b[i]);
        printf("\n");
    } else {
        puts("unknown, try help");
    }
}

void app_main(void)
{
    uart_driver_install(UART_NUM_0, 2048, 65536, 0, NULL, 0);
    uart_vfs_dev_use_driver(UART_NUM_0);
    setvbuf(stdin, NULL, _IONBF, 0);

    printf("\nsx1302-p4: WM1302 via Heltec debug board, HAL %s\n", LIBLORAGW_VERSION);
    hw_reset();
    int e = espdev_setup(SPI2_HOST, PIN_SCK, PIN_MOSI, PIN_MISO, PIN_CS, 2000000);
    printf("spi setup -> %d\n", e);
    e = lgw_connect(LGW_COM_SPI, "/dev/spidev0.0");
    printf("lgw_connect -> %d\n", e);
    int v = read_version();
    printf("SX1302 version 0x%02X\n", v & 0xFF);
    /* lgw_start opens the link itself */
    lgw_disconnect();
    do_start();
    espdev_set_speed(16000000);  /* reads verified bit-exact to 20 MHz on dupont wires */
    puts("ready: sweep | cap <src> [b64] | ring <src> | stream <src> [ms] | spi <hz> | tune <hz0> [hz1]");

    char line[128];
    int n = 0;
    for (;;) {
        int ch = fgetc(stdin);
        if (ch == EOF) { vTaskDelay(1); continue; }
        if (ch == '\r' || ch == '\n') {
            if (n) { line[n] = 0; printf("> %s\n", line); handle(line); n = 0; }
        } else if (n < (int)sizeof line - 1) {
            line[n++] = (char)ch;
        }
    }
}
