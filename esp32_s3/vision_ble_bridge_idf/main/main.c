/*
 * PetLink Route A Vision Bridge (ESP-IDF v5.5.3 + NimBLE + Serial/UDP)
 *
 * Bridges AC880 vision posture JSON packets:
 *   - Input A: USB Serial (UART0 @ 115200) newline-delimited JSON lines
 *   - Input B: Wi-Fi UDP port 9000 JSON datagrams (when Wi-Fi SSID is configured via Kconfig or NVS)
 *   - Output : BLE Nordic UART Service (6E400001-B5A3-F393-E0A9-E50E24DCCA9E)
 *              Device Name = "Petlink-ESP32S3", TX Notify = 6E400003-..., MTU = 256
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "audio_frontend.h"
#include "audio_i2s.h"
#include "demo_candidate.h"
#include "dog_predict.h"
#include "driver/uart.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_psram.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hierarchical_predict.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "tjc_display.h"
#include "ui_config.h"

#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

static const char *TAG = "PL_BRIDGE";
static const char *BLE_DEV_NAME = "Petlink-ESP32S3";
static const char *NVS_NS = "pl_wifi";

/* Nordic UART Service UUIDs (little-endian):
 * Service: 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
 * RX:      6E400002-B5A3-F393-E0A9-E50E24DCCA9E
 * TX:      6E400003-B5A3-F393-E0A9-E50E24DCCA9E
 */
static const ble_uuid128_t nus_svc_uuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x01, 0x00, 0x40, 0x6e);
static const ble_uuid128_t nus_rx_uuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x02, 0x00, 0x40, 0x6e);
static const ble_uuid128_t nus_tx_uuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x03, 0x00, 0x40, 0x6e);

static uint16_t tx_val_handle = 0;
static volatile uint16_t g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static volatile bool g_tx_subscribed = false;
static uint8_t g_own_addr_type = 0;

static volatile bool g_wifi_connected = false;
static char g_wifi_ip[24] = "0.0.0.0";
static volatile uint32_t g_rx_frames = 0;
static volatile uint32_t g_ble_tx_frames = 0;

static portMUX_TYPE g_frame_lock = portMUX_INITIALIZER_UNLOCKED;
static char g_last_frame[512] = "{\"seq\":0,\"valid\":0,\"cls\":\"NONE\",\"pose\":\"UNK\"}";
static size_t g_last_frame_len = 44;

typedef enum {
    VIS_CLS_NONE = 0,
    VIS_CLS_CAT = 1,
    VIS_CLS_DOG = 2,
} vis_cls_t;

typedef enum {
    VIS_POSE_UNK = 0,
    VIS_POSE_STD = 1,
    VIS_POSE_SIT = 2,
    VIS_POSE_LIE = 3,
} vis_pose_t;

typedef struct {
    uint32_t rx_seq;
    bool valid;
    vis_cls_t cls;
    vis_pose_t pose;
    int conf; /* 0..100 */
} vis_state_t;

typedef struct {
    uint32_t round;
    bool have_result;
    bool capturing;
    int species_mode; /* 0=cat 1=dog */
    pl_text_code_t text_code;
    int face_pic;
    int conf; /* 0..100 */
    bool trigger;
    char label[40];
} audio_state_t;

static vis_state_t g_vis_latest = {0};
static TickType_t g_vis_last_tick = 0;
static audio_state_t g_audio_latest = {
    .species_mode = 0,
    .text_code = PL_TEXT_IDLE,
    .face_pic = PL_TJC_PIC_IDLE,
};

static volatile bool g_tjc_ready = false;
static volatile bool g_audio_ready = false;
static volatile bool g_auto_mode = true;      /* default ON: standalone audio recognition */
static volatile bool g_tjc_paused = false;
static volatile bool g_manual_capture_req = false;
static volatile int g_species_mode = 0;       /* 0=cat, 1=dog */

static void parse_vision_json(const char *json, vis_state_t *out)
{
    memset(out, 0, sizeof(*out));
    const char *p = strstr(json, "\"valid\":");
    if (p) out->valid = (atoi(p + 8) != 0);
    p = strstr(json, "\"score\":");
    if (p) {
        float sc = strtof(p + 8, NULL);
        int c = (int)(sc * 100.0f + 0.5f);
        if (c < 0) c = 0;
        if (c > 100) c = 100;
        out->conf = c;
    }
    p = strstr(json, "\"cls\":\"");
    if (p) {
        p += 7;
        if (strncmp(p, "CAT", 3) == 0) out->cls = VIS_CLS_CAT;
        else if (strncmp(p, "DOG", 3) == 0) out->cls = VIS_CLS_DOG;
    }
    p = strstr(json, "\"pose\":\"");
    if (p) {
        p += 8;
        if (strncmp(p, "STD", 3) == 0) out->pose = VIS_POSE_STD;
        else if (strncmp(p, "SIT", 3) == 0) out->pose = VIS_POSE_SIT;
        else if (strncmp(p, "LIE", 3) == 0) out->pose = VIS_POSE_LIE;
    }
}

