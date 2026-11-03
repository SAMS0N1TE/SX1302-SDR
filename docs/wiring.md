# Wiring

## Mini PCIe pins

The WM1302 and the Heltec HT-HC01P HaLow card put SPI on the same edge pins, so the HT-HC01P debug board works as a socket for the WM1302. Pin numbers below are the standard mini PCIe numbers (odd on one side, even on the other). Heltec's own pin map image numbers the pins 1 to 52 around the card instead.

| Edge pin | HT-HC01P | WM1302 | Debug header |
| ---: | --- | --- | --- |
| 45 | SPI_CLK | SPI_CLK | CLK |
| 47 | SPI_MISO | SPI_MISO | MISO |
| 49 | SPI_MOSI | SPI_MOSI | MOSI |
| 51 | SPI_CS | SX1302_CSN | CS |
| 22 | RESET_N | SX1302_RESET, active high | RESET |
| 10 | SPI_INT | SX1262_RESET, active low | INT |
| 31 | BUSY | SX1262_IO2 | BUSY |
| 33 | WAKEUP_IN | SX1262_IO1 | WAKE |
| 2, 24, 39, 41, 52 | 3V3 | 3V3 | 3V3 |

Not on the debug header: SX1262_CSN (25), SX1262_BUSY (8), the temperature sensor I2C (30, 32), 1PPS (19).

## Nano pins

| Signal | GPIO | Header pin |
| --- | --- | --- |
| SPI_CLK | 2 | right 11 |
| SPI_MISO | 3 | right 9 |
| SPI_MOSI | 6 | right 12 |
| SX1302_CSN | 53 | right 14 |
| SX1302_RESET | 23 | left 7 |
| SX1262_RESET | 22 | left 16 |
| 3V3 | | right 5 |
| GND | | right 7 |

Header pins count from the top of each header, odd pins in the left column.

Avoid on the Nano: GPIO45 to 48 (their I/O supply is the programmable LDO that also feeds the microSD pull-ups), GPIO24 to 27 (USB), GPIO36 to 38 (straps and console), GPIO54 (C5 reset).

## Power

The module runs on 3.3 V only. It draws about 40 mA receiving and up to 415 mA transmitting at full power.

## Reset

The firmware drives SX1302_RESET high for 100 ms, then low, and holds SX1262_RESET low.
