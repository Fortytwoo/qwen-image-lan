@echo off
"%~dp0service\.venv\Scripts\python.exe" -X utf8 "%~dp0service\register_passkey.py" --open
pause
