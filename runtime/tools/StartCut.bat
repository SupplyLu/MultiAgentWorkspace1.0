@echo off
REM StartCut.bat - Signal the start of Cut stage
cd /d "%~dp0"

python "%~dp0signal_bridge.py" ^
    --agent_id %AGENT_ID% ^
    --task_id %TASK_ID% ^
    --signal start_cut ^
    --pool package

exit /b %ERRORLEVEL%
