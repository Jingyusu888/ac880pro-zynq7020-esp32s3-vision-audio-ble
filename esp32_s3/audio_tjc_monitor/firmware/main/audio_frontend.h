#ifndef PL_AUDIO_FRONTEND_H
#define PL_AUDIO_FRONTEND_H
#include <stddef.h>
#include <stdint.h>
#define PL_PCM_SAMPLES 32000   /* 4 s 窗 @ 8 kHz（猫版） */
#define PL_PCM_SAMPLES_2S 16000 /* 2 s 窗 @ 8 kHz（狗版） */
#define PL_FEATURES 238
typedef struct pl_frontend pl_frontend_t;
typedef void (*pl_yield_fn)(void *context);
size_t pl_frontend_workspace_size(void);
pl_frontend_t *pl_frontend_init(void *memory, size_t bytes);
/* Exact frozen v3_8k pipeline: mono float32, 8000 Hz.
 * count 决定窗长：32000 → 126 帧主 + 33 帧 F0（4s，猫）；
 *            16000 → 64 帧主 + 17 帧 F0（2s，狗）。其余返回 -1。 */
int pl_extract(pl_frontend_t *work, const float *pcm, size_t count,
               float features[PL_FEATURES], pl_yield_fn yield, void *context);
/* 24-bit signed microphone sample in a 32-bit I2S word. */
int32_t pl_i2s_sample24(uint32_t word, int high_aligned);
#endif
