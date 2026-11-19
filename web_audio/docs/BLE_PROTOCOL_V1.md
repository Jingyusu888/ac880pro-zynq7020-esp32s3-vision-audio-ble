# PetLink BLE 协议规格 v1（板端固件 1.2.0-monitor + 控制通道补丁）

> 本文档的每个字节布局都取自 `petlink_s3_monitor/main/ble_monitor.c`、`monitor_log.h`、`app_main.c` 的实际代码，不是转述。
> 协议版本：**控制通道 v1**（`STATUS[0] == 1`）。

---

## 1. 广播与连接

| 项 | 值 |
|---|---|
| 设备名（scan response） | `PetLink-Monitor` |
| 广播内容 | 128-bit Service UUID（完整）、`FLAGS = LE General Discoverable + BR/EDR Not Supported` |
| 连接模式 | Undirected / General discoverable，不断广播 |
| 同时连接数 | **1**（`conn_handle` 单值，第二个连接会被拒） |
| 配对 / 加密 | **无**。无 bonding、无 MITM、任何手机可直接连 |
| 建议 MTU | 板端请求 256（`CONFIG_BT_NIMBLE_ATT_PREFERRED_MTU=256`），实际取双方较小值 |
| 断开后行为 | 自动重新广播，新连接请重做读表 + 订阅 |

服务 UUID（下文用 `XXXX` 指代最后一段）：

```
504c4b4d-4f4e-4954-4f52-000000000001     ← 主服务 "PLKMONITOR"
```

## 2. 特征表

| 短 UUID | 名称 | 权限 | 长度 | 方向 | 用途 |
|---|---|---|---|---|---|
| `…0002` | TIME | Write | 4 | 手机 → 板 | 校时 |
| `…0003` | CURSOR | Read + Write | 4 | 双向 | 历史游标 |
| `…0004` | REC | Notify | 20 | 板 → 手机 | 识别记录流 |
| `…0005` | CTRL | Write | 2 | 手机 → 板 | **控制命令** |
| `…0006` | STATUS | Read + Notify | 8 | 双向 | 板子状态 |

全部小端（little-endian）。浮点是 IEEE-754 binary32。

> 兼容性：`0005/0006` 是**追加**的。老固件没有这两个特征，`getCharacteristic` 会抛异常 —— 用这个动作本身探测固件是否支持控制。

---

## 3. TIME `…0002` — 校时

写入 **恰好 4 字节**，`uint32` LE。

**关键约定：epoch 是「本地墙钟按 UTC 表示」的秒数。** 板子把 RTC 当墙上时间直接存，不做时区换算。所以：

```js
// 正确：本地时间 - 时区偏移
const epoch = Math.floor((Date.now() - new Date().getTimezoneOffset()*60000)/1000);
// 错误：Math.floor(Date.now()/1000)  ← 会让显示时间整体偏掉一个时区
```

读出来的 `REC.epoch` 用同样的方式反解：`new Date(epoch*1000)` 之后取 **UTC** 字段显示（`getUTCHours()` 等），不要取本地字段。

长度不是 4 → 板子回 `BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN`（0x0D）。

---

## 4. REC `…0004` — 识别记录（20 字节，packed）

每轮识别完成后板子主动 notify 一帧；历史补齐时也走这个特征。

| 偏移 | 类型 | 字段 | 说明 |
|---|---|---|---|
| 0 | u32 LE | `epoch` | 该轮完成时刻，本地墙钟按 UTC 表示 |
| 4 | u32 LE | `round` | 轮次，从 1 递增；**每轮 append 一次历史，所以 `round` 与历史序号 seq 一一对应** |
| 8 | f32 LE | `score` | 展示候选的联合得分，0..1 |
| 12 | f32 LE | `confidence` | 过门槛标签的置信度，0..1 |
| 16 | u8 | `cand_code` | 展示候选标签码（见 §7） |
| 17 | u8 | `gate_label` | 过门槛标签码（可能与 `cand_code` 不同） |
| 18 | u8 | `trigger` | 1 = 过了置信门槛（此时才播语音） |
| 19 | u8 | `reserved` | 恒 0 |

注意：

- **notify 里没有 seq 字段。** 需要 seq 只能靠 `round`（两者一一对应）。若这个假设被打破，表现为历史重复或漏条，用「全量重同步」（写 `CURSOR = 0`）兜底。
- `cand_code` 与 `gate_label` 可以不同：低置信时 `cand_code` 仍给候选，`gate_label` 是门槛判定结果。
- `trigger = 0` 时不要播报、也不要显示「没听到猫叫」这类文案 —— `unknown` 是**置信度拒识**，不是「非猫检测」。

---

## 5. CURSOR `…0003` — 历史游标

| 操作 | 语义 |
|---|---|
| Read | 返回 4 字节 LE：板端最新序号 `head`（1..N，从 1 开始） |
| Write `N` | 板子从第 `N` 条开始，按 20ms 间隔逐条 notify `N, N+1, … head` |
| Write `0` | 板子会把 0 修正为「当前窗口最老的一条」，即**全量**重推 |

