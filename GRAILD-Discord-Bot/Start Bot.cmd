@echo off
cd /d "%~dp0"
title GRAILD Discord Bot
if not exist ".venv\Scripts\python.exe" (
    echo Python environment missing. Follow the setup instructions in README.md.
    pause
    exit /b 1
)
echo Keep this window open while you want the bot online.
echo If the bot is already running, close this window to avoid running two copies.
echo Press Ctrl+C to stop the bot.
".venv\Scripts\python.exe" bot.py
pause
