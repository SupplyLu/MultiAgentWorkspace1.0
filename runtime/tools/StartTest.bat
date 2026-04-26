@echo off
REM StartTest.bat - Signal the start of Test stage
cd /d "%~dp0"

python "%~dp0signal_bridge.py" ^
    --agent_id %AGENT_ID% ^
    --task_id %TASK_ID% ^
    --signal start_test ^
    --pool package

exit /b %ERRORLEVEL%
