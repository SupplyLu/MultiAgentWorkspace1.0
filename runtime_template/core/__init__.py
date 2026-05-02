"""Runtime Template Core Components

Reusable building blocks for creating custom Runtime pools.
"""

from .file_queue import parse_task_file, validate_id_field, parse_task_header
from .json_store import JSONStore, ensure_json_file
from .pool_state_templates import (
    StateTransition,
    PoolStateTemplate,
    PoolStateTemplateRegistry,
)
from .launch_manager import LaunchManager, LaunchRequest
from .windows_process import (
    is_windows,
    create_job_object,
    assign_process_to_job,
    terminate_job,
    query_job_process_count,
    kill_process,
    open_in_explorer,
)

__all__ = [
    # file_queue
    "parse_task_file",
    "validate_id_field",
    "parse_task_header",
    # json_store
    "JSONStore",
    "ensure_json_file",
    # pool_state_templates
    "StateTransition",
    "PoolStateTemplate",
    "PoolStateTemplateRegistry",
    # launch_manager
    "LaunchManager",
    "LaunchRequest",
    # windows_process
    "is_windows",
    "create_job_object",
    "assign_process_to_job",
    "terminate_job",
    "query_job_process_count",
    "kill_process",
    "open_in_explorer",
]
