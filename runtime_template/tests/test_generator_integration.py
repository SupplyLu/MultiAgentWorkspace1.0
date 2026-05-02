"""Integration tests for runtime_template_generator.py."""

import json
import subprocess
import sys
from pathlib import Path


def test_generator_creates_directory_structure(generator_output_dir, sample_state_machine, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--state-machine-path", str(state_machine_path),
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    pool_dir = generator_output_dir / "pools" / "review"
    assert (pool_dir / "Queue").is_dir()
    assert (pool_dir / "Outbox").is_dir()
    assert (pool_dir / "fields").is_dir()
    assert (pool_dir / "reviewer_01" / "workspace").is_dir()
    assert (pool_dir / "reviewer_02" / "workspace").is_dir()


def test_generator_copies_core_modules(generator_output_dir, sample_state_machine, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--state-machine-path", str(state_machine_path),
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    core_dir = generator_output_dir / "core"
    assert (core_dir / "file_queue.py").is_file()
    assert (core_dir / "json_store.py").is_file()
    assert (core_dir / "pool_state_templates.py").is_file()
    assert (core_dir / "launch_manager.py").is_file()
    assert (core_dir / "windows_process.py").is_file()


def test_generator_copies_signal_bridge(generator_output_dir, sample_state_machine, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--state-machine-path", str(state_machine_path),
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    assert (generator_output_dir / "tools" / "signal_bridge.py").is_file()


def test_generator_creates_bat_files(generator_output_dir, sample_state_machine, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--state-machine-path", str(state_machine_path),
            "--stage-bats", "start_review,approved,rejected",
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    tools_dir = generator_output_dir / "tools"
    assert (tools_dir / "Online.bat").is_file()
    assert (tools_dir / "Done.bat").is_file()
    assert (tools_dir / "Blocked.bat").is_file()
    assert (tools_dir / "Failed.bat").is_file()
    assert (tools_dir / "StartStartReview.bat").is_file()
    assert (tools_dir / "StartApproved.bat").is_file()
    assert (tools_dir / "StartRejected.bat").is_file()


def test_generator_loads_state_machine(generator_output_dir, sample_state_machine, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--state-machine-path", str(state_machine_path),
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    generated_state_machine = json.loads((generator_output_dir / "state" / "state_machine.json").read_text(encoding="utf-8"))
    assert generated_state_machine == sample_state_machine


def test_generator_injects_bootstrap(generator_output_dir, sample_state_machine, sample_bootstrap, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    bootstrap_path = tmp_path / "BOOTSTRAP.txt"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")
    bootstrap_path.write_text(sample_bootstrap, encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--bootstrap-path", str(bootstrap_path),
            "--state-machine-path", str(state_machine_path),
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    bootstrap_content = (generator_output_dir / "tools" / "BOOTSTRAP.txt").read_text(encoding="utf-8")
    assert sample_bootstrap in bootstrap_content
    assert "review" in bootstrap_content


def test_generated_core_imports(generator_output_dir, sample_state_machine, tmp_path):
    template_dir = Path(__file__).parent.parent
    state_machine_path = tmp_path / "state_machine.json"
    state_machine_path.write_text(json.dumps(sample_state_machine, ensure_ascii=False), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(template_dir / "runtime_template_generator.py"),
            "--pool-name", "review",
            "--slot-prefix", "reviewer",
            "--slot-count", "2",
            "--state-machine-path", str(state_machine_path),
            "--output-dir", str(generator_output_dir),
        ],
        check=True,
    )

    subprocess.run(
        [
            sys.executable,
            "-c",
            "from core import file_queue, json_store, pool_state_templates, launch_manager, windows_process; print('OK')",
        ],
        cwd=generator_output_dir,
        check=True,
    )