static int gap_event(struct ble_gap_event *event, void *arg);

static int nus_rx_cb(uint16_t conn_handle, uint16_t attr_handle,
                     struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)conn_handle;
    (void)attr_handle;
    (void)arg;
    if (ctxt->op != BLE_GATT_ACCESS_OP_WRITE_CHR) {
        return BLE_ATT_ERR_READ_NOT_PERMITTED;
    }
    uint16_t len = OS_MBUF_PKTLEN(ctxt->om);
    if (len > 0 && len < 256) {
        char buf[256];
        uint16_t copied = 0;
        ble_hs_mbuf_to_flat(ctxt->om, buf, len, &copied);
        buf[copied] = '\0';
        ESP_LOGI(TAG, "[BLE RX] %s", buf);
    }
    return 0;
}

static int nus_tx_cb(uint16_t conn_handle, uint16_t attr_handle,
                     struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    (void)conn_handle;
    (void)attr_handle;
    (void)arg;
    if (ctxt->op != BLE_GATT_ACCESS_OP_READ_CHR) {
        return BLE_ATT_ERR_WRITE_NOT_PERMITTED;
    }
    char snap[512];
    size_t len = 0;
    portENTER_CRITICAL(&g_frame_lock);
    len = g_last_frame_len;
    if (len > sizeof(snap)) len = sizeof(snap);
    memcpy(snap, g_last_frame, len);
    portEXIT_CRITICAL(&g_frame_lock);
    return os_mbuf_append(ctxt->om, snap, len) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
}

static const struct ble_gatt_svc_def gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &nus_svc_uuid.u,
        .characteristics = (struct ble_gatt_chr_def[]){
            {
                .uuid = &nus_rx_uuid.u,
                .access_cb = nus_rx_cb,
                .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
            },
            {
                .uuid = &nus_tx_uuid.u,
                .access_cb = nus_tx_cb,
                .flags = BLE_GATT_CHR_F_NOTIFY | BLE_GATT_CHR_F_READ,
                .val_handle = &tx_val_handle,
            },
            {0},
        },
    },
    {0},
};

static void start_advertising(void)
{
    struct ble_gap_adv_params adv_params;
    struct ble_hs_adv_fields fields;
    int rc;

    memset(&fields, 0, sizeof(fields));
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128 = (ble_uuid128_t *)&nus_svc_uuid;
    fields.num_uuids128 = 1;
    fields.uuids128_is_complete = 1;
    rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_set_fields rc=%d", rc);
        return;
    }

    memset(&fields, 0, sizeof(fields));
    const char *name = ble_svc_gap_device_name();
    fields.name = (const uint8_t *)name;
    fields.name_len = strlen(name);
    fields.name_is_complete = 1;
    rc = ble_gap_adv_rsp_set_fields(&fields);
    if (rc != 0) {
        ESP_LOGE(TAG, "adv_rsp_set_fields rc=%d", rc);
        return;
    }

    memset(&adv_params, 0, sizeof(adv_params));
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    rc = ble_gap_adv_start(g_own_addr_type, NULL, BLE_HS_FOREVER, &adv_params, gap_event, NULL);
    if (rc == 0) {
        printf("BLE_ADV_START name=%s svc=6E400001-B5A3-F393-E0A9-E50E24DCCA9E\n", BLE_DEV_NAME);
        fflush(stdout);
    } else {
        ESP_LOGE(TAG, "adv_start rc=%d", rc);
    }
}

static int gap_event(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        if (event->connect.status == 0) {
            g_conn_handle = event->connect.conn_handle;
            g_tx_subscribed = false;
            printf("BLE_CONNECTED handle=%u\n", (unsigned)g_conn_handle);
        } else {
            g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            start_advertising();
        }
        fflush(stdout);
        return 0;

    case BLE_GAP_EVENT_DISCONNECT:
        g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
        g_tx_subscribed = false;
        printf("BLE_DISCONNECTED reason=%d\n", event->disconnect.reason);
        fflush(stdout);
        start_advertising();
        return 0;

    case BLE_GAP_EVENT_SUBSCRIBE:
        if (event->subscribe.attr_handle == tx_val_handle) {
            g_tx_subscribed = (event->subscribe.cur_notify != 0);
            printf("BLE_SUBSCRIBED=%d\n", g_tx_subscribed ? 1 : 0);
            fflush(stdout);
        }
        return 0;

    case BLE_GAP_EVENT_MTU:
        printf("BLE_MTU=%u\n", (unsigned)event->mtu.value);
        fflush(stdout);
        return 0;

    default:
        return 0;
    }
}

