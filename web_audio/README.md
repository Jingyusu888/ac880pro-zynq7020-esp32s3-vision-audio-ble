# PetLink Web & Audio 子系统（精简重构版）

本目录从原 `D:\petlink2` 迁移并精简重构，剥离了已废弃的 v1 脚本（`src/_migrated/`）、旧静态前端（`app/frontend/`）、历史实验模型以及 3+ GB 数据/构建缓存（已冷归档至 `E:\archive\petlink_legacy\`）。

## 目录结构

- `src/petlink/`：8kHz 音频特征提取（238 维）、层级 LR 推理与训练管线
- `models/`：现役 4 个模型包（猫 `b0_v5`、狗 `b0_dog_v1`、`dog_gate_v1`、`species_gate_v1`）
- `configs/`：特征与模型配置（`paths.yaml` 已去除了硬编码盘符路径）
- `app/backend/`：FastAPI 后端（认证、宠物档案、猫/狗音频识别、社区地基 P0、IMU 接口）
- `app/frontend-web/`：React + Vite + TypeScript 前端源码
- `tools/`：板端 C 头文件参数导出与 HMI 容器解析工具
- `docs/`：BLE 协议 v1、ESP32 引脚图与历史项目审阅记录

## 本地运行

```powershell
cd web_audio
# 1. 创建并安装虚拟环境（或直接复用 E:\python\pet_link_venv）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps

# 2. 构建前端（可选；不构建时后端也会正常启动并返回 API 状态）
cd app\frontend-web && npm install && npm run build && cd ..\..

# 3. 启动后端服务
.venv\Scripts\python.exe -m uvicorn app.backend.main:app --port 8765

# 4. 运行社区与后端冒烟测试
.venv\Scripts\python.exe -m app.backend.tests.test_community_smoke
```
