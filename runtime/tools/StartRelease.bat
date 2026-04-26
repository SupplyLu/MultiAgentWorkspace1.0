@echo off
REM StartRelease.bat - Signal the start of Release stage
cd /d "%~dp0"

python "%~dp0signal_bridge.py" ^
    --agent_id %AGENT_ID% ^
    --task_id %TASK_ID% ^
    --signal start_release ^
    --pool package

exit /b %ERRORLEVEL%