static void ble_on_sync(void)
{
    ble_hs_util_ensure_addr(0);
    ble_hs_id_infer_auto(0, &g_own_addr_type);
    start_advertising();
}

static void ble_on_reset(int reason)
{
    ESP_LOGW(TAG, "NimBLE reset reason=%d", reason);
    g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
    g_tx_subscribed = false;
}

static void nimble_host_task(void *param)
{
    (void)param;
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static void send_ble_notify(const char *src, const char *data, size_t len)
{
    if (len == 0 || len >= sizeof(g_last_frame)) return;
    portENTER_CRITICAL(&g_frame_lock);
    memcpy(g_last_frame, data, len);
    g_last_frame[len] = '\0';
    g_last_frame_len = len;
    portEXIT_CRITICAL(&g_frame_lock);

    if (g_conn_handle != BLE_HS_CONN_HANDLE_NONE && g_tx_subscribed) {
        struct os_mbuf *om = ble_hs_mbuf_from_flat(data, (uint16_t)len);
        if (om != NULL) {
            int rc = ble_gatts_notify_custom(g_conn_handle, tx_val_handle, om);
            if (rc == 0) {
                g_ble_tx_frames++;
            } else {
                ESP_LOGW(TAG, "notify rc=%d", rc);
            }
        }
    }
    printf("[%s] %.*s\n", src, (int)len, data);
    fflush(stdout);
}

static void forward_json_to_ble(const char *src, const char *data, size_t len)
{
    if (len == 0 || len >= sizeof(g_last_frame)) return;
    vis_state_t parsed;
    parse_vision_json(data, &parsed);
    g_rx_frames++;
    audio_state_t audio_snap;
    portENTER_CRITICAL(&g_frame_lock);
    parsed.rx_seq = g_rx_frames;
    g_vis_latest = parsed;
    g_vis_last_tick = xTaskGetTickCount();
    audio_snap = g_audio_latest;
    portEXIT_CRITICAL(&g_frame_lock);

    if (parsed.valid) {
        if (parsed.cls == VIS_CLS_CAT) g_species_mode = 0;
        else if (parsed.cls == VIS_CLS_DOG) g_species_mode = 1;
    }

    if (audio_snap.have_result && len > 2 && data[len - 1] == '}') {
        char merged[512];
        size_t prefix_len = len - 1;
        if (prefix_len + 96 < sizeof(merged)) {
            memcpy(merged, data, prefix_len);
            int tail = snprintf(
                merged + prefix_len, sizeof(merged) - prefix_len,
                ",\"src\":\"hybrid\",\"audio_label\":\"%s\",\"audio_conf\":%.2f,\"audio_trig\":%d}",
                audio_snap.label, (double)audio_snap.conf / 100.0, audio_snap.trigger ? 1 : 0);
            if (tail > 0 && prefix_len + (size_t)tail < sizeof(merged)) {
                send_ble_notify(src, merged, prefix_len + (size_t)tail);
                return;
            }
        }
    }
    send_ble_notify(src, data, len);
}

/* ---- Optional Wi-Fi STA + UDP:9000 ---- */
static bool g_wifi_started = false;

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        g_wifi_connected = false;
        snprintf(g_wifi_ip, sizeof(g_wifi_ip), "0.0.0.0");
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        snprintf(g_wifi_ip, sizeof(g_wifi_ip), IPSTR, IP2STR(&ev->ip_info.ip));
        g_wifi_connected = true;
        printf("WIFI_READY IP=%s UDP=%d\n", g_wifi_ip, CONFIG_PETLINK_UDP_PORT);
        fflush(stdout);
    }
}

static bool load_wifi_creds(char *ssid, size_t ssid_sz, char *pass, size_t pass_sz)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        size_t s_len = ssid_sz, p_len = pass_sz;
        esp_err_t e1 = nvs_get_str(h, "ssid", ssid, &s_len);
        esp_err_t e2 = nvs_get_str(h, "pass", pass, &p_len);
        nvs_close(h);
        if (e1 == ESP_OK && strlen(ssid) > 0) {
            if (e2 != ESP_OK) pass[0] = '\0';
            return true;
        }
    }
    if (strlen(CONFIG_PETLINK_WIFI_SSID) > 0) {
        snprintf(ssid, ssid_sz, "%s", CONFIG_PETLINK_WIFI_SSID);
        snprintf(pass, pass_sz, "%s", CONFIG_PETLINK_WIFI_PASS);
        return true;
    }
    return false;
}

