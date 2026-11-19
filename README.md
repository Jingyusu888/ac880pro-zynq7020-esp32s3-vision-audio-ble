# ac880pro-zynq7020-esp32s3-vision-audio-ble

**Zynq-7020 (AC880PRO) PS+PL 异构边缘视觉计算 × ESP32-S3 端侧声学感知与本地触摸屏 × BLE 移动客户端系统**

> **求实习 ing**：广东某 985 高校电信方向大三学生（FPGA PS+PL 异构加速 / 嵌入式 Linux / ESP32 与端侧 AI），欢迎技术交流或实习内推，联系邮箱：`jingyusu888@gmail.com`。

基于 **Xilinx Zynq-7020 (`xc7z020clg484-2`)** 与 **ESP32-S3-N8R2** 构建的全本地化视听协同宠物行为感知系统：

- **边缘视觉端（AC880PRO）**：PL 端完成 OV5640（720p DVP）采集、DDR3L 三帧异步缓存与 1280×720@60Hz HDMI2 实时叠加；通过 `256×144` RGB565 BRAM 单缓冲安全邮箱（`~49.70 ms`）向 PS 端 ARM Linux（`ncnn`）移交缩略图，运行 `YOLOv5n-320` 检测与 `RTMPose-m AP-10K INT8` 17 关键点骨架估计及零训练站/坐/卧姿态判定，最终通过 AXI4-Lite 与 VSYNC 影子锁存两级流水 OSD 无撕裂绘回 HDMI2，并以 UDP JSON 实时外发结构化姿态流。
- **端侧声学与交互端（ESP32-S3 + INMP441 + TJC 480×272 屏）**：采用 `2.0.0-idf` 一体化双模固件（`1.01 MB`，占用 2 MB `factory` 分区 50%，全音频工作区驻留 2 MB PSRAM），支持**无视觉时自主循环运行 238 维猫/狗声学分类，有视觉流接入（3.5s 内）自动切入视听协同模式**，驱动 GB2312 中文串口触摸屏并经 BLE Nordic UART Service（广播名 `Petlink-ESP32S3`，UUID `6E400001-...`）推送至手机端。
- **移动端（Flutter App `0.3.0+4`）**：通过 BLE NUS 订阅实时接收融合 JSON 帧，展示物种、站/坐/卧姿态与声学标签，并以本地 SQLite 留存有效行为变化历史记录。

---

## 核心实机指标

| 子系统 | 关键硬件 / 模型配置 | 实测指标 |
| :--- | :--- | :--- |
| **FPGA PL 视频加速与 OSD** | Vivado 2025.2 (`xc7z020clg484-2`) | `WNS = +0.745 ns`、`WHS = +0.053 ns`、0 时序违例；`30.41%` LUT、`25.71%` BRAM、`15.45%` DSP |
| **PS 端视觉与骨架闭环** | `YOLOv5n-320 FP32` + `RTMPose-m AP-10K INT8` (`percentile=0.9999`) | 抓图拷贝 `49.70 + 7.47 ms`，检测 `~882 ms`，骨架 `~1750 ms`，端到端闭环约 `2.69 s/帧` |
| **ESP32-S3 声学与交互** | `I2S0 (16 kHz -> 8 kHz)` + 238 维猫(`B0`)/狗(`b0_dog_v1`) | 猫诉求类 F1 `0.894`、正向细分 F1 `0.754`；狗门控准确率 `99.84%`、三态 macro-F1 `0.426` |

---

## 目录结构

