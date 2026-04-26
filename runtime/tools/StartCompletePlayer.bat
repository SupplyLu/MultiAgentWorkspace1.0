@echo off
REM StartCompletePlayer.bat - Signal the start of CompletePlayer stage
cd /d "%~dp0"

python "%~dp0signal_bridge.py" ^
    --agent_id %AGENT_ID% ^
    --task_id %TASK_ID% ^
    --signal start_complete_player ^
    --pool package

exit /b %ERRORLEVEL%
