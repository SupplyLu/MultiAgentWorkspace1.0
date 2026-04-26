@echo off
setlocal enabledelayedexpansion

set AGENT_ID=main_brain_01
set ROLE=main_brain
set POOL=task

cd /d "%~dp0..\..\pools\task\main_brain_01"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& 'claude.cmd' --dangerously-skip-permissions 'Read and strictly follow all instructions in BOOTSTRAP.txt in the current directory. Then wait for user input and respond in the conversation.'"

endlocal
