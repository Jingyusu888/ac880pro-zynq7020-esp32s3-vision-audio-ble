#include "ui_text.h"
#include "ui_config.h"
#include <string.h>

/* gb2312 字节表。由脚本按 gb2312 编码生成，勿手改。 */
static const uint8_t gb_idle[]      = {0xb4,0xfd,0xbb,0xfa};                         /* 待机 */
static const uint8_t gb_busy[]      = {0xca,0xb6,0xb1,0xf0,0xd6,0xd0,0xa1,0xad};     /* 识别中… */
static const uint8_t gb_auto[]      = {0xd7,0xd4,0xb6,0xaf};                         /* 自动 */
static const uint8_t gb_manual[]    = {0xca,0xd6,0xb6,0xaf};                         /* 手动 */
static const uint8_t gb_gate_pass[] = {0xd3,0xd0,0xb0,0xd1,0xce,0xd5};                /* 有把握 */
static const uint8_t gb_gate_low[]  = {0xb5,0xcd,0xd6,0xc3,0xd0,0xc5};                /* 低置信 */
static const uint8_t gb_relax[]     = {0xc7,0xd7,0xbd,0xfc,0xb7,0xc5,0xcb,0xc9};      /* 亲近放松 */
static const uint8_t gb_request[]   = {0xcb,0xdf,0xc7,0xf3};                          /* 诉求 */
static const uint8_t gb_threat[]    = {0xbf,0xb9,0xbe,0xdc,0xb2,0xbb,0xca,0xca};      /* 抗拒不适 */
static const uint8_t gb_distress[]  = {0xcd,0xb4,0xbf,0xe0,0xc7,0xe3,0xcf,0xf2};      /* 痛苦倾向 */
static const uint8_t gb_uncertain[] = {0xb2,0xbb,0xc8,0xb7,0xb6,0xa8};                /* 不确定 */
static const uint8_t gb_unknown[]   = {0xce,0xb4,0xd6,0xaa};                          /* 未知 */
static const uint8_t gb_dog_active[]= {0xbb,0xee,0xd4,0xbe};                          /* 活跃 */
static const uint8_t gb_dog_alert[] = {0xbe,0xaf,0xbe,0xf5};                          /* 警觉 */
static const uint8_t gb_dog_rest[]  = {0xb7,0xc5,0xcb,0xc9};                          /* 放松 */
/* 物种模式（v6 两态手选，显示在 b1 按钮上：猫 <-> 狗） */
static const uint8_t gb_sp_both[]   = {0xc3,0xa8,0xb9,0xb7};                           /* 猫狗（保留备用，两态不再使用） */
static const uint8_t gb_sp_cat[]    = {0xc3,0xa8};                                     /* 猫 */
static const uint8_t gb_sp_dog[]    = {0xb9,0xb7};                                     /* 狗 */

/* 当前物种模式（0=猫 1=狗）：待机/识别中占位图跟随物种，狗模式不显示猫脸。 */
static int s_species_mode=0;
void pl_set_species_mode(int m) { s_species_mode = (m==1) ? 1 : 0; }
int  pl_species_mode(void)      { return s_species_mode; }

static const uint8_t *const table[PL_TEXT_COUNT] = {
    gb_idle, gb_busy, gb_auto, gb_manual, gb_gate_pass, gb_gate_low,
    gb_relax, gb_request, gb_threat, gb_distress, gb_uncertain, gb_unknown,
    gb_dog_active, gb_dog_alert, gb_dog_rest,
    gb_sp_both, gb_sp_cat, gb_sp_dog
};

