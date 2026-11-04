#pragma once
#include <stdbool.h>
#include <stdint.h>
bool p25_begin(unsigned amplitude, unsigned seed);
bool p25_active(void);
void p25_gap(unsigned lost);
void p25_push(int8_t i, int8_t q, uint8_t meter, bool stale);
void p25_chunk(unsigned samples);
void p25_self(void);
void p25_end(bool report, int nac);
