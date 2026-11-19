#ifndef PL_AUDIO_I2S_H
#define PL_AUDIO_I2S_H
#include <stdint.h>
#include "esp_err.h"
typedef struct { uint32_t samples, capture_ms, nonzero, clipped; float peak; } pl_capture_t;
esp_err_t pl_audio_init(void);
/* Output int32 values hold normalized signed 24-bit samples, not raw slot words. */
esp_err_t pl_audio_capture(int32_t *raw_16k, float *pcm_8k, pl_capture_t *report);
#endif
