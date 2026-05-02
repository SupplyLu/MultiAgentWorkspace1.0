# Re-export all shared components
from app.shared.json_store import JSONStore, ensure_json_file
from app.shared.windows_process import (
    is_windows, create_job_object, assign_process_to_job,
    terminate_job, query_job_process_count, is_process_alive_via_job, kill_process,
    build_taskkill_command, open_in_explorer
)
from app.shared.file_queue import (
    normalize_header_key, parse_task_header,
    split_task_file_content, parse_task_file
)
from app.shared.event_bus import Event, EventBus
from app.shared.constants import *
from app.shared.agent_record import (
    AgentRecord, TaskRecord, OwnershipRecord,
    CoordinatorSnapshot, utc_now_iso
)
from app.shared.heartbeat_monitor import (
    is_stale, is_file_idle, seconds_since_file_update, get_file_mtime
)
from app.shared.launch_manager import LaunchManager, LaunchRequest
from app.shared.shutdown_manager import ShutdownManager, ShutdownRequest
