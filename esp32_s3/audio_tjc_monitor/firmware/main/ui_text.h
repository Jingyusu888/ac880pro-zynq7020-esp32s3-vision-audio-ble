/* PetLink 屏显文案单源表
 *
 * 背景: HMI 工程的字库是 gb2312，而固件 C 源里的字符串字面量是 UTF-8。
 * 过去 pl_tjc_text() 直接把 UTF-8 字节发给屏，屏按 gb2312 解，结果就是乱码。
 *
 * 本文件把"要显示什么"和"屏能认的字节"绑死：固件只传 code，字节由这里出。
 * 所有字节由脚本按 gb2312 编码生成，不要手改；改文案要重新生成并跑 host 单测。
 *
 * 约束: 文案里的每个字符都必须在 gb2312 字集内（font32.zi 是"全字符集"，
 * 但像 '—' U+2014、'·' U+00B7 不在 gb2312，编不出来）。
 */
#ifndef PL_UI_TEXT_H
#define PL_UI_TEXT_H

#include <stdint.h>
#include <stddef.h>

/* 屏显文案 code。固件对外只使用这个枚举，不再出现中文字符串字面量。 */
typedef enum {
    PL_TEXT_IDLE = 0,       /* 待机 */
    PL_TEXT_BUSY,           /* 识别中… */
    PL_TEXT_AUTO,           /* 自动 */
    PL_TEXT_MANUAL,         /* 手动 */
    PL_TEXT_GATE_PASS,      /* 有把握 */
    PL_TEXT_GATE_LOW,       /* 低置信 */
    PL_TEXT_RELAX,          /* 亲近放松 */
    PL_TEXT_REQUEST,        /* 诉求 */
    PL_TEXT_THREAT,         /* 抗拒不适 */
    PL_TEXT_DISTRESS,       /* 痛苦倾向 */
    PL_TEXT_UNCERTAIN,      /* 不确定 */
    PL_TEXT_UNKNOWN,        /* 未知 */
    PL_TEXT_DOG_ACTIVE,     /* 活跃 (dog) */
    PL_TEXT_DOG_ALERT,      /* 警觉 (dog) */
    PL_TEXT_DOG_REST,       /* 放松 (dog) */
    PL_TEXT_SP_BOTH,        /* 猫狗（保留备用，两态手选不再使用） */
    PL_TEXT_SP_CAT,         /* 猫 (b1 按钮显示当前物种模式) */
    PL_TEXT_SP_DOG,         /* 狗 */
    PL_TEXT_COUNT
} pl_text_code_t;

/* 取某条文案的 gb2312 字节。返回 NULL / len=0 表示 code 越界。 */
const uint8_t *pl_text_gb(pl_text_code_t code, size_t *len);

/* 由模型标签 + 门槛结果得到屏显文案 code。
 * 红线: 拒识与低置信只走 UNKNOWN / GATE_LOW，绝不产生"没有猫叫"一类文案。
 * unknown 是置信度拒识，不是猫叫检测结论。 */
pl_text_code_t pl_text_for_result(const char *label, int triggered);

/* 门槛文案: 过门槛=有把握，未过=低置信 */
pl_text_code_t pl_text_for_gate(int triggered);

/* 表情图 code -> 屏上图片资源 ID 的映射集中在这里（ID 值见 ui_config.h）。
 * 返回 -1 表示该状态没有对应图（调用方应保持当前图不刷新）。 */
int pl_face_pic_of(pl_text_code_t code);

/* 当前物种模式（0=猫 1=狗）：待机/识别中占位图跟随物种，狗模式不显示猫脸。 */
void pl_set_species_mode(int m);
int  pl_species_mode(void);

#endif /* PL_UI_TEXT_H */