| 目录 / 文件 | 说明 |
| :--- | :--- |
| `fpga/ac880_petlink_v2025/` | Vivado 2025.2 顶层、核心 RTL（`petlink_ctrl_regs.v`、`petlink_mailbox_capture.v`、`petlink_osd.v`）、约束、`xsim` 仿真、`build_full.tcl`、时序/资源报告及成品比特流 `ac880_petlink_full.bit` |
| `fpga/cam_yolo_ref/`, `fpga/ip_base/` | `build_full.tcl` 引用的 OV5640、DDR3 MIG、AXI 读写、DVI/TMDS 基础 RTL 与 IP 核配置（`.xci`） |
| `board/` | AC880 ARM Linux 实时推理与测试程序（`detect_pet_pose_live.cpp`、`posture_classifier.hpp`、`set_pose.c`） |
| `models/` | 板端唯一运行的轻量化模型（`yolov5n_v7.0_320.ncnn.{param,bin}` 与 `rtmpose_m_ap10k_256_int8.ncnn.{param,bin}`） |
| `esp32_s3/vision_ble_bridge_idf/` | ESP32-S3 一体化双模固件工程（ESP-IDF v5.5.3，包含声学推理调度、串口/UDP 接收、TJC 屏控与 NimBLE NUS 服务） |
| `esp32_s3/audio_tjc_monitor/` | 被主固件交叉引用的声学前端/分类/TJC 协议源码（`firmware/main/`）与 TJC 串口屏工程（`hmi/6.HMI`） |
| `mobile_app/flutter_app/` | Android 移动端 Flutter 客户端源码（v0.3.0+4，BLE NUS 接入、流式容错解析、SQLite 历史记录） |
| `scripts/run_integrated_demo.py` | 一键联调主控脚本（自动配置 AC880 网口 IPv4/IPv6、启动板端视觉推理与无头 UDP→串口中继；可选 `--with-web`） |
| `启动硬件联调.bat` | Windows 双击快捷启动脚本（默认无头模式经 `COM8` 联调） |
| `web_audio/` | 声学特征/模型训练参数与可选本地 Web 工作台（`b0_v5`、`b0_dog_v1`、FastAPI + Vite 前端源码与 `tools/`） |
| `tests/` | 几何姿态分类器单元测试（`test_posture_classifier.cpp`）与 UDP 监听调试工具（`pc_udp_listener.py`） |
| `boot_backup/` | 设备树生成脚本 `make_cam_dtb.py` 及适配后的 `system_cam.dtb` |
| `sample_images/`, `results/` | 测试样例及真机输出对比截图（`results/board_skeleton_opt/dog_m_int8.png`、`cat_m_int8.png`） |

---

## PS-PL 硬件接口概要

- **`0x40000000`（AXI4-Lite，4 KB）**：
  - `0x00` `MAGIC_ID`（`0xAC880720`）
  - `0x04` `CTRL`（`bit0`：抓图请求，`bit1`：释放 BRAM 锁，`bit2`：原子提交 OSD 框与骨架）
  - `0x08` `STATUS`（`bit0`：busy，`bit1`：ready，`[31:16]`：帧序号）
  - `0x10..0x18` `BOX_XY1` / `BOX_XY2` / `BOX_ATTR`（检测框、`CAT/DOG` 类别及 `[4:3]` 姿态码 `0:UNK, 1:STD, 2:SIT, 3:LIE`）
  - `0x1C` `KPT_VALID`（17 位关节点有效掩码，无效点及相连骨架边自动在 PL 侧隐藏）
  - `0x20..0x60` `KPT_XY[0..16]`（17 个 1280×720 屏幕坐标）
- **`0x42000000`（True Dual-Port BRAM，128 KB）**：存储 `1/5` 降采样的 `256×144` RGB565 缩略图（73,728 B）。

---

## 编译、仿真与一键联调

### 1. RTL 自检仿真（Vivado `xsim`）
```powershell
cd fpga\ac880_petlink_v2025\sim\work
xvlog.bat ..\..\rtl\petlink_ctrl_regs.v ..\..\rtl\petlink_mailbox_capture.v ..\..\rtl\petlink_osd.v ..\tb_petlink_bridge.v
xelab.bat tb_petlink_bridge -s tb_sim
xsim.bat tb_sim -R
```

### 2. Vivado 2025.2 全工程重编译
```powershell
cd fpga\ac880_petlink_v2025
vivado.bat -mode batch -source scripts\build_full.tcl
```

### 3. AC880 板端程序编译与单元测试
```bash
# AC880 ARM Linux 上编译
gcc -O2 set_pose.c -o set_pose
g++ -std=c++11 -O3 -march=armv7-a -mfpu=neon -mfloat-abi=hard -fopenmp \
    detect_pet_pose_live.cpp -I<ncnn_inc> <libncnn.a> -lpthread -o detect_pet_pose_live

# 本地几何姿态分类器单元测试
g++ -std=c++14 -O2 -Iboard tests/test_posture_classifier.cpp -o test_posture_classifier
```

### 4. ESP32-S3 一体化双模固件编译烧录（ESP-IDF v5.5.3）
```powershell
cd esp32_s3\vision_ble_bridge_idf
idf.py set-target esp32s3
idf.py build flash monitor -p COM8
```

### 5. 一键启动全链路实机联调
1. 网线直连 AC880PRO 与主机，ESP32-S3（已接入 INMP441 麦克风与 TJC 串口屏）通过 USB 连接至 `COM8`；
2. 双击根目录 `启动硬件联调.bat`，或命令行执行：
   ```powershell
   python scripts\run_integrated_demo.py --esp32-port COM8
   ```
3. 打开手机端安装自 `mobile_app/flutter_app` 的客户端，连接 BLE 设备 `Petlink-ESP32S3`（Service UUID `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`）即可实时查看同步状态与本地历史记录。
