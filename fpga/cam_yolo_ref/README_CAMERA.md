# AC880 摄像头 → DDR3L → HDMI2

YOLO 后续开发的全局路线与当前进度见 [YOLO 项目总规划](docs/YOLO项目总规划.md)（2026-11-13）；下文保留原摄像头工程的交付记录。

当前主工程：`camera_af/camera_af.xpr`，顶层 `rtl/camera_af/camera_hdmi_af_top.v`。

## 唯一保留位流

[下载文件](delivery/upgrades/autofocus_20261109/camera_hdmi_af_top.bit)

1280×720 原生全屏 + OV5640 单次 AF 候选。此版已 JTAG 下载成功；用户观察 LED 0/1/2 亮、3 灭，未明显感到镜头自动调整。固件报告完成不等于已经证实光学自动对焦。此前清晰改善来自手动调焦。

LED：0 图像初始化、1 AF 固件就绪、2 固件报告聚焦完成、3 AF 错误。本版只在启动/系统复位后对焦一次，不持续追焦。

## 目录入口

|目录|作用|
|---|---|
|`rtl/camera_af/`|当前 AF 顶层、控制器、共享 SCCB 封装、固件 ROM|
|`rtl/camera/`|采集入口、异步 FIFO、AXI 写/读、SCCB，以及非 AF 720p 顶层|
|`cam_yolo.srcs/`|多个阶段共用的显示、采集、时钟、打包、帧管理源文件与原工程 IP|
|`camera_live/ip/`|当前 AF 工程实际引用的时钟与 MIG IP，不能删|
|`camera_af/`|当前 AF Vivado 工程入口|
|`camera_live/camera_live.xpr`|保留的非 AF 摄像头工程，仅源码入口，不再保存独立 bit|
|`cam_yolo.xpr`|保留的原彩条/教学工程，仅源码入口|
|`constraints/`|当前摄像头和 DDR/HDMI 约束|
|`third_party/ov5640_af/`|固定版本的固件来源、参考驱动、LICENSE 和哈希|
|`verification/`|测试源文件、执行脚本、验证日志和板级证据图|
|`delivery/upgrades/autofocus_20261109/`|唯一当前 bit、报告、manifest、构建与下载脚本|
|`docs/`、`图片区/`|原理、阶段报告、流程图和整理记录|

## 构建与验证

在 `delivery/upgrades/autofocus_20261109/` 中运行：

```powershell
& E:/vivado/Xilinx/Vivado/2018.3/bin/vivado.bat -mode batch -source build.tcl
```

AF 针对性仿真入口：`verification/camera_af/run_checks.ps1`。固件 ROM 可由 `scripts/prepare_af_firmware.py` 从固定上游快照重新生成。

重建会重新产生 .runs/.cache 等目录；清理没有改变 HDL、约束或 IP 配置。此次只整理构建产物，没有修改工程的源码引用，也没有硬件重下载。

## 清理记录

2026-11-09：旧位流、综合/仿真缓存、波形、临时调试产物、重复笔记备份及过时顶层生成/打包脚本移出本工程。工程内只保留当前 AF bit 一份。源码、IP、测试源文件及主要报告保留。

永久删除被自动安全检查拒绝，因此上述内容已可恢复地归档到：`D:/Electronic_hardware/FPGA/_cleanup_archive/cam_yolo_20261109/`。本次减少的是工程目录体积，没有释放相应磁盘空间。详见 `docs/CLEANUP_20261109.md`。
