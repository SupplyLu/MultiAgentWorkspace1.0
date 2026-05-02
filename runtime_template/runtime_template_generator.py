#!/usr/bin/env python3
"""Runtime Template Generator

生成标准化的 Runtime 池实例，包含：
- 标准目录结构（Queue/Outbox/fields/槽位）
- 核心复用组件（file_queue/json_store/pool_state_templates/launch_manager）
- 生命周期 BAT 文件
- 用户自定义 BOOTSTRAP 注入
- 状态机定义加载
"""

import argparse
import json
import shutil
from pathlib import Path


def create_directory_structure(
    output_dir: Path,
    pool_name: str,
    slot_prefix: str,
    slot_count: int,
    include_rejectbox: bool = False,
):
    """创建标准池目录结构"""
    pool_dir = output_dir / "pools" / pool_name

    # 创建标准目录
    (pool_dir / "Queue").mkdir(parents=True, exist_ok=True)
    (pool_dir / "Outbox").mkdir(parents=True, exist_ok=True)
    (pool_dir / "fields").mkdir(parents=True, exist_ok=True)

    if include_rejectbox:
        (pool_dir / "Rejectbox").mkdir(parents=True, exist_ok=True)

    # 创建槽位目录
    for i in range(1, slot_count + 1):
        slot_id = f"{slot_prefix}_{i:02d}"
        slot_workspace = pool_dir / slot_id / "workspace"
        slot_workspace.mkdir(parents=True, exist_ok=True)

    print(f"[OK] Created pool directory structure at {pool_dir}")


def copy_core_components(output_dir: Path, template_dir: Path):
    """复制核心复用组件"""
    core_src = template_dir / "core"
    core_dst = output_dir / "core"

    if core_src.exists():
        shutil.copytree(core_src, core_dst, dirs_exist_ok=True)
        print(f"[OK] Copied core components to {core_dst}")
    else:
        print(f"[WARN] core components not found at {core_src}")


def generate_bat_files(
    output_dir: Path,
    template_dir: Path,
    pool_name: str,
    stage_bats: list[str] = None,
):
    """生成生命周期 BAT 文件"""
    tools_dir = output_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    # 复制 signal_bridge.py
    signal_bridge_src = template_dir / "tools" / "signal_bridge.py"
    if signal_bridge_src.exists():
        shutil.copy(signal_bridge_src, tools_dir / "signal_bridge.py")

    # 生成标准 BAT 文件
    standard_bats = ["Online", "Done", "Blocked", "Failed"]

    for bat_name in standard_bats:
        template_path = template_dir / "tools" / f"{bat_name}.bat.template"
        if template_path.exists():
            shutil.copy(template_path, tools_dir / f"{bat_name}.bat")

    # 生成自定义阶段 BAT
    if stage_bats:
        for stage_signal in stage_bats:
            bat_content = f"""@echo off
setlocal enabledelayedexpansion

set AGENT_ID=%1
set TASK_ID=%2
set SIGNAL={stage_signal}
set POOL=%3
set MESSAGE=%4

python "%~dp0signal_bridge.py" --agent-id %AGENT_ID% --task-id %TASK_ID% --signal %SIGNAL% --pool %POOL% --message %MESSAGE%

endlocal
"""
            bat_name = "".join(word.capitalize() for word in stage_signal.split("_"))
            bat_path = tools_dir / f"Start{bat_name}.bat"
            bat_path.write_text(bat_content, encoding="utf-8")

    print(f"[OK] Generated BAT files in {tools_dir}")


def generate_bootstrap(
    output_dir: Path,
    template_dir: Path,
    pool_name: str,
    user_bootstrap_path: Path = None,
):
    """生成 BOOTSTRAP.txt"""
    tools_dir = output_dir / "tools"
    bootstrap_template = template_dir / "templates" / "BOOTSTRAP.template.txt"

    if not bootstrap_template.exists():
        print(f"[WARN] BOOTSTRAP template not found at {bootstrap_template}")
        return

    template_content = bootstrap_template.read_text(encoding="utf-8")

    # 读取用户自定义 BOOTSTRAP
    user_content = ""
    if user_bootstrap_path and user_bootstrap_path.exists():
        user_content = user_bootstrap_path.read_text(encoding="utf-8")
    else:
        user_content = f"# {pool_name} 池专属执行流程\n\n（用户需要在此补充本池的具体执行规则）"

    # 替换占位符
    final_content = template_content.replace("{POOL_NAME}", pool_name)
    final_content = final_content.replace("{USER_BOOTSTRAP_CONTENT}", user_content)

    bootstrap_path = tools_dir / "BOOTSTRAP.txt"
    bootstrap_path.write_text(final_content, encoding="utf-8")

    print(f"[OK] Generated BOOTSTRAP.txt at {bootstrap_path}")


