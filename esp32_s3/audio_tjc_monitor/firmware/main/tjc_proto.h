/* TJC/Nextion 协议层 —— 纯逻辑，不依赖 ESP-IDF、不依赖 UART
 *
 * 抽出来的目的: 帧的"拼"和"解"是最容易出错又最难在板子上定位的部分。
 * 单独成模块后可以在 PC 上用 gcc 直接编译并跑回归（见 tests/host_tjc_test.c），
 * 不必烧板、不必接屏。
 *
 * 修掉的两个历史缺陷:
 *   1) 发送侧把 snprintf 的返回值当"应写长度"用 —— 截断时会写入越界长度，
 *      并且声称支持转义但 text 路径根本没做引号转义。
 *      现在所有构造都是"有界写入 + 容量不足返回 0"，绝不产生半帧。
 *   2) 接收侧只靠"找三个 FF"当帧尾 —— 0x71 是定长二进制帧，数据域里可能含 FF，
 *      噪声之后也无法可靠重同步。
 *      现在按"帧头 + 已知长度 + 帧尾"三段解析。
 */
#ifndef TJC_PROTO_H
#define TJC_PROTO_H

#include <stddef.h>
#include <stdint.h>

/* ===================== 发送侧 ===================== */

/* 构造 comp.txt="<text>" + FF FF FF。text 为原始字节（屏侧按字库编码解释，
 * 中文请传 gb2312 字节，见 ui_text.h）。容量不足返回 0。 */
size_t tjc_build_text(uint8_t *out, size_t cap, const char *comp,
                      const uint8_t *text, size_t text_len);

/* 构造 comp.attr=value（如 conf.val=87 / face.pic=3）+ FF FF FF。容量不足返回 0。 */
size_t tjc_build_int(uint8_t *out, size_t cap, const char *comp,
                     const char *attr, int32_t value);

/* 构造系统属性赋值 name=value（如 dim=100 / bauds=9600）+ FF FF FF。
 * 与 tjc_build_int 的区别: 这条没有 "控件名." 前缀。容量不足返回 0。 */
size_t tjc_build_assign(uint8_t *out, size_t cap, const char *name, int32_t value);

/* 构造一条裸指令 + FF FF FF（如 "page 0"）。容量不足返回 0。 */
size_t tjc_build_raw(uint8_t *out, size_t cap, const char *cmd);

/* ===================== 接收侧 ===================== */

typedef enum {
    TJC_FRAME_NONE = 0,
    TJC_FRAME_TOUCH,       /* 0x65 组件触摸事件 (page/comp/event) */
    TJC_FRAME_TOUCHCOORD,  /* 0x67 坐标事件 */
    TJC_FRAME_GETNUM,      /* 0x71 数值返回 */
    TJC_FRAME_GETSTR,      /* 0x70 字符串返回 */
    TJC_FRAME_ERROR,       /* 单字节错误码（0x00..0x24 区间） */
    TJC_FRAME_EVENT        /* 0x86/0x87/0x88 等单字节事件 */
} tjc_frame_kind_t;

typedef struct {
    tjc_frame_kind_t kind;
    uint8_t head;
    uint8_t page, comp, event;    /* TOUCH */
    uint16_t x, y;                 /* TOUCHCOORD */
    uint32_t value;                /* GETNUM */
    const uint8_t *str;            /* GETSTR: 指向解析器内部缓冲，下次 feed 后失效 */
    size_t str_len;
} tjc_frame_t;

typedef struct {
    int state;
    uint8_t head;
    uint8_t body[32];
    uint8_t n;
    uint8_t need;      /* 定长帧的数据域长度；0xFF 表示变长(0x70) */
    uint8_t term;
    uint8_t ff_run;
} tjc_parser_t;

void tjc_parser_reset(tjc_parser_t *p);

/* 逐字节喂入。返回 1 表示 frame 已填满一帧，0 表示尚未凑齐（含噪声被丢弃）。
 * 一帧内的字节流可以是碎片、粘包或前导噪声，解析器都能自行重同步。 */
int tjc_parser_feed(tjc_parser_t *p, uint8_t byte, tjc_frame_t *frame);

#endif /* TJC_PROTO_H */
