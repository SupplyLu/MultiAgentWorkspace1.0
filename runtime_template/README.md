# Runtime Template

这是一个从现有 MultiAgentWorkspace Runtime 中抽取出来的**通用 Runtime 模版框架**。

目标：
- 不改现有池实现
- 只抽出核心可复用机制
- 初始化时由用户注入专属 BOOTSTRAP
- 标准化 Queue / Outbox / fields / 槽位结构
- 支持自定义状态机和自定义 bat 生命周期
- **与现有 Runtime 核心机制完全一致，仅在名字 / Bootstrap / 中间信号 bat 名称 / 职能上不同**

## 已抽取的核心

- `core/file_queue.py`：任务文件解析与安全校验
- `core/json_store.py`：跨进程安全 JSON 存储
- `core/pool_state_templates.py`：通用状态机注册与 JSON 加载
- `core/launch_manager.py`：Claude CLI 启动器（含 Windows Job Object 支持）
- `core/windows_process.py`：Windows Job Object / taskkill / explorer 底层封装
- `tools/signal_bridge.py`：生命周期信号桥

## 标准目录结构

```text
{output_dir}/
├── pools/
│   └── {pool_name}/
│       ├── Queue/
│       ├── Outbox/
│       ├── fields/
│       ├── Rejectbox/              # 可选
│       ├── {slot_prefix}_01/
│       │   └── workspace/
│       └── ...
├── tools/
│   ├── Online.bat
│   ├── Done.bat
│   ├── Blocked.bat
│   ├── Failed.bat
│   ├── signal_bridge.py
│   └── BOOTSTRAP.txt
└── core/
    ├── file_queue.py
    ├── json_store.py
    ├── pool_state_templates.py
    ├── launch_manager.py
    └── windows_process.py
```

这套目录结构与现有 Runtime 对齐：
- Pool 内部标准目录仍是 `Queue / Outbox / fields / {slot}/workspace`
- 槽位命名仍是 `{slot_prefix}_{i:02d}`
- 任务主键 / 项目主键的内部流转规则不变
- 模版不改变现有 Runtime 对任务头、状态机、信号、进程清理的核心约束

## 使用方式

运行生成器：

```bash
python runtime_template_generator.py \
  --pool-name review \
  --slot-prefix reviewer \
  --slot-count 2 \
  --bootstrap-path ./my_bootstrap.txt \
  --state-machine-path ./review_state_machine.json \
  --output-dir ./generated_runtime
```

可选参数：
- `--include-rejectbox`：为审批类池生成 Rejectbox
- `--stage-bats start_review,approved,rejected`：生成额外 BAT

## 状态机格式

参考：
- `examples/simple_work_state_machine.json`
- `examples/review_state_machine.json`

## 测试

运行测试套件：

```bash
pytest runtime_template/tests/
```

测试覆盖：
- 核心组件单元测试（file_queue、json_store、pool_state_templates、launch_manager、signal_bridge）
- JSONStore 跨线程 / 跨进程测试
- 生成器集成测试（端到端验证生成的 Runtime 实例结构）

## 依赖

- Python 3.10+
- `filelock`
- Windows 下完整 Job Object 能力需要 `pywin32`

## 设计边界

这个模版当前负责：
- 目录骨架
- 核心复用组件
- 标准 BAT 模版
- BOOTSTRAP 注入位
- 状态机定义加载

这个模版当前**不负责**：
- 直接替换现有 `runtime/app/runtimes/*`
- 自动生成完整 pool runtime 编排器
- 自动迁移现有 work/thinking/construct/gate/package 的业务实现

换句话说：
- **核心基础设施与现有 Runtime 对齐**
- **具体池的名字、Bootstrap、中间信号 bat 名称、职能由用户定义**
- **Queue / slots / fields / Outbox 以及内部项目主键流转规则不应偏离现有 Runtime**

## 下一步

用户在生成实例后需要：
1. 根据 `state/state_machine.json` 实现 Runtime 编排器
2. 根据 `tools/BOOTSTRAP.txt` 调整 Agent 执行流程
3. 测试任务派发、生命周期信号和进程清理
4. 验证生成的 Pool 与现有 Runtime 行为一致