const uint8_t *pl_text_gb(pl_text_code_t code, size_t *len) {
    static const size_t lens[PL_TEXT_COUNT] = {
        sizeof(gb_idle), sizeof(gb_busy), sizeof(gb_auto), sizeof(gb_manual),
        sizeof(gb_gate_pass), sizeof(gb_gate_low),
        sizeof(gb_relax), sizeof(gb_request), sizeof(gb_threat), sizeof(gb_distress),
        sizeof(gb_uncertain), sizeof(gb_unknown),
        sizeof(gb_dog_active), sizeof(gb_dog_alert), sizeof(gb_dog_rest),
        sizeof(gb_sp_both), sizeof(gb_sp_cat), sizeof(gb_sp_dog)
    };
    if ((int)code < 0 || code >= PL_TEXT_COUNT) { if (len) *len = 0; return NULL; }
    if (len) *len = lens[code];
    return table[code];
}

/* 模型标签 -> 屏显文案。
 * 猫四分类全覆盖；狗三分类本轮只给占位中文（验收报告需写明"狗结果仅显示不播报"）。
 * not_dog / unknown 都落 UNKNOWN：它们是置信度拒识，不是"没检测到动物"。 */
pl_text_code_t pl_text_for_result(const char *label, int triggered) {
    if (!label) return PL_TEXT_UNKNOWN;
    if (!strcmp(label, "affiliative_relaxed"))           return PL_TEXT_RELAX;
    if (!strcmp(label, "request_seeking"))                return PL_TEXT_REQUEST;
    if (!strcmp(label, "threat_discomfort"))              return PL_TEXT_THREAT;
    if (!strcmp(label, "pain_distress"))                  return PL_TEXT_DISTRESS;
    if (!strcmp(label, "positive_or_request_uncertain"))  return PL_TEXT_UNCERTAIN;
    if (!strcmp(label, "negative_or_distress_uncertain"))  return PL_TEXT_UNCERTAIN;
    if (!strcmp(label, "active"))                          return PL_TEXT_DOG_ACTIVE;
    if (!strcmp(label, "alert"))                           return PL_TEXT_DOG_ALERT;
    if (!strcmp(label, "rest"))                            return PL_TEXT_DOG_REST;
    (void)triggered;
    return PL_TEXT_UNKNOWN;
}

pl_text_code_t pl_text_for_gate(int triggered) {
    return triggered ? PL_TEXT_GATE_PASS : PL_TEXT_GATE_LOW;
}

/* 表情图映射。ID 值全部来自 ui_config.h（步骤 9/10 抄回图片面板后填写）。
 * 拒识态 PL_TEXT_UNKNOWN 用"未知"图，不用"没有猫叫"之类表述。 */
/* 狗图已导入（ID 10~13）。dog_pic 保留兜底：ID 未配置(-1)时退回中性脸。 */
static int dog_pic(int pic_id) {
    return pic_id >= 0 ? pic_id : PL_TJC_PIC_IDLE;
}

int pl_face_pic_of(pl_text_code_t code) {
    switch (code) {
    case PL_TEXT_IDLE:       /* 待机/识别中占位图跟随物种，狗模式不显示猫脸 */
    case PL_TEXT_BUSY:       return s_species_mode==1 ? dog_pic(PL_TJC_PIC_DOG_IDLE)
                                                      : PL_TJC_PIC_IDLE;
    case PL_TEXT_RELAX:      return PL_TJC_PIC_RELAX;
    case PL_TEXT_REQUEST:    return PL_TJC_PIC_REQUEST;
    case PL_TEXT_THREAT:     return PL_TJC_PIC_THREAT;
    case PL_TEXT_DISTRESS:   return PL_TJC_PIC_PAIN;
    case PL_TEXT_UNCERTAIN:  return PL_TJC_PIC_UNKNOWN;
    case PL_TEXT_UNKNOWN:    return PL_TJC_PIC_UNKNOWN;
    case PL_TEXT_DOG_ACTIVE: return dog_pic(PL_TJC_PIC_DOG_ACTIVE);
    case PL_TEXT_DOG_ALERT:  return dog_pic(PL_TJC_PIC_DOG_ALERT);
    case PL_TEXT_DOG_REST:   return dog_pic(PL_TJC_PIC_DOG_REST);
    default:                 return -1;   /* 物种模式按钮文字等无对应图 */
    }
}