- 环形窗口 `PL_HIST_SLOTS = 300`：只保留最近 300 条，更早的被覆盖。`head > 300` 时最老的是 `head-299`。
- 写 `N` 小于最老序号时同样被修正为最老序号。
- 历史推送和实时 notify 共用 `REC` 特征，**手机侧要按 `round` 去重**。

时间估算：300 条 × 20ms ≈ 6 秒。首次连接别一次性拉满 300 条后立刻等结果，两者会混流。

---

## 6. CTRL `…0005` — 控制命令（2 字节）

写入 **恰好 2 字节**：`[op][param]`。长度不对 → 回 `INVALID_ATTR_VALUE_LEN`，板子不执行。

| op | 名称 | param | 效果 |
|---|---|---|---|
| `0x01` | TRIGGER | 忽略（填 0） | 立即采 4 秒并识别一轮。**自动模式下也会插一轮** |
| `0x02` | SET_AUTO | 0 = 手动 / 1 = 自动 | 手动模式下只由 `0x01` 触发；自动模式循环采 |
| `0x03` | SET_VOICE | 0 = 静音 / 1 = 允许播报 | 只关语音，不影响识别、记录、显示 |
| `0x04` | STATUS | 忽略（填 0） | 立即推一帧 STATUS 通知（需已订阅 `0006`） |
| 其它 | — | — | 静默忽略，不报错 |

设计约束：命令在 NimBLE host 任务里只置标志，真正执行在识别主循环里。所以 **写入成功 ≠ 已切换**，以 STATUS 通知为准（切换后板子会自动推一帧）。

---

## 7. STATUS `…0006` — 板子状态（8 字节）

| 偏移 | 类型 | 字段 | 说明 |
|---|---|---|---|
| 0 | u8 | `proto` | 控制协议版本，当前 `1`。老固件无此帧 |
| 1 | u8 | `reserved` | 0 |
| 2 | u8 | `auto_mode` | 1 = 自动循环，0 = 手动触发 |
| 3 | u8 | `voice_enabled` | 1 = 允许语音播报，0 = 静音 |
| 4 | u32 LE | `rounds` | 本次上电以来完成的轮次 |

读一次拿全量；订阅后模式/语音变化会自动推。

---

## 8. 标签码表（`acceptance_log.c` 的 `labels[]`，索引即码）

| 码 | 字符串 | 中文（界面用） |
|---|---|---|
| 0 | `unknown` | 未知 / 拒识 |
| 1 | `positive_or_request_uncertain` | 正向但难细分 |
| 2 | `negative_or_distress_uncertain` | 负向但难细分 |
| 3 | `affiliative_relaxed` | 亲近放松 |
| 4 | `request_seeking` | 诉求·想要东西 |
| 5 | `threat_discomfort` | 抗拒不适 |
| 6 | `pain_distress` | 痛苦倾向 |
| 7 | `active` | 狗：活动 |
| 8 | `alert` | 狗：警觉 |
| 9 | `rest` | 狗：休息 |
| 10 | `not_dog` | 物种门控判为非犬 |

**狗分支注意**：狗路径写入历史的 `cand_code` 取自 `last_candidate.label`（猫的候选体系），而 `gate_label` 会落 7/8/9/10。也就是说狗样本的 `cand_code` 可能是 0 或猫标签 —— 显示时以 `gate_label` 为准，别把 `cand_code` 当狗状态。

---

## 9. 一次完整会话的顺序

```
扫描 → 连接（设备名 PetLink-Monitor）
  ├─ 取服务 504c…0001
  ├─ 取 5 个特征（0005/0006 取不到 = 老固件，无控制能力）
  ├─ 订阅 0006 STATUS → addEventListener
  ├─ 读 0006 → 拿 proto / auto / voice / rounds
  ├─ 订阅 0004 REC → addEventListener
  ├─ 写 0002 TIME = nowAsUtc()
  └─ 读 0003 CURSOR → head；写 0003 = min(本地已有最大 round, head)
        ↓ 板子按 20ms 逐条 notify 历史
用户操作：
  ├─ 点「立即识别」 → 写 0005 = [0x01, 0]
  ├─ 切模式       → 写 0005 = [0x02, 0/1] → 等 STATUS 通知确认
  └─ 静音/恢复     → 写 0005 = [0x03, 0/1] → 等 STATUS 通知确认
```

---

## 10. 已知限制（写进 app 的说明里，别当 bug 修）

1. **单连接**：板子只接受一个中心设备。手机连着时，电脑连不上。
2. **无加密/无配对**：同一空间内任何人都能连上并下命令。演示级，别当产品安全边界。
3. **历史 300 条**上限，掉电即清（RAM 环形缓冲）。
4. **`round` 与 seq 一一对应是推断**，来自代码里每轮 append 一次的事实；协议本身没在 REC 里带 seq。
5. **手动模式下主循环靠 20ms 轮询等待触发**，不是中断驱动，触发到开采有最多几十毫秒延迟。
6. 语音播报有**每情绪 5 分钟冷却**（`CONFIG_PETLINK_VOICE_COOLDOWN_MIN`），同一情绪短时间内不会重复播；这与「静音」是两件事。
7. 板端 epoch 依赖 DS3231；RTC 不在位时 `epoch` 会是 0，界面要能显示「未校时」。
