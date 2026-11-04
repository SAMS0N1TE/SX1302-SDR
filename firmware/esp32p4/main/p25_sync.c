#include "p25_sync.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* Bench detector for channelized 125 kS/s complex samples, carrier at +20 kHz. */
enum { SF_TAPS = 49, SF_WINDOW = 120, SF_STEP = 4320, SF_HIST = 11 * SF_STEP + 1 };
typedef struct {
    int8_t scores[SF_HIST];
    float phase_filter[24][SF_TAPS], osc_i[25], osc_q[25];
    float mix_i[2 * SF_TAPS], mix_q[2 * SF_TAPS], delay_i[3], delay_q[3];
    float disc[2 * SF_WINDOW], weights[SF_WINDOW], norm;
    unsigned mixpos, oscpos, frac, delaypos, discpos, histpos, valid, n_input;
    uint32_t recent[4096], saved[2048], best_end, copied_end, bin_end;
    unsigned saved_count, contiguous, saved_first, amplitude, onset, prior_symbol, rng;
    uint32_t fixture_phase, fixture_step;
    float fixture_sine[256];
    float best, bin_best;
} sync_state;
/* One detector runs on radio A while the console owns the stream. */
static sync_state *sd;
bool p25_active(void) {
    return sd != NULL;
}
void p25_gap(unsigned lost) {
    sd->valid = 0;
    sd->contiguous = 0;
    sd->n_input += lost;
}