static void save_wifi_creds(const char *ssid, const char *pass)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_str(h, "ssid", ssid);
        nvs_set_str(h, "pass", pass);
        nvs_commit(h);
        nvs_close(h);
    }
}

static void udp_server_task(void *param)
{
    (void)param;
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "UDP socket failed");
        vTaskDelete(NULL);
        return;
    }
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(CONFIG_PETLINK_UDP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "UDP bind failed");
        close(sock);
        vTaskDelete(NULL);
        return;
    }
    printf("UDP_LISTENING port=%d\n", CONFIG_PETLINK_UDP_PORT);
    fflush(stdout);

    char buf[512];
    for (;;) {
        struct sockaddr_in src_addr;
        socklen_t socklen = sizeof(src_addr);
        int len = recvfrom(sock, buf, sizeof(buf) - 1, 0, (struct sockaddr *)&src_addr, &socklen);
        if (len > 0) {
            while (len > 0 && (buf[len - 1] == '\n' || buf[len - 1] == '\r' || buf[len - 1] == ' ')) {
                len--;
            }
            buf[len] = '\0';
            if (len > 0 && buf[0] == '{') {
                forward_json_to_ble("UDP->BLE", buf, (size_t)len);
            }
        }
    }
}

static void start_wifi_if_configured(void)
{
    char ssid[32] = {0}, pass[64] = {0};
    if (!load_wifi_creds(ssid, sizeof(ssid), pass, sizeof(pass))) {
        printf("WIFI_SKIPPED (no SSID configured; USB-Serial->BLE active)\n");
        fflush(stdout);
        return;
    }
    if (!g_wifi_started) {
        ESP_ERROR_CHECK(esp_netif_init());
        ESP_ERROR_CHECK(esp_event_loop_create_default());
        esp_netif_create_default_wifi_sta();
        wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
        ESP_ERROR_CHECK(esp_wifi_init(&cfg));
        ESP_ERROR_CHECK(esp_event_handler_instance_register(
            WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
        ESP_ERROR_CHECK(esp_event_handler_instance_register(
            IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));
        g_wifi_started = true;
        xTaskCreate(udp_server_task, "udp_srv", 4096, NULL, 4, NULL);
    }

    wifi_config_t wcfg = {0};
    memcpy(wcfg.sta.ssid, ssid, sizeof(wcfg.sta.ssid));
    memcpy(wcfg.sta.password, pass, sizeof(wcfg.sta.password));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wcfg));
    ESP_ERROR_CHECK(esp_wifi_start());
    printf("WIFI_CONNECTING ssid=%s\n", ssid);
    fflush(stdout);
}

/* ---- USB Serial (UART0) Input Task ---- */
static void serial_rx_task(void *param)
{
    (void)param;
    uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0);
    char line[512];
    size_t pos = 0;
    uint8_t ch = 0;
    for (;;) {
        int n = uart_read_bytes(UART_NUM_0, &ch, 1, pdMS_TO_TICKS(100));
        if (n <= 0) continue;
        if (ch == '\r' || ch == '\n') {
            if (pos == 0) continue;
            line[pos] = '\0';
            if (line[0] == '{') {
                forward_json_to_ble("SER->BLE", line, pos);
            } else if (strcmp(line, "PING") == 0 || strcmp(line, "STATUS") == 0) {
                printf("PONG ble_conn=%d ble_sub=%d wifi=%d ip=%s tjc=%d audio=%d rx=%lu ble_tx=%lu\n",
                       (g_conn_handle != BLE_HS_CONN_HANDLE_NONE) ? 1 : 0,
                       g_tx_subscribed ? 1 : 0,
                       g_wifi_connected ? 1 : 0,
                       g_wifi_ip,
                       g_tjc_ready ? 1 : 0,
                       g_audio_ready ? 1 : 0,
                       (unsigned long)g_rx_frames,
                       (unsigned long)g_ble_tx_frames);
                fflush(stdout);
            } else if (strncmp(line, "WIFI:", 5) == 0) {
                char *comma = strchr(line + 5, ',');
                if (comma != NULL) {
                    *comma = '\0';
                    save_wifi_creds(line + 5, comma + 1);
                    printf("WIFI_SAVED ssid=%s (restarting)\n", line + 5);
                    fflush(stdout);
                    vTaskDelay(pdMS_TO_TICKS(200));
                    esp_restart();
                }
            } else if (strcmp(line, "WIFI_CLEAR") == 0) {
                save_wifi_creds("", "");
                printf("WIFI_CLEARED (restarting)\n");
                fflush(stdout);
                vTaskDelay(pdMS_TO_TICKS(200));
                esp_restart();
            }
            pos = 0;
        } else if (pos + 1 < sizeof(line)) {
            line[pos++] = (char)ch;
        } else {
            pos = 0; /* overflow reset */
        }
    }
}

