#include "tjc_proto.h"
#include <string.h>
#include <stdio.h>
#include <inttypes.h>

#define TERM_BYTE 0xFFu
#define VAR_LEN   0xFFu   /* need 字段取此值表示变长帧(0x70) */

/* ---------------------- 发送侧 ---------------------- */

static int put(uint8_t *out, size_t cap, size_t *n, uint8_t b) {
    if (*n >= cap) return 0;
    out[(*n)++] = b;
    return 1;
}

static int put_mem(uint8_t *out, size_t cap, size_t *n, const void *src, size_t len) {
    const uint8_t *s = (const uint8_t *)src;
    if (*n + len > cap) return 0;
    memcpy(out + *n, s, len);
    *n += len;
    return 1;
}

static int put_term(uint8_t *out, size_t cap, size_t *n) {
    if (*n + 3 > cap) return 0;
    out[(*n)++] = TERM_BYTE;
    out[(*n)++] = TERM_BYTE;
    out[(*n)++] = TERM_BYTE;
    return 1;
}

size_t tjc_build_text(uint8_t *out, size_t cap, const char *comp,
                      const uint8_t *text, size_t text_len) {
    if (!out || cap < 8 || !comp) return 0;
    size_t n = 0;
    if (!put_mem(out, cap, &n, comp, strlen(comp))) return 0;
    if (!put_mem(out, cap, &n, ".txt=\"", 6))       return 0;
    for (size_t i = 0; i < text_len; i++) {
        uint8_t b = text[i];
        /* 引号与反斜杠按 TJC 要求转义；0xFF 双写，避免被当成帧尾 */
        if (b == '"' || b == '\\') {
            if (!put(out, cap, &n, '\\')) return 0;
        }
        if (!put(out, cap, &n, b)) return 0;
        if (b == TERM_BYTE && !put(out, cap, &n, TERM_BYTE)) return 0;
    }
    if (!put(out, cap, &n, '"')) return 0;
    if (!put_term(out, cap, &n)) return 0;
    return n;
}

size_t tjc_build_int(uint8_t *out, size_t cap, const char *comp,
                     const char *attr, int32_t value) {
    if (!out || cap < 8 || !comp || !attr) return 0;
    size_t n = 0;
    char num[16];
    int k = snprintf(num, sizeof(num), "%" PRIi32, value);
    if (k <= 0 || (size_t)k >= sizeof(num)) return 0;
    if (!put_mem(out, cap, &n, comp, strlen(comp))) return 0;
    if (!put(out, cap, &n, '.'))                    return 0;
    if (!put_mem(out, cap, &n, attr, strlen(attr))) return 0;
    if (!put(out, cap, &n, '='))                    return 0;
    if (!put_mem(out, cap, &n, num, (size_t)k))     return 0;
    if (!put_term(out, cap, &n))                    return 0;
    return n;
}

size_t tjc_build_assign(uint8_t *out, size_t cap, const char *name, int32_t value) {
    if (!out || cap < 8 || !name) return 0;
    size_t n = 0;
    char num[16];
    int k = snprintf(num, sizeof(num), "%" PRIi32, value);
    if (k <= 0 || (size_t)k >= sizeof(num)) return 0;
    if (!put_mem(out, cap, &n, name, strlen(name))) return 0;
    if (!put(out, cap, &n, '='))                    return 0;
    if (!put_mem(out, cap, &n, num, (size_t)k))     return 0;
    if (!put_term(out, cap, &n))                    return 0;
    return n;
}

size_t tjc_build_raw(uint8_t *out, size_t cap, const char *cmd) {
    if (!out || cap < 4 || !cmd) return 0;
    size_t n = 0;
    if (!put_mem(out, cap, &n, cmd, strlen(cmd))) return 0;
    if (!put_term(out, cap, &n)) return 0;
    return n;
}

/* ---------------------- 接收侧 ---------------------- */