static void sync_init(void) {
    memset(sd, 0, sizeof(*sd));
    sd->best = sd->bin_best = -1;
    for (int k = 0; k < 25; k++) {
        sd->osc_i[k] = cosf(-2 * M_PI * 4 * k / 25);
        sd->osc_q[k] = sinf(-2 * M_PI * 4 * k / 25);
    }
    for (int p = 0; p < 24; p++) {
        float total = 0;
        for (int k = 0; k < SF_TAPS; k++) {
            float t = k - 24 + p / 24.0f;
            float v = fabsf(t) < 1.e-6f ? 0.112f : sinf(M_PI * 0.112f * t) / (M_PI * t);
            sd->phase_filter[p][k] = v * (0.54f - 0.46f * cosf(2 * M_PI * k / (SF_TAPS - 1)));
            total += sd->phase_filter[p][k];
        }
        for (int k = 0; k < SF_TAPS; k++)
            sd->phase_filter[p][k] /= total;
    }
    const uint64_t word = UINT64_C(0x5575F5FF77FF);
    float sum = 0;
    for (int k = 0; k < SF_WINDOW; k++) {
        sd->weights[k] = ((word >> (2 * (23 - k / 5))) & 3) == 1 ? 1 : -1;
        sum += sd->weights[k];
    }
    for (int k = 0; k < SF_WINDOW; k++) {
        sd->weights[k] -= sum / SF_WINDOW;
        sd->norm += sd->weights[k] * sd->weights[k];
    }
}
/* Systematic BCH(63,16) encoding for a known voice NID. Both voice DUIDs use parity 1. */
static uint64_t voice_nid(unsigned nac, unsigned duid) {
    unsigned info = (nac << 4) | duid;
    uint64_t rem = (uint64_t)info << 47;
    for (int k = 62; k >= 47; k--)
        if (rem & (UINT64_C(1) << k))
            rem ^= UINT64_C(0xcd930bdd3b2b) << (k - 47);
    return ((uint64_t)info << 48) | (rem << 1) | 1;
}
void p25_push(int8_t i, int8_t q, uint8_t meter, bool stale) {
    unsigned n = sd->n_input++;
    if (sd->amplitude && n >= sd->onset && n - sd->onset < 12 * 22500) {
        unsigned elapsed = n - sd->onset;
        unsigned symbol = (elapsed % 22500) * 4800 / 125000;
        unsigned sequence = elapsed / 22500 * 864 + symbol;
        if (sequence != sd->prior_symbol) {
            sd->prior_symbol = sequence;
            sd->rng = 1664525u * sd->rng + 1013904223u;
            unsigned dibit =
                symbol < 24 ? (UINT64_C(0x5575F5FF77FF) >> (2 * (23 - symbol))) & 3 : sd->rng >> 30;
            if (symbol >= 24 && symbol <= 56) {
                unsigned duid = (elapsed / 22500) % 2 ? 10 : 5;
                if (symbol == 35)
                    dibit = 1;
                else {
                    unsigned nidsym = symbol - 24 - (symbol > 35);
                    dibit = (voice_nid(0x293, duid) >> (62 - 2 * nidsym)) & 3;
                }
            }
            const int deviations[4] = {600, 1800, -600, -1800};
            sd->fixture_step = (uint32_t)((20000 + deviations[dibit]) * (4294967296.0 / 125000));
        }
        unsigned phase = sd->fixture_phase >> 24;
        sd->fixture_phase += sd->fixture_step;
        i = (int8_t)fminf(127, fmaxf(-128, i + lrintf(sd->amplitude * sd->fixture_sine[(phase + 64) & 255])));
        q = (int8_t)fminf(127, fmaxf(-128, q + lrintf(sd->amplitude * sd->fixture_sine[phase])));
    }
    if (sd->contiguous < 4096)
        sd->contiguous++;
    sd->recent[n & 4095] =
        (uint8_t)i | ((uint32_t)(uint8_t)q << 8) | ((uint32_t)meter << 16) | ((uint32_t)stale << 24);
    unsigned o = sd->oscpos, m = sd->mixpos;
    float a = stale ? 0 : i * sd->osc_i[o] - q * sd->osc_q[o];
    float b = stale ? 0 : i * sd->osc_q[o] + q * sd->osc_i[o];
    sd->oscpos = (o + 1) % 25;
    sd->mix_i[m] = sd->mix_i[m + SF_TAPS] = a;
    sd->mix_q[m] = sd->mix_q[m + SF_TAPS] = b;
    sd->mixpos = (m + 1) % SF_TAPS;
    sd->frac += 24;
    if (sd->frac < 125)
        return;
    sd->frac -= 125;
    float I = 0, Q = 0;
    const float *h = sd->phase_filter[sd->frac];
    for (int k = 0; k < SF_TAPS; k++) {
        I += h[k] * sd->mix_i[sd->mixpos + k];
        Q += h[k] * sd->mix_q[sd->mixpos + k];
    }
    /* Lag-three quadrature discriminator. Fold normalized sync scores only after a complete uninterrupted
     * history. */
    unsigned j = sd->delaypos;
    float v = Q * sd->delay_i[j] - I * sd->delay_q[j];
    sd->delay_i[j] = I;
    sd->delay_q[j] = Q;
    sd->delaypos = (j + 1) % 3;
    unsigned d = sd->discpos;
    sd->disc[d] = sd->disc[d + SF_WINDOW] = v;
    sd->discpos = (d + 1) % SF_WINDOW;
    float sum = 0, ss = 0, dot = 0;
    for (int k = 0; k < SF_WINDOW; k++) {
        float x = sd->disc[sd->discpos + k];
        sum += x;
        ss += x * x;
        dot += x * sd->weights[k];
    }
    float rho = dot / sqrtf(sd->norm * fmaxf(1.e-8f, ss - sum * sum / SF_WINDOW));
    int pos = sd->histpos;
    sd->scores[pos] = lrintf(127 * fminf(1, fmaxf(-1, rho)));
    sd->histpos = (pos + 1) % SF_HIST;
    if (sd->valid < SF_HIST + SF_WINDOW + 16) {
        sd->valid++;
        return;
    }
    int odd = 0, even = 0;
    for (int k = 0; k < 12; k++) {
        if (k & 1)
            odd += sd->scores[pos];
        else
            even += sd->scores[pos];
        pos -= SF_STEP;
        if (pos < 0)
            pos += SF_HIST;
    }
    float score = fmaxf(fminf(odd, even), fminf(-odd, -even)) / (6 * 127.0f);
    if (score > sd->best) {
        sd->best = score;
        sd->best_end = n;
    }
    if (score > sd->bin_best) {
        sd->bin_best = score;
        sd->bin_end = n;
    }
}
static void sync_save(bool final) {
    if (sd->best < 0 || (sd->saved_count && sd->copied_end == sd->best_end))
        return;
    unsigned available = sd->n_input - sd->best_end - 1;
    if (!final && available < 1024)
        return;
    if (available + 1024 > sd->contiguous)
        return;
    sd->saved_count = 1024 + (available < 1024 ? available : 1024);
    sd->saved_first = sd->best_end + 1 - 1024;
    for (unsigned i = 0; i < sd->saved_count; i++)
        sd->saved[i] = sd->recent[(sd->saved_first + i) & 4095];
    sd->copied_end = sd->best_end;
}
void p25_self(void) {
    /* 12 repetitions with 180 ms spacing. Synthesize the +20 kHz RF offset
       before the mixer/decimator, as in a live IF capture. No RF transmission. */
    const uint64_t word = UINT64_C(0x5575F5FF77FF);
    unsigned onset = 50000;
    float phase = 0;
    for (unsigned n = 0; n < 340000; n++) {
        int sym = n < onset ? 24 : (int)(((n - onset) % 22500) * 4800 / 125000);
        int dev = n >= onset && n < onset + 12 * 22500 && sym < 24
                      ? (((word >> (2 * (23 - sym))) & 3) == 1 ? 1800 : -1800)
                      : 0;
        phase += 2 * M_PI * (20000 + dev) / 125000;
        if (phase > 2 * M_PI)
            phase -= 2 * M_PI;
        p25_push(lrintf(80 * cosf(phase)), lrintf(80 * sinf(phase)), 0, false);
    }
    printf("sync fixture end=%lu expected near 298149 score=%.4f\n", (unsigned long)sd->best_end, sd->best);
}

