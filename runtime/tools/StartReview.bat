@echo off
setlocal enabledelayedexpansion

set AGENT_ID=%1
set TASK_ID=%2
set SIGNAL=start_review
set POOL=%3
set MESSAGE=%4

python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal %SIGNAL% --pool %POOL% --message %MESSAGE%

endlocal
