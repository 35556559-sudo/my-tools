@echo off
chcp 65001 >nul
rem ===== 轻沙箱 LightSandbox 启动器 =====
rem 用系统自带的 py 启动器（无黑色窗口）打开界面；不行则退回 pythonw
cd /d "%~dp0"

if exist "C:\Windows\pyw.exe" (
    start "" "C:\Windows\pyw.exe" -3 "%~dp0light_sandbox.py"
) else (
    start "" pythonw "%~dp0light_sandbox.py"
)
