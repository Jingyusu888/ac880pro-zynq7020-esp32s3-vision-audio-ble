@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting AC880 -^> ESP32-S3 BLE (Petlink-ESP32S3) -^> Mobile App...
"E:\python\pet_link_venv\Scripts\python.exe" -u "scripts\run_integrated_demo.py" --esp32-port COM8
pause
