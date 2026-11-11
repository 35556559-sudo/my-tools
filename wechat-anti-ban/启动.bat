@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   微信防封助手 启动中...
echo ========================================
echo.
echo 快捷键: Ctrl+Shift+G
echo 在微信输入框打字后按快捷键即可生成纯文字GIF
echo.
echo 关闭此窗口即可退出程序
echo.
python main.py
pause
