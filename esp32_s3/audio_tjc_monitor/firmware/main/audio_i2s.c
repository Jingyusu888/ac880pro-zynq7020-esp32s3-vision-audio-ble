#include "audio_i2s.h"
#include "audio_frontend.h"
#include "sdkconfig.h"
#include "driver/i2s_std.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>
#include <string.h>
static i2s_chan_handle_t rx;
static volatile uint32_t overflows;
static int32_t slots[512]; /* Internal RAM; 256 stereo frames per read. */
static bool IRAM_ATTR overflow_callback(i2s_chan_handle_t channel, i2s_event_data_t *event, void *context) {
    (void)channel; (void)event; (void)context; overflows++; return false;
}
esp_err_t pl_audio_init(void) {
    i2s_chan_config_t channel=I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0,I2S_ROLE_MASTER);
    channel.dma_desc_num=8; channel.dma_frame_num=256;
    esp_err_t err=i2s_new_channel(&channel,NULL,&rx); if(err!=ESP_OK) return err;
    i2s_std_config_t config={
        .clk_cfg=I2S_STD_CLK_DEFAULT_CONFIG(16000),
        .slot_cfg=I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,I2S_SLOT_MODE_STEREO),
        .gpio_cfg={.mclk=I2S_GPIO_UNUSED,.bclk=CONFIG_PETLINK_BCLK_GPIO,
            .ws=CONFIG_PETLINK_WS_GPIO,.dout=I2S_GPIO_UNUSED,.din=CONFIG_PETLINK_SD_GPIO,
            .invert_flags={.mclk_inv=false,.bclk_inv=false,.ws_inv=false}}
    };
    err=i2s_channel_init_std_mode(rx,&config); if(err!=ESP_OK) return err;
    i2s_event_callbacks_t callbacks={.on_recv_q_ovf=overflow_callback};
    return i2s_channel_register_event_callback(rx,&callbacks,NULL);
}
esp_err_t pl_audio_capture(int32_t *raw, float *pcm, pl_capture_t *report) {
    if(!raw || !pcm || !report || !rx) return ESP_ERR_INVALID_ARG;
    memset(report,0,sizeof(*report));
    esp_err_t err=i2s_channel_enable(rx); if(err!=ESP_OK) return err;
    /* Drain while clocks run so microphone and DMA settle. */
    for(int i=0;i<8;i++) {
        size_t bytes=0; err=i2s_channel_read(rx,slots,sizeof(slots),&bytes,1000);
        if(err!=ESP_OK || bytes!=sizeof(slots)) { i2s_channel_disable(rx); return ESP_ERR_TIMEOUT; }
    }
    uint32_t start_overflows=overflows; int64_t started=esp_timer_get_time();
    unsigned at=0;
    while(at<64000) {
        size_t wanted=(64000-at)<256 ? (64000-at)*8 : sizeof(slots), bytes=0;
        err=i2s_channel_read(rx,slots,wanted,&bytes,1000);
        if(err!=ESP_OK || bytes!=wanted || bytes%8) { err=ESP_ERR_TIMEOUT; break; }
        for(size_t i=0;i<bytes/8;i++) {
            int32_t n=pl_i2s_sample24((uint32_t)slots[2*i],
#ifdef CONFIG_PETLINK_I2S_HIGH_ALIGNED
                                    1
#else
                                    0
#endif
            );
            raw[at]=n; float value=(float)n/8388608.0f;
            if(!(at&1)) pcm[at/2]=value;
            report->nonzero+=(n!=0); report->clipped+=(n>=8380000 || n<=-8380000);
            report->peak=fmaxf(report->peak,fabsf(value)); at++;
        }
    }
    report->samples=at; report->capture_ms=(uint32_t)((esp_timer_get_time()-started)/1000);
    esp_err_t stop=i2s_channel_disable(rx);
    if(err!=ESP_OK) return err;
    if(stop!=ESP_OK) return stop;
    if(overflows!=start_overflows || at!=64000) return ESP_ERR_INVALID_SIZE;
    /* Complete silence is still an input in the always-output demo.
       Original MIC_DEBUG must first verify that the microphone receives sound. */
#ifndef CONFIG_PETLINK_DEMO_ALWAYS_OUTPUT
    if(!report->nonzero) return ESP_ERR_NOT_FOUND;
#endif
    return ESP_OK;
}
