@echo off
setlocal
cd /d "%~dp0"
call gradlew.bat --no-daemon assembleDebug %*
exit /b %errorlevel%