/* ---- Local INMP441 Audio Recognizer Task ---- */
static void audio_yield(void *context)
{
    (void)context;
    vTaskDelay(1);
}

static void audio_task(void *param)
{
    (void)param;
    static float s_features[PL_FEATURES];
    if (esp_psram_get_size() < 2 * 1024 * 1024) {
        ESP_LOGW(TAG, "PSRAM < 2MB; audio disabled");
        vTaskDelete(NULL);
        return;
    }
    float *pcm = heap_caps_malloc(PL_PCM_SAMPLES * sizeof(float), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    int32_t *raw = heap_caps_malloc(64000 * sizeof(int32_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    void *work_mem = heap_caps_malloc(pl_frontend_workspace_size(), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    pl_frontend_t *work = (work_mem != NULL) ? pl_frontend_init(work_mem, pl_frontend_workspace_size()) : NULL;
    if (!pcm || !raw || !work) {
        ESP_LOGW(TAG, "Audio PSRAM alloc failed; audio disabled");
        vTaskDelete(NULL);
        return;
    }
    esp_err_t err = pl_audio_init();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "Mic I2S init failed (%s); continuing vision-only", esp_err_to_name(err));
        vTaskDelete(NULL);
        return;
    }

    g_audio_ready = true;
    printf("AUDIO_INIT_OK bclk=%d ws=%d sd=%d psram=%u\n",
           CONFIG_PETLINK_BCLK_GPIO, CONFIG_PETLINK_WS_GPIO, CONFIG_PETLINK_SD_GPIO,
           (unsigned)esp_psram_get_size());
    fflush(stdout);

    uint32_t round = 0;
    for (;;) {
        bool do_cap = g_auto_mode || g_manual_capture_req;
        if (!do_cap) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }
        g_manual_capture_req = false;
        pl_tjc_set_busy(true);
        portENTER_CRITICAL(&g_frame_lock);
        g_audio_latest.capturing = true;
        portEXIT_CRITICAL(&g_frame_lock);

        pl_capture_t report;
        err = pl_audio_capture(raw, pcm, &report);
        if (err != ESP_OK) {
            printf("AUDIO_CAPTURE_ERR %s samples=%lu\n",
                   esp_err_to_name(err), (unsigned long)report.samples);
            fflush(stdout);
            portENTER_CRITICAL(&g_frame_lock);
            g_audio_latest.capturing = false;
            portEXIT_CRITICAL(&g_frame_lock);
            pl_tjc_set_busy(false);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        int sp = g_species_mode;
        pl_set_species_mode(sp);
        int64_t t0 = esp_timer_get_time();

        const char *lbl = "unknown";
        const char *cand_lbl = "unknown";
        bool trig = false;
        float conf_f = 0.0f;

        if (sp == 1) {
            pl_extract(work, pcm, PL_PCM_SAMPLES_2S, s_features, audio_yield, NULL);
            float dog_prob = 0.0f;
            int is_dog = dog_gate_classify(s_features, &dog_prob);
            if (is_dog) {
                double dprobs[3] = {0};
                int st = dog_state_classify(s_features, dprobs);
                static const char *const st_labels[3] = {"active", "alert", "rest"};
                lbl = st_labels[(st >= 0 && st < 3) ? st : 0];
                cand_lbl = lbl;
                trig = true;
                conf_f = (float)dprobs[(st >= 0 && st < 3) ? st : 0];
            } else {
                lbl = "unknown";
                cand_lbl = "not_dog";
                trig = false;
                conf_f = dog_prob;
            }
        } else {
            pl_prediction_t pred;
            pl_demo_candidate_t cand;
            pl_extract(work, pcm, PL_PCM_SAMPLES, s_features, audio_yield, NULL);
            pl_predict(s_features, &pred);
            pl_demo_candidate(pred.probabilities, &cand);
            lbl = pred.label ? pred.label : "unknown";
            cand_lbl = cand.label ? cand.label : lbl;
            trig = pred.trigger;
            conf_f = pred.confidence;
        }

        uint32_t proc_ms = (uint32_t)((esp_timer_get_time() - t0) / 1000);
        uint32_t total_ms = report.capture_ms + proc_ms;
        int conf_pct = (int)(conf_f * 100.0f + 0.5f);
        if (conf_pct < 0) conf_pct = 0;
        if (conf_pct > 100) conf_pct = 100;

        pl_text_code_t tcode = pl_text_for_result(lbl, trig ? 1 : 0);
        int fpic = pl_face_pic_of(tcode);
        round++;

        vis_state_t vis_snap;
        TickType_t vis_tick;
        portENTER_CRITICAL(&g_frame_lock);
        g_audio_latest.round = round;
        g_audio_latest.have_result = true;
        g_audio_latest.capturing = false;
        g_audio_latest.species_mode = sp;
        g_audio_latest.text_code = tcode;
        g_audio_latest.face_pic = (fpic >= 0) ? fpic : PL_TJC_PIC_UNKNOWN;
        g_audio_latest.conf = conf_pct;
        g_audio_latest.trigger = trig;
        snprintf(g_audio_latest.label, sizeof(g_audio_latest.label), "%s", lbl);
        vis_snap = g_vis_latest;
        vis_tick = g_vis_last_tick;
        portEXIT_CRITICAL(&g_frame_lock);

        pl_tjc_set_busy(false);

        printf("AUDIO_RESULT round=%lu sp=%s label=%s cand=%s conf=%.2f trig=%d nonzero=%lu peak=%.4f\n",
               (unsigned long)round, sp ? "dog" : "cat", lbl, cand_lbl,
               (double)conf_f, trig ? 1 : 0, (unsigned long)report.nonzero, (double)report.peak);
        fflush(stdout);

        TickType_t now = xTaskGetTickCount();
        bool vis_online = (vis_snap.rx_seq > 0) && ((now - vis_tick) <= pdMS_TO_TICKS(4500));
        if (!vis_online) {
            char jbuf[256];
            int n = snprintf(
                jbuf, sizeof(jbuf),
                "{\"seq\":%lu,\"valid\":%d,\"cls\":\"%s\",\"score\":%.2f,\"pose\":\"UNK\","
                "\"raw\":\"AUDIO:%s\",\"kpt_cnt\":0,\"box\":[0,0,0,0],\"ms\":%lu,"
                "\"src\":\"audio\",\"audio_label\":\"%s\",\"audio_trig\":%d}",
                (unsigned long)round, trig ? 1 : 0, trig ? (sp ? "DOG" : "CAT") : "NONE",
                (double)conf_f, lbl, (unsigned long)total_ms, lbl, trig ? 1 : 0);
            if (n > 0 && (size_t)n < sizeof(jbuf)) {
                send_ble_notify("AUDIO->BLE", jbuf, (size_t)n);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}

/* ---- TJC UART1 Screen UI Task ---- */
static const uint8_t gb_vis_pause[] = {0xd2,0xd1,0xd4,0xdd,0xcd,0xa3};           /* 已暂停 */
static const uint8_t gb_cat_std[]   = {0xc3,0xa8,0x20,0xd5,0xbe,0xc1,0xa2};      /* 猫 站立 */
static const uint8_t gb_cat_sit[]   = {0xc3,0xa8,0x20,0xd7,0xf8,0xd7,0xcb};      /* 猫 坐姿 */
static const uint8_t gb_cat_lie[]   = {0xc3,0xa8,0x20,0xc5,0xbf,0xce,0xd4};      /* 猫 趴卧 */
static const uint8_t gb_cat_unk[]   = {0xc3,0xa8,0x20,0xce,0xb4,0xd6,0xaa};      /* 猫 未知 */
static const uint8_t gb_dog_std[]   = {0xb9,0xb7,0x20,0xd5,0xbe,0xc1,0xa2};      /* 狗 站立 */
static const uint8_t gb_dog_sit[]   = {0xb9,0xb7,0x20,0xd7,0xf8,0xd7,0xcb};      /* 狗 坐姿 */
static const uint8_t gb_dog_lie[]   = {0xb9,0xb7,0x20,0xc5,0xbf,0xce,0xd4};      /* 狗 趴卧 */
static const uint8_t gb_dog_unk[]   = {0xb9,0xb7,0x20,0xce,0xb4,0xd6,0xaa};      /* 狗 未知 */

static QueueHandle_t g_tjc_events = NULL;

static int vis_face_pic(vis_cls_t cls, vis_pose_t pose)
{
    if (cls == VIS_CLS_CAT) {
        if (pose == VIS_POSE_LIE) return PL_TJC_PIC_RELAX;
        if (pose == VIS_POSE_STD) return PL_TJC_PIC_REQUEST;
        return PL_TJC_PIC_IDLE;
    }
    if (cls == VIS_CLS_DOG) {
        if (pose == VIS_POSE_STD) return PL_TJC_PIC_DOG_ACTIVE;
        if (pose == VIS_POSE_SIT) return PL_TJC_PIC_DOG_ALERT;
        if (pose == VIS_POSE_LIE) return PL_TJC_PIC_DOG_REST;
        return PL_TJC_PIC_DOG_IDLE;
    }
    return PL_TJC_PIC_IDLE;
}

static void send_vis_label(const vis_state_t *st)
{
    if (st->cls == VIS_CLS_CAT) {
        switch (st->pose) {
        case VIS_POSE_STD: pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_cat_std, sizeof(gb_cat_std)); break;
        case VIS_POSE_SIT: pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_cat_sit, sizeof(gb_cat_sit)); break;
        case VIS_POSE_LIE: pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_cat_lie, sizeof(gb_cat_lie)); break;
        default:           pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_cat_unk, sizeof(gb_cat_unk)); break;
        }
        return;
    }
    switch (st->pose) {
    case VIS_POSE_STD: pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_dog_std, sizeof(gb_dog_std)); break;
    case VIS_POSE_SIT: pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_dog_sit, sizeof(gb_dog_sit)); break;
    case VIS_POSE_LIE: pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_dog_lie, sizeof(gb_dog_lie)); break;
    default:           pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_dog_unk, sizeof(gb_dog_unk)); break;
    }
}