/* 依帧头给出数据域长度；返回 -1 表示不是可识别帧头，0 表示单字节帧 */
static int payload_len_of(uint8_t head) {
    switch (head) {
    case 0x65: return 3;      /* 触摸: page, comp, event */
    case 0x66: return 1;       /* 当前页号 */
    case 0x67: return 5;       /* 坐标: x(2) y(2) event(1) */
    case 0x70: return VAR_LEN; /* 字符串返回: 变长 */
    case 0x71: return 4;       /* 数值返回: 4 字节 LE */
    case 0x86: case 0x87: case 0x88: return 0;  /* 睡眠/唤醒/自复位 */
    default:   break;
    }
    /* 单字节错误码区间（0x00 指令失败 … 0x1A 变量无效 … 0x24） */
    if (head <= 0x24) return 0;
    return -1;
}

void tjc_parser_reset(tjc_parser_t *p) {
    if (!p) return;
    p->state = 0; p->head = 0; p->n = 0;
    p->need = 0; p->term = 0; p->ff_run = 0;
}

static void emit(tjc_parser_t *p, tjc_frame_t *f) {
    memset(f, 0, sizeof(*f));
    f->head = p->head;
    switch (p->head) {
    case 0x65:
        f->kind = TJC_FRAME_TOUCH;
        f->page = p->body[0]; f->comp = p->body[1]; f->event = p->body[2];
        break;
    case 0x67:
        f->kind = TJC_FRAME_TOUCHCOORD;
        f->x = (uint16_t)(p->body[0] | ((uint16_t)p->body[1] << 8));
        f->y = (uint16_t)(p->body[2] | ((uint16_t)p->body[3] << 8));
        f->event = p->body[4];
        break;
    case 0x71:
        f->kind = TJC_FRAME_GETNUM;
        f->value = ((uint32_t)p->body[0]) | ((uint32_t)p->body[1] << 8) |
                   ((uint32_t)p->body[2] << 16) | ((uint32_t)p->body[3] << 24);
        break;
    case 0x70:
        f->kind = TJC_FRAME_GETSTR;
        f->str = p->body; f->str_len = p->n;
        break;
    case 0x86: case 0x87: case 0x88:
        f->kind = TJC_FRAME_EVENT;
        break;
    default:
        f->kind = (p->head <= 0x24) ? TJC_FRAME_ERROR : TJC_FRAME_NONE;
        break;
    }
}

int tjc_parser_feed(tjc_parser_t *p, uint8_t byte, tjc_frame_t *frame) {
    if (!p || !frame) return 0;

    if (p->state == 0) {                       /* S_SYNC: 找帧头 */
        if (byte == TERM_BYTE) return 0;       /* 帧间填充，跳过 */
        int need = payload_len_of(byte);
        if (need < 0) return 0;                /* 噪声，丢弃 */
        p->head = byte; p->n = 0; p->term = 0; p->ff_run = 0;
        p->need = (uint8_t)need;
        p->state = (need == 0) ? 2 : 1;        /* 单字节帧直接进入等帧尾 */
        return 0;
    }

    if (p->state == 1) {                      /* S_BODY: 收数据域 */
        if (p->need == VAR_LEN) {
            if (byte == TERM_BYTE) {
                p->ff_run++;
                if (p->ff_run == 3) { emit(p, frame); tjc_parser_reset(p); return 1; }
                return 0;
            }
            p->ff_run = 0;
            if (p->n >= sizeof(p->body)) { tjc_parser_reset(p); return 0; }
            p->body[p->n++] = byte;
            return 0;
        }
        if (p->n >= sizeof(p->body)) { tjc_parser_reset(p); return 0; }
        p->body[p->n++] = byte;
        if (p->n >= p->need) { p->state = 2; p->term = 0; }
        return 0;
    }

    /* S_TERM: 等三个 FF */
    if (byte == TERM_BYTE) {
        p->term++;
        if (p->term == 3) { emit(p, frame); tjc_parser_reset(p); return 1; }
        return 0;
    }
    /* 帧尾被破坏：丢掉这半帧，把当前字节当作可能的帧头重新喂一次（最多递归一层） */
    tjc_parser_reset(p);
    return tjc_parser_feed(p, byte, frame);
}