def load_state_machine(
    output_dir: Path,
    state_machine_path: Path,
):
    """加载并验证状态机定义"""
    if not state_machine_path.exists():
        print(f"[WARN] state machine file not found at {state_machine_path}")
        return None

    with open(state_machine_path, "r", encoding="utf-8") as f:
        state_machine = json.load(f)

    # 验证必需字段
    required_fields = ["pool_id", "initial_state", "terminal_states", "transitions"]
    for field in required_fields:
        if field not in state_machine:
            raise ValueError(f"State machine missing required field: {field}")

    # 保存状态机定义到输出目录
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    state_machine_dst = state_dir / "state_machine.json"
    with open(state_machine_dst, "w", encoding="utf-8") as f:
        json.dump(state_machine, f, indent=2, ensure_ascii=False)

    print(f"[OK] Loaded state machine: {state_machine['pool_id']}")
    print(f"  - Initial state: {state_machine['initial_state']}")
    print(f"  - Terminal states: {', '.join(state_machine['terminal_states'])}")
    print(f"  - Transitions: {len(state_machine['transitions'])}")

    return state_machine


def generate_readme(output_dir: Path, pool_name: str, slot_prefix: str, slot_count: int):
    """生成 README"""
    readme_content = f"""# {pool_name} Runtime Instance

这是使用 Runtime Template 生成的池实例。

## 配置

- **池名称**: {pool_name}
- **槽位前缀**: {slot_prefix}
- **槽位数量**: {slot_count}

## 目录结构

```
pools/{pool_name}/
├── Queue/              # 待处理任务
├── Outbox/             # 已完成任务输出
├── fields/             # 长期保留的项目产物
├── {slot_prefix}_01/   # 槽位 1
│   └── workspace/
├── {slot_prefix}_02/   # 槽位 2
│   └── workspace/
└── ...
```

## 使用方式

1. 将任务文件放入 `pools/{pool_name}/Queue/`
2. 启动 Runtime（需要自行实现 Runtime 编排器）
3. Runtime 会自动派发任务到空闲槽位
4. 完成的任务输出会出现在 `pools/{pool_name}/Outbox/`

## 核心组件

- `core/file_queue.py` - 任务文件解析
- `core/json_store.py` - 跨进程安全 JSON 存储
- `core/pool_state_templates.py` - 状态机模板
- `core/launch_manager.py` - Claude CLI 启动器
- `tools/signal_bridge.py` - 生命周期信号桥

## 下一步

1. 根据 `state/state_machine.json` 实现 Runtime 编排器
2. 根据 `tools/BOOTSTRAP.txt` 调整 Agent 执行流程
3. 测试任务派发和生命周期信号
"""

    readme_path = output_dir / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    print(f"[OK] Generated README at {readme_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate a standardized Runtime pool instance")
    parser.add_argument("--pool-name", required=True, help="Pool name (e.g., review, work)")
    parser.add_argument("--slot-prefix", required=True, help="Slot prefix (e.g., reviewer, worker)")
    parser.add_argument("--slot-count", type=int, required=True, help="Number of slots to create")
    parser.add_argument("--bootstrap-path", type=Path, help="Path to user-provided BOOTSTRAP.txt")
    parser.add_argument("--state-machine-path", type=Path, required=True, help="Path to state machine JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    parser.add_argument("--include-rejectbox", action="store_true", help="Create Rejectbox directory")
    parser.add_argument("--stage-bats", help="Comma-separated list of custom stage signals (e.g., start_review,approved)")

    args = parser.parse_args()

    # 获取模板目录（脚本所在目录）
    template_dir = Path(__file__).parent

    # 解析自定义阶段 BAT
    stage_bats = []
    if args.stage_bats:
        stage_bats = [s.strip() for s in args.stage_bats.split(",")]

    print(f"\nGenerating Runtime instance: {args.pool_name}")
    print(f"   Output: {args.output_dir}")
    print()

    # 创建输出目录
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # 执行生成步骤
    create_directory_structure(
        args.output_dir,
        args.pool_name,
        args.slot_prefix,
        args.slot_count,
        args.include_rejectbox,
    )

    copy_core_components(args.output_dir, template_dir)

    generate_bat_files(
        args.output_dir,
        template_dir,
        args.pool_name,
        stage_bats,
    )

    generate_bootstrap(
        args.output_dir,
        template_dir,
        args.pool_name,
        args.bootstrap_path,
    )

    load_state_machine(args.output_dir, args.state_machine_path)

    generate_readme(args.output_dir, args.pool_name, args.slot_prefix, args.slot_count)

    print()
    print("[DONE] Runtime instance generated successfully!")
    print(f"   Next: cd {args.output_dir} && cat README.md")


if __name__ == "__main__":
    main()