static void tjc_ui_task(void *param)
{
    (void)param;
    int prev_label_key = -1;
    int prev_conf = -1;
    int prev_gate = -1;
    int prev_pic = -1;
    int prev_mode = -1;
    int prev_b1 = -1;
    bool force_redraw = true;
    TickType_t last_draw = 0;

    for (;;) {
        pl_tjc_event_t ev;
        while (xQueueReceive(g_tjc_events, &ev, 0) == pdTRUE) {
            if (ev.kind == PL_TJC_AUTORESET) {
                force_redraw = true;
                continue;
            }
            if (ev.kind != PL_TJC_TOUCH || ev.touch.event != PL_TJC_EVENT_PUSH || ev.touch.page != 0) {
                continue;
            }
            int comp = (int)ev.touch.comp;
            if (comp == PL_TJC_COMP_START) {
                if (g_auto_mode) g_tjc_paused = !g_tjc_paused;
                else g_manual_capture_req = true;
                force_redraw = true;
            } else if (comp == PL_TJC_COMP_MODE) {
                g_auto_mode = !g_auto_mode;
                g_tjc_paused = false;
                g_manual_capture_req = false;
                force_redraw = true;
            } else if (comp == PL_TJC_COMP_SPECIES) {
                g_species_mode = (g_species_mode == 0) ? 1 : 0;
                pl_set_species_mode(g_species_mode);
                force_redraw = true;
            }
            printf("TOUCH comp=%d auto=%d paused=%d sp=%d\n",
                   comp, g_auto_mode ? 1 : 0, g_tjc_paused ? 1 : 0, g_species_mode);
            fflush(stdout);
        }

        TickType_t now = xTaskGetTickCount();
        if (force_redraw || (now - last_draw) >= pdMS_TO_TICKS(250)) {
            vis_state_t vis_snap;
            TickType_t vis_tick;
            audio_state_t aud_snap;
            portENTER_CRITICAL(&g_frame_lock);
            vis_snap = g_vis_latest;
            vis_tick = g_vis_last_tick;
            aud_snap = g_audio_latest;
            portEXIT_CRITICAL(&g_frame_lock);

            bool vis_active = (vis_snap.rx_seq > 0) && ((now - vis_tick) <= pdMS_TO_TICKS(3500)) && vis_snap.valid;
            bool paused = g_tjc_paused;
            bool auto_now = g_auto_mode;
            int sp_now = g_species_mode;
            pl_set_species_mode(sp_now);

            int mode_val = auto_now ? 1 : 0;
            int b1_val = sp_now;
            int label_key = 0;
            int conf_val = 0;
            int gate_val = 0;
            int pic_id = PL_TJC_PIC_IDLE;

            if (paused) {
                label_key = 900;
                conf_val = prev_conf >= 0 ? prev_conf : 0;
                gate_val = prev_gate >= 0 ? prev_gate : 0;
                pic_id = prev_pic >= 0 ? prev_pic : PL_TJC_PIC_IDLE;
            } else if (vis_active) {
                b1_val = (vis_snap.cls == VIS_CLS_DOG) ? 1 : 0;
                label_key = 200 + vis_snap.cls * 10 + vis_snap.pose;
                conf_val = vis_snap.conf;
                gate_val = (vis_snap.conf >= 50 || aud_snap.trigger) ? 1 : 0;
                pic_id = vis_face_pic(vis_snap.cls, vis_snap.pose);
            } else if (!auto_now && (aud_snap.capturing || g_manual_capture_req)) {
                label_key = 100 + (int)PL_TEXT_BUSY;
                conf_val = aud_snap.have_result ? aud_snap.conf : 0;
                gate_val = aud_snap.trigger ? 1 : 0;
                pic_id = pl_face_pic_of(PL_TEXT_BUSY);
            } else if (aud_snap.have_result) {
                label_key = 100 + (int)aud_snap.text_code;
                conf_val = aud_snap.conf;
                gate_val = aud_snap.trigger ? 1 : 0;
                pic_id = aud_snap.face_pic;
            } else {
                pl_text_code_t init_code = auto_now ? PL_TEXT_BUSY : PL_TEXT_IDLE;
                label_key = 100 + (int)init_code;
                conf_val = 0;
                gate_val = 0;
                pic_id = pl_face_pic_of(init_code);
            }

            if (force_redraw) {
                pl_tjc_page(PL_TJC_PAGE_NAME);
                prev_label_key = prev_conf = prev_gate = prev_pic = prev_mode = prev_b1 = -1;
                force_redraw = false;
            }
            if (mode_val != prev_mode) {
                pl_tjc_text_code(PL_TJC_NAME_MODE, auto_now ? PL_TEXT_AUTO : PL_TEXT_MANUAL);
                prev_mode = mode_val;
            }
            if (b1_val != prev_b1) {
                pl_tjc_text_code(PL_TJC_NAME_B1, (b1_val == 1) ? PL_TEXT_SP_DOG : PL_TEXT_SP_CAT);
                prev_b1 = b1_val;
            }
            if (label_key != prev_label_key) {
                if (paused) {
                    pl_tjc_text_gb(PL_TJC_NAME_LABEL, gb_vis_pause, sizeof(gb_vis_pause));
                } else if (vis_active) {
                    send_vis_label(&vis_snap);
                } else {
                    pl_tjc_text_code(PL_TJC_NAME_LABEL, (pl_text_code_t)(label_key - 100));
                }
                prev_label_key = label_key;
            }
            if (conf_val != prev_conf) {
                pl_tjc_val(PL_TJC_NAME_CONF, conf_val);
                prev_conf = conf_val;
            }
            if (gate_val != prev_gate) {
                pl_tjc_text_code(PL_TJC_NAME_GATE, gate_val ? PL_TEXT_GATE_PASS : PL_TEXT_GATE_LOW);
                prev_gate = gate_val;
            }
            if (pic_id >= 0 && pic_id != prev_pic) {
                pl_tjc_pic(PL_TJC_NAME_FACE, pic_id);
                prev_pic = pic_id;
            }
            last_draw = now;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

static void start_tjc_screen(void)
{
    g_tjc_events = xQueueCreate(8, sizeof(pl_tjc_event_t));
    if (!g_tjc_events || pl_tjc_init(g_tjc_events) != ESP_OK) {
        ESP_LOGW(TAG, "TJC UART1 init failed (continuing without TJC)");
        return;
    }
    pl_tjc_set_busy_drop_comp(PL_TJC_COMP_START);
    g_tjc_ready = true;
    xTaskCreate(tjc_ui_task, "tjc_ui", 3072, NULL, 4, NULL);
    printf("TJC_INIT_OK uart=1 tx=%d rx=%d baud=%d\n",
           CONFIG_PETLINK_TJC_TX_GPIO, CONFIG_PETLINK_TJC_RX_GPIO, CONFIG_PETLINK_TJC_BAUD);
    fflush(stdout);
}

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    printf("\nPETLINK_HYBRID version=2.0.0-idf target=esp32s3 psram=%u\n",
           (unsigned)esp_psram_get_size());
    fflush(stdout);

    ESP_ERROR_CHECK(nimble_port_init());
    ble_hs_cfg.sync_cb = ble_on_sync;
    ble_hs_cfg.reset_cb = ble_on_reset;
    ble_svc_gap_device_name_set(BLE_DEV_NAME);
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ESP_ERROR_CHECK(ble_gatts_count_cfg(gatt_svcs));
    ESP_ERROR_CHECK(ble_gatts_add_svcs(gatt_svcs));
    nimble_port_freertos_init(nimble_host_task);

    start_wifi_if_configured();
    start_tjc_screen();
    xTaskCreate(audio_task, "pl_audio", 6144, NULL, 3, NULL);
    xTaskCreate(serial_rx_task, "ser_rx", 4096, NULL, 5, NULL);
}
