/* PetLink 屏上资源 ID 集中配置
 *
 * 这里的值必须来自 USART HMI 编辑器里读到的真实 ID，不能猜。
 * 填法见《步骤14_UI资源ID填写对照表.md》。
 *
 * 尚未确定的项保持 -1（见各行 TODO）。为 -1 时：
 *   - 表情图不刷新（保持当前图），不会因为猜错 ID 而显示错图；
 *   - 触摸按钮不匹配任何控件（comp 是 uint8_t，永远不等于 -1），不会误触发；
 *   - 文本控件不受影响（文本走控件名，不走 ID）。
 * 在编辑器里读到真实 ID 后，把对应行的 -1 改成实际值、删掉 TODO 注释即可。
 */
#ifndef PL_UI_CONFIG_H
#define PL_UI_CONFIG_H

/* ---- 控件 ID ----
 * 来源: 解析 C:\hmi\6.HMI 的页面段（att-N 属性块）。2026-11-09 21:55 存档版：
 * mode 由文本控件换成按钮控件后，控件被重新编号，page0 上 8 个对象 id 依次为:
 *   page0=0  face=1  label=2  conf=3  gate=4  b0=5  b1=6  mode=7
 * b0=按钮(开始, sendkey=2)  b1=按钮(猫/狗, sendkey=2)  mode=按钮(手动/自动,
 * x=248 y=178 w=216 h=36, txt="手动" GBK, sendkey=2)。
 * 注意：换控件/删控件会导致 id 重排，工程每次改动后必须重新解析核对这里。
 */
#define PL_TJC_COMP_START   5   /* b0 按钮：开始识别（手动模式下触发一次采集） */
#define PL_TJC_COMP_MODE    7   /* mode 按钮控件：切 自动/手动 采样（按下发 0x65） */
#define PL_TJC_COMP_SPECIES 6   /* b1 按钮：切物种模式 猫 <-> 狗（v6 两态手选） */

/* ---- 图片 ID ----
 * 来源：直接从 petlink_monitor.HMI 容器解析。该文件头部是资源索引表（每条 28 字节：
 * 16 字节文件名 + 4 偏移 + 4 长度 + 4 保留），其中 0.is ~ 8.is 就是图片条目；
 * 逐条取出数据区内的 BMP 与 hmi\*.bmp 源文件做 md5 比对，全部逐字节一致，
 * 故 ID 与文件的对应关系确定无疑（ID 从 0 起）。打开编辑器仍可对照"图片"面板复核。
 *
 *   ID 0 face_idle   ID 1 face_relax   ID 2 bg_idle    ID 3 bg_result
 *   ID 4 face_request ID 5 face_threat ID 6 face_pain  ID 7 mic   ID 8 paw
 */
#define PL_TJC_PIC_IDLE      0   /* face_idle.bmp   */
#define PL_TJC_PIC_RELAX     1   /* face_relax.bmp  */
#define PL_TJC_PIC_REQUEST   4   /* face_request.bmp*/
#define PL_TJC_PIC_THREAT    5   /* face_threat.bmp */
#define PL_TJC_PIC_PAIN      6   /* face_pain.bmp   */
#define PL_TJC_PIC_UNKNOWN   9   /* face_unknown.bmp —— 已按 01~10 顺序导入为 ID 9，
                                     与 hmi\import\10_face_unknown.bmp 逐字节 md5 一致。 */

/* ---- 狗图 ID（猫狗双模式）----
 * 工程里现在还没有狗图，先全部保持 -1：=-1 时 pl_face_pic_of() 退回中性脸(ID 0)，
 * 不会因为猜错 ID 而显示空图/错图。
 * 狗图按 11_face_dog_*.bmp 顺序追加导入后，ID 依次为 10/11/12，把下面三个值填上即可。
 */
/* 狗贴纸（AI 生成，tools/make_dog_faces.py 处理，导入顺序 11~14 -> ID 10~13）。
 * 若编辑器里实际分配的 ID 不同，以编辑器读回值为准改这里。 */
#define PL_TJC_PIC_DOG_IDLE   10   /* dog_idle  狗-待机 */
#define PL_TJC_PIC_DOG_ACTIVE 11   /* dog_active 活跃 */
#define PL_TJC_PIC_DOG_ALERT  12   /* dog_alert  警觉 */
#define PL_TJC_PIC_DOG_REST   13   /* dog_rest   放松 */

/* ---- 控件名（HMI 里控件的 objname，必须与固件完全一致，否则指令写空）---- */
#define PL_TJC_NAME_LABEL "label"   /* 结果中文文案 */
#define PL_TJC_NAME_CONF  "conf"    /* 置信度数值 */
#define PL_TJC_NAME_GATE  "gate"    /* 门槛: 有把握 / 低置信（每次结果刷新） */
#define PL_TJC_NAME_MODE  "mode"    /* 模式: 自动 / 手动（只在切换时刷新） */
#define PL_TJC_NAME_FACE  "face"    /* 表情图 */
#define PL_TJC_NAME_B1    "b1"      /* 物种模式按钮：显示 猫狗 / 只猫 / 只狗 */

/* ---- 页面名（固件只发 "0"，与 HMI 的 page0 对应）---- */
#define PL_TJC_PAGE_NAME "0"

/* ---- 触摸事件边沿 ----
 * TJC/Nextion 协议事实: event=1 是"按下"，event=0 是"弹起"（help.pdf p35）。
 * 固件只处理按下；HMI 里两个按钮必须勾"按下发送组件ID"，
 * 只勾"弹起发送"会被静默忽略。 */
#define PL_TJC_EVENT_PUSH 1
#define PL_TJC_EVENT_POP  0

#endif /* PL_UI_CONFIG_H */
