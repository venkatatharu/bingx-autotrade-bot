@echo off
title BingX Trading Bot v4
cd /d "c:\Users\avulu\OneDrive\Desktop\bingx bot"
set AUTO_CONFIRM=1

:start
echo ============================================
echo   BingX Bot v4 Starting...
echo ============================================
echo.
"C:\Users\avulu\AppData\Local\Programs\Python\Python313\python.exe" -X utf8 bingx_autotrade_bot.py
echo.
echo ============================================
echo   Bot stopped. Auto-restarting in 10s...
echo   Press Ctrl+C to stop the restart.
echo ============================================
timeout /t 10
goto :start
