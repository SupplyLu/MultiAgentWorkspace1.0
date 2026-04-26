"""Bridge to execute local CLI commands for runtime management."""

import subprocess
import os


class RuntimeCommandBridge:
    def restart_pool(self, pool: str) -> dict[str, bool | str]:
        """Restart a specific runtime pool via local script."""
        try:
            # Map pool to main entry script
            entry_map = {
                "work": "main.py",
                "thinking": "main_thinking.py",
                "construct": "main_construct.py",
                "gate": "main_gate.py",
                "post": "main_post.py",
                "package": "main_package.py"
            }
            
            if pool not in entry_map:
                return {"success": False, "error": f"Unknown pool: {pool}"}
                
            script = entry_map[pool]
            
            # Start process without waiting
            process = subprocess.Popen(
                ["python", "-m", f"app.{script[:-3]}"],
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
            )
            
            # Brief check if it crashed immediately
            if process.poll() is not None:
                return {"success": False, "error": "Process crashed immediately on startup"}
                
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
