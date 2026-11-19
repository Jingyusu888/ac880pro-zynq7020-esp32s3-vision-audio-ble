#ifndef PL_TJC_DISPLAY_H
#define PL_TJC_DISPLAY_H
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include <stdint.h>
#include <stddef.h>
#include "ui_text.h"

/* TJC/Nextion 指令集串口屏驱动（UART1）。
 *
 * 编码契约（重要）:
 *   HMI 工程字库是 gb2312，固件 C 源字面量是 UTF-8，直接发必然乱码。
 *   凡是要显示中文，一律走 pl_tjc_text_code()，字节由 ui_text.c 提供（gb2312）。
 *   pl_tjc_text() 只保留给纯 ASCII 场景。
 *
 * 帧的拼装与解析全部下沉到 tjc_proto.c（纯逻辑、可在 PC 上单测），
 * 本文件只负责"把字节送进 UART"和"把解出的事件投进队列"。
 */

typedef struct {
    uint8_t page;   /* 触摸事件所在页 */
    uint8_t comp;   /* 控件 ID */
    uint8_t event;  /* 1=按下 0=弹起（TJC/Nextion 协议事实，help.pdf p35） */
} pl_tjc_touch_t;

typedef enum {
    PL_TJC_TOUCH,       /* 触摸事件(pl_tjc_touch_t) */
    PL_TJC_AUTORESET,   /* 0x88 屏自复位通知 */
    PL_TJC_GETVAL,      /* get 返回: value 字段 */
} pl_tjc_event_kind_t;

typedef struct {
    pl_tjc_event_kind_t kind;
    union {
        pl_tjc_touch_t touch;
        uint32_t value;
    };
} pl_tjc_event_t;

esp_err_t pl_tjc_init(QueueHandle_t events_out);
/* 切页: 页名或 "0".."n" */
esp_err_t pl_tjc_page(const char *page);
/* 组件文本(纯 ASCII)。中文请用 pl_tjc_text_code。 */
esp_err_t pl_tjc_text(const char *comp, const char *ascii_text);
/* 组件文本(原始字节，调用方保证编码与字库一致) */
esp_err_t pl_tjc_text_gb(const char *comp, const uint8_t *gb, size_t len);
/* 组件文本(推荐入口): 按文案 code 自动取 gb2312 字节 */
esp_err_t pl_tjc_text_code(const char *comp, pl_text_code_t code);
/* 组件图片/数值 */
esp_err_t pl_tjc_pic(const char *comp, int pic_id);
esp_err_t pl_tjc_val(const char *comp, int32_t val);
/* 背光 0-100 */
esp_err_t pl_tjc_dim(int percent);
/* 原始指令（如 "tsw mode,1"）：用于编辑器里没有的运行时属性（文本控件触摸使能等） */
esp_err_t pl_tjc_cmd(const char *cmd);

/* 忙碌窗口：v6 任务书「忙时重复点击不得积压成多轮识别」。
 * busy=true 期间到达的、comp==busy_drop_comp 的触摸帧在接收任务里直接丢弃
 * （不入队），因此不会在下一轮开始时被消费成一次多余识别。
 * 只丢"开始"这一个控件；切猫/狗、切自动/手动仍按任务书排队待生效。 */
void pl_tjc_set_busy(bool busy);
void pl_tjc_set_busy_drop_comp(int comp);
/* 运行时改波特率(同步改 UART1 与屏) */
esp_err_t pl_tjc_baud(uint32_t baud);
#endif