bool p25_begin(unsigned amplitude, unsigned seed) {
    sd = malloc(sizeof(*sd));
    if (!sd)
        return false;
    sync_init();
    sd->amplitude = amplitude;
    sd->rng = seed;
    sd->prior_symbol = UINT32_MAX;
    sd->onset = 50000 + seed % 150000;
    if (amplitude) {
        for (int j = 0; j < 256; j++)
            sd->fixture_sine[j] = sinf(2 * M_PI * j / 256);
        printf("digital fixture onset=%lu expected_end=%lu amplitude=%u\n", (unsigned long)sd->onset,
               (unsigned long)(sd->onset + 248156), amplitude);
    }
    return true;
}
void p25_chunk(unsigned samples) {
    sync_save(false);
    if (sd->n_input / 625000 != (sd->n_input - samples) / 625000) {
        printf("sync block end=%lu peak_end=%lu score=%.4f\n", (unsigned long)sd->n_input,
               (unsigned long)sd->bin_end, sd->bin_best);
        sd->bin_best = -1;
    }
}
/* Validate the saved candidate independently of the cadence score. Search symbol
 * timing and polarity by sync only. Evaluate the following NID without refitting.
 * The bounded window is 2048 input samples, or at most 394 discriminator samples. */
static void verify_header(unsigned nac) {
    float fi[2 * SF_TAPS] = {0}, fq[2 * SF_TAPS] = {0}, smooth[400], phase[400];
    unsigned m = 0, frac = 0, count = 0;
    float old_i = 0, old_q = 0;
    for (unsigned n = 0; n < sd->saved_count; n++) {
        uint32_t w = sd->saved[n];
        int i = (int8_t)w, q = (int8_t)(w >> 8);
        if (w >> 24)
            i = q = 0;
        unsigned osc = n % 25;
        fi[m] = fi[m + SF_TAPS] = i * sd->osc_i[osc] - q * sd->osc_q[osc];
        fq[m] = fq[m + SF_TAPS] = i * sd->osc_q[osc] + q * sd->osc_i[osc];
        m = (m + 1) % SF_TAPS;
        frac += 24;
        if (frac < 125)
            continue;
        frac -= 125;
        float I = 0, Q = 0;
        for (unsigned k = 0; k < SF_TAPS; k++) {
            I += fi[m + k] * sd->phase_filter[frac][k];
            Q += fq[m + k] * sd->phase_filter[frac][k];
        }
        phase[count++] = atan2f(Q * old_i - I * old_q, I * old_i + Q * old_q);
        old_i = I;
        old_q = Q;
    }
    const unsigned symbols = 57;
    if (count < 5 * symbols + 12) {
        puts("sync header incomplete");
        return;
    }
    for (unsigned k = 0; k + 4 < count; k++)
        smooth[k] = (phase[k] + phase[k + 1] + phase[k + 2] + phase[k + 3] + phase[k + 4]) * .2f;
    float corr = 0, scale = 0, bias = 0;
    unsigned pos = 0;
    const unsigned long long syncword = UINT64_C(0x5575f5ff77ff);
    for (unsigned k = 10; k + symbols * 5 <= count; k++) {
        float sum = 0, sq = 0, dot = 0;
        for (int j = 0; j < 24; j++) {
            float v = smooth[k + 5 * j];
            sum += v;
            sq += v * v;
            dot += v * sd->weights[5 * j];
        }
        float denom = sd->norm / 5;
        float score = dot / sqrtf(fmaxf(1e-10f, denom * (sq - sum * sum / 24)));
        if (fabsf(score) > corr) {
            corr = fabsf(score);
            pos = k;
            scale = dot / denom;
            float first = ((syncword >> 46) & 3) == 1 ? 1 : -1;
            bias = sum / 24 - scale * (first - sd->weights[0]);
        }
    }
    if (fabsf(scale) < 1e-6f) {
        puts("sync header insufficient modulation");
        return;
    }
    uint64_t bits = 0;
    for (unsigned j = 24; j < symbols; j++) {
        if (j == 35)
            continue; /* First status dibit comes after 70 payload bits. */
        float v = 3 * (smooth[pos + j * 5] - bias) / scale;
        unsigned symbol = v < -2 ? 3 : v < 0 ? 2 : v < 2 ? 0 : 1;
        bits = (bits << 2) | symbol;
    }
    unsigned e1 = __builtin_popcountll(bits ^ voice_nid(nac, 5));
    unsigned e2 = __builtin_popcountll(bits ^ voice_nid(nac, 10));
    unsigned d = e1 <= e2 ? e1 : e2;
    printf("sync header nac=%03X duid=%X distance=%u/64 correlation=%.3f consistent=%u\n", nac,
           e1 <= e2 ? 5 : 10, d, corr, (unsigned)(corr >= .75f && d <= 6));
}
void p25_end(bool report, int nac) {
    if (report && sd->best >= 0) {
        sync_save(true);
        printf("sync winner end=%lu score=%.4f\n", (unsigned long)sd->best_end, sd->best);
        if (sd->saved_count && sd->copied_end == sd->best_end) {
            printf("sync window first=%lu samples=%u\n", (unsigned long)sd->saved_first, sd->saved_count);
            if (nac >= 0)
                verify_header((unsigned)nac);
            printf("SYNC_EVENT ");
            for (unsigned i = 0; i < sd->saved_count; i++)
                printf("%08lx", (unsigned long)sd->saved[i]);
            puts("");
        }
    }
    free(sd);
    sd = NULL;
}
