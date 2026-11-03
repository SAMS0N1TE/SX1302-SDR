/* Minimal stand-in for Linux <linux/spi/spidev.h> so the sx1302_hal SPI files
   compile unchanged on ESP-IDF. Transfers go to esp_spidev.c. */
#pragma once
#include <stdint.h>

struct spi_ioc_transfer {
    uint64_t tx_buf;
    uint64_t rx_buf;
    uint32_t len;
    uint32_t speed_hz;
    uint16_t delay_usecs;
    uint8_t  bits_per_word;
    uint8_t  cs_change;
    uint8_t  tx_nbits;
    uint8_t  rx_nbits;
    uint16_t pad;
};

#define SPI_MODE_0 0

#define ESPDEV_IOC_MSG_BASE   0x1000u
#define SPI_IOC_MESSAGE(n)    (ESPDEV_IOC_MSG_BASE + (unsigned)(n))
#define SPI_IOC_WR_MODE          0x2001u
#define SPI_IOC_RD_MODE          0x2002u
#define SPI_IOC_WR_BITS_PER_WORD 0x2003u
#define SPI_IOC_RD_BITS_PER_WORD 0x2004u
#define SPI_IOC_WR_MAX_SPEED_HZ  0x2005u
#define SPI_IOC_RD_MAX_SPEED_HZ  0x2006u
#define SPI_IOC_WR_LSB_FIRST     0x2007u
#define SPI_IOC_RD_LSB_FIRST     0x2008u
