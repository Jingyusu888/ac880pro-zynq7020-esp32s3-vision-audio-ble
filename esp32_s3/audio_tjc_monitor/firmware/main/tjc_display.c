#include "tjc_display.h"
#include "tjc_proto.h"
#include "sdkconfig.h"
#include "driver/uart.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <stdio.h>
#include <string.h>

#define TJC_UART   UART_NUM_1
#define TJC_TX_PIN CONFIG_PETLINK_TJC_TX_GPIO
#define TJC_RX_PIN CONFIG_PETLINK_TJC_RX_GPIO

static QueueHandle_t events;
static SemaphoreHandle_t tx_lock;
static tjc_parser_t parser;
/* 忙碌窗口过滤（见 tjc_display.h）：接收任务里按到达时刻判定，避免积压 */
static volatile bool busy_flag;
static int busy_drop_comp = -1;

void pl_tjc_set_busy(bool busy) { busy_flag = busy; }
void pl_tjc_set_busy_drop_comp(int comp) { busy_drop_comp = comp; }

/* 把整帧送进 UART。构造阶段由 tjc_proto 保证"要么完整要么 0 字节"。 */
static esp_err_t send_bytes(const uint8_t *buf, size_t len) {
    if (!buf || len == 0) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(tx_lock, portMAX_DELAY);
    int wr = uart_write_bytes(TJC_UART, buf, len);
    xSemaphoreGive(tx_lock);
    return wr == (int)len ? ESP_OK : ESP_FAIL;
}

/* 帧尾被破坏 / 容量不足时 tjc_proto 返回 0，这里不能当成"发送 0 字节成功" */
static esp_err_t build_or_fail(size_t n, const uint8_t *buf) {
    if (n == 0) return ESP_ERR_INVALID_SIZE;
    return send_bytes(buf, n);
}

static void tjc_rx_task(void *arg) {
    (void)arg;
    uint8_t b[32];
    for (;;) {
        int n = uart_read_bytes(TJC_UART, b, sizeof(b), pdMS_TO_TICKS(100));
        for (int i = 0; i < n; i++) {
            tjc_frame_t fr;
            if (!tjc_parser_feed(&parser, b[i], &fr)) continue;
            pl_tjc_event_t ev;
            switch (fr.kind) {
            case TJC_FRAME_TOUCH:
                if (busy_flag && (int)fr.comp == busy_drop_comp) {
                    /* 识别进行中重复点"开始"：任务书要求不得积压成多轮，直接丢 */
                    printf("TOUCH_DROP_BUSY comp=%u\n", (unsigned)fr.comp); fflush(stdout);
                    break;
                }
                ev.kind = PL_TJC_TOUCH;
                ev.touch.page = fr.page;
                ev.touch.comp = fr.comp;
                ev.touch.event = fr.event;
                xQueueSend(events, &ev, 0);
                break;
            case TJC_FRAME_GETNUM:
                ev.kind = PL_TJC_GETVAL;
                ev.value = fr.value;
                xQueueSend(events, &ev, 0);
                break;
            case TJC_FRAME_EVENT:
                if (fr.head == 0x88) {          /* 屏自复位 */
                    ev.kind = PL_TJC_AUTORESET;
                    xQueueSend(events, &ev, 0);
                }
                break;
            default:
                break;                          /* 错误码/坐标事件暂不透出 */
            }
        }
    }
}

esp_err_t pl_tjc_init(QueueHandle_t events_out) {
    if (!events_out) return ESP_ERR_INVALID_ARG;
    events = events_out;
    uart_config_t cfg = {.baud_rate = CONFIG_PETLINK_TJC_BAUD,.data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,.stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,.source_clk = UART_SCLK_DEFAULT};
    esp_err_t err = uart_param_config(TJC_UART, &cfg);
    if (err != ESP_OK) return err;
    err = uart_set_pin(TJC_UART, TJC_TX_PIN, TJC_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (err != ESP_OK) return err;
    err = uart_driver_install(TJC_UART, 4096, 0, 0, NULL, 0);
    if (err != ESP_OK) return err;
    tx_lock = xSemaphoreCreateMutex();
    if (!tx_lock) return ESP_ERR_NO_MEM;
    tjc_parser_reset(&parser);
    if (xTaskCreate(tjc_rx_task, "tjc_rx", 3072, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    vTaskDelay(pdMS_TO_TICKS(200)); /* 屏上电稳定 */
    return ESP_OK;
}

esp_err_t pl_tjc_page(const char *page) {
    char body[48];
    int k = snprintf(body, sizeof(body), "page %s", page);
    if (k <= 0 || (size_t)k >= sizeof(body)) return ESP_ERR_INVALID_SIZE;
    uint8_t out[64];
    return build_or_fail(tjc_build_raw(out, sizeof(out), body), out);
}

/* 只用于纯 ASCII；中文走 pl_tjc_text_code */
esp_err_t pl_tjc_text(const char *comp, const char *ascii_text) {
    if (!ascii_text) return ESP_ERR_INVALID_ARG;
    uint8_t out[192];
    size_t n = tjc_build_text(out, sizeof(out), comp,
                              (const uint8_t *)ascii_text, strlen(ascii_text));
    return build_or_fail(n, out);
}

esp_err_t pl_tjc_text_gb(const char *comp, const uint8_t *gb, size_t len) {
    uint8_t out[192];
    size_t n = tjc_build_text(out, sizeof(out), comp, gb, len);
    return build_or_fail(n, out);
}

esp_err_t pl_tjc_text_code(const char *comp, pl_text_code_t code) {
    size_t len = 0;
    const uint8_t *gb = pl_text_gb(code, &len);
    if (!gb || len == 0) return ESP_ERR_INVALID_ARG;
    return pl_tjc_text_gb(comp, gb, len);
}

esp_err_t pl_tjc_pic(const char *comp, int pic_id) {
    uint8_t out[64];
    return build_or_fail(tjc_build_int(out, sizeof(out), comp, "pic", pic_id), out);
}

esp_err_t pl_tjc_val(const char *comp, int32_t val) {
    uint8_t out[64];
    return build_or_fail(tjc_build_int(out, sizeof(out), comp, "val", val), out);
}

esp_err_t pl_tjc_dim(int percent) {
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    uint8_t out[32];
    return build_or_fail(tjc_build_assign(out, sizeof(out), "dim", percent), out);
}

/* 发送一条原始 TJC 指令（如 "tsw mode,1"）。调用方保证内容为合法指令与纯 ASCII。
 * 用途：文本控件在编辑器里没有 tsw 属性，触摸使能只能开机后经串口打开。 */
esp_err_t pl_tjc_cmd(const char *cmd) {
    if (!cmd || !*cmd) return ESP_ERR_INVALID_ARG;
    size_t cl = strlen(cmd);
    if (cl > 96) return ESP_ERR_INVALID_SIZE;
    uint8_t out[100];
    memcpy(out, cmd, cl);
    out[cl] = 0xFF; out[cl + 1] = 0xFF; out[cl + 2] = 0xFF;
    return send_bytes(out, cl + 3);
}

esp_err_t pl_tjc_baud(uint32_t baud) {
    uint8_t out[48];
    esp_err_t err = build_or_fail(tjc_build_assign(out, sizeof(out), "bauds", (int32_t)baud), out);
    if (err != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(120)); /* 等屏切换后再切本端 */
    return uart_set_baudrate(TJC_UART, baud);
}
