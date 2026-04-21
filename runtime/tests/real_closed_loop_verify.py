import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.runtimes.work_runtime import WorkRuntime

def main():
    root = Path(__file__).parent.parent.parent
    
    # Create task
    task_file = root / "pools/work/Queue/task_real_verify.txt"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text("TASK_ID: t_real_002\nFEATURE_ID: f_real\n\n请确认：\n1. 执行 .\Online.bat $AGENT_ID $TASK_ID work online\n2. 执行 .\StartWriting.bat $AGENT_ID $TASK_ID work writing\n3. 执行 .\Done.bat $AGENT_ID $TASK_ID work done\n4. 退出！\n", encoding="utf-8")
    
    # Start runtime
    runtime = WorkRuntime(root_dir=root, signal_port=18866)
    runtime.start()
    
    try:
        print("Dispatching...")
        res = runtime.dispatch_next(dry_run=False)
        print("Dispatched:", res)
        
        slot = runtime.get_slot("worker_01")
        if not slot or not slot.busy:
            print("Slot not busy, aborting")
            return
            
        print("Waiting up to 60s for real worker to complete the cycle...")
        for i in range(60):
            if not slot.busy:
                print(f"Success! Slot released after {i} seconds.")
                events = runtime._signal_server.event_store.get_events("worker_01", "t_real_002")
                print("Events generated:")
                for e in events:
                    print(f"  {e['signal']} (to {e.get('to_state')})")

                # Verify slot directory cleanup
                remaining = [
                    f.name for f in slot.slot_dir.iterdir()
                    if f.name != "workspace"
                ]
                if remaining:
                    print(f"WARNING: Slot not fully cleaned, remaining: {remaining}")
                else:
                    print("Slot directory cleaned successfully (only workspace/ remains).")
                break
            time.sleep(1)
        else:
            print("Timeout waiting for worker to finish.")
    finally:
        runtime.stop()

if __name__ == "__main__":
    main()
