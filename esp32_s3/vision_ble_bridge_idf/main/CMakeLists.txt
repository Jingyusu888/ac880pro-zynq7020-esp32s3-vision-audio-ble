idf_component_register(
    SRCS "main.c"
         "../../audio_tjc_monitor/firmware/main/audio_i2s.c"
         "../../audio_tjc_monitor/firmware/main/audio_frontend.c"
         "../../audio_tjc_monitor/firmware/main/classifier.c"
         "../../audio_tjc_monitor/firmware/main/hierarchical_predict.c"
         "../../audio_tjc_monitor/firmware/main/dog_predict.c"
         "../../audio_tjc_monitor/firmware/main/demo_candidate.c"
         "../../audio_tjc_monitor/firmware/main/tjc_proto.c"
         "../../audio_tjc_monitor/firmware/main/tjc_display.c"
         "../../audio_tjc_monitor/firmware/main/ui_text.c"
    INCLUDE_DIRS "." "../../audio_tjc_monitor/firmware/main"
    REQUIRES driver esp_driver_uart esp_driver_i2s esp_psram esp_timer esp_wifi esp_netif esp_event lwip nvs_flash bt
)
