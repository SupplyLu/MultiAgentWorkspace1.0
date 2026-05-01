"""手动拉起一个可见的 worker 窗口进行演示"""

import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.runtimes.work_runtime import WorkRuntime


def main():
    # 使用真实的 pools 目录
    root = Path(__file__).parent.parent.parent
    pools_work = root / "pools" / "work"

    # 确保目录存在
    queue_dir = pools_work / "Queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    # 创建一个简单任务
    task_file = queue_dir / "demo_task.txt"
    task_file.write_text(
        """PROJECT_KEY: SignalBridge-v1-Demo
POOL: work

请在你的 workspace 目录创建一个 hello.txt 文件，内容为 "Hello from WorkRuntime!"
然后发送 online、start_writing、done 信号。
""",
        encoding="utf-8",
    )

    print(f"任务文件已创建: {task_file}")
    print(f"Queue 内容: {list(queue_dir.iterdir())}")

    # 初始化 Runtime
    runtime = WorkRuntime(root_dir=root, signal_port=18850)
    runtime.start()
    print("信号服务器已启动: http://localhost:18850")

    # 真实派发
    print("\n准备派发任务并拉起 worker...")
    result = runtime.dispatch_next(dry_run=False)

    if result["dispatched"]:
        launch = result["launch"]
        print(f"\n[OK] Worker 已拉起!")
        print(f"  槽位: {result['slot_id']}")
        print(f"  任务: {result['task_id']}")
        print(f"  PID: {launch.get('pid')}")
        print(f"  命令: {launch.get('command')}")
        print(f"\n你现在应该能看到一个新的 CMD 窗口弹出，标题为 'worker_01'")
        print("该窗口会运行 Claude CLI 并读取任务文件。")
        print("\n按 Ctrl+C 停止监控...")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n清理中...")
            runtime._launch_manager.cleanup_launch(launch)
            runtime.stop()
            print("已停止")
    else:
        print(f"派发失败: {result.get('error')}")
        runtime.stop()


if __name__ == "__main__":
    main()
