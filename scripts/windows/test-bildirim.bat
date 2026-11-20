@echo off
rem Abonelere test bildirimi gonderir (baslat.bat acik olmali).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m cryptobot test-alert
pause
