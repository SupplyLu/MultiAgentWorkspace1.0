@echo off
REM Reject.bat - Unified rejection entry for all Package stages
REM Writes rejection marker to Rejectbox and sends denied signal
REM
REM Required environment variables:
REM   AGENT_ID          - Slot ID (e.g. cutter_01)
REM   TASK_ID           - Package task ID (e.g. pkg_pid_simulink_001)
REM   PROJECT_NAME      - Project name (e.g. pid_simulink_001)
REM   PACKAGE_STAGE     - Stage that triggered rejection (cut/test/release/complete)
REM   SIGNAL_SERVER_PORT - Signal server port

cd /d "%~dp0"

REM Read rejection reason from file if it exists
set REJECT_REASON_FILE=%~dp0reject_reason.txt
set REJECT_REASON=No reason provided"

if exist "%REJECT_REASON_FILE%" (
    set /p REJECT_REASON=<"%REJECT_REASON_FILE%"
)

REM Write rejection marker to Rejectbox
set REJECTBOX_DIR=%~dp0..\..\pools\package\Rejectbox
if not exist "%REJECTBOX_DIR%" mkdir "%REJECTBOX_DIR%"

echo PROJECT_NAME: %PROJECT_NAME% > "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"
echo TASK_ID: %TASK_ID% >> "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"
echo DENIED_AT_STAGE: %PACKAGE_STAGE% >> "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"
echo REJECTED_BY: %AGENT_ID% >> "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"
echo. >> "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"
echo REASON: >> "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"
echo %REJECT_REASON% >> "%REJECTBOX_DIR%\%PROJECT_NAME%_denied.txt"

REM Send denied signal to Runtime
python "%~dp0signal_bridge.py" ^
    --agent_id %AGENT_ID% ^
    --task_id %TASK_ID% ^
    --signal denied ^
    --pool package

exit /b %ERRORLEVEL%
