from __future__ import annotations

import argparse
import codecs
import copy
from contextvars import ContextVar
import json
import os
import readline
import re
import shlex
import shutil
import subprocess
import sys
import signal
import threading
import time
import tempfile
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .activity import Activity, capture_native, dashboard
from .file_diff import BASELINE, snapshot, file_diff, diff_snapshots, is_tool_artifact
from .progress import LocalProgress, ElapsedTimer
from . import ui
from . import screen


STATE_DIR_NAME = ".agentdock"
LIVE_OUTPUT = ContextVar("live_output", default=False)
SESSION_MODELS = ContextVar("session_models", default=None)
DEFAULT_CONFIG: dict[str, Any] = {
    "version": 2,
    "qwen_model": "ollama_chat/qwen3-coder:30b-a3b-q4_K_M",
    "max_repair_attempts": 4,
    "codex_planner_model": None,
    "codex_reviewer_model": None,
    "gradle_command": None,
    "verification_command": None,
    "final_codex_review": True,
    "ollama_base_url": "http://127.0.0.1:11434",
    "default_chat_agent": "local",
    "chat_mode": "chat",
    "output_mode": "compact",
    "theme": "violet",
    "stage_models": {"planning": None, "coding": None, "review": None},
    "agents": {
        "codex": {
            "backend": "codex",
            "auth": "subscription",
            "model": None,
            "role": "chat",
            "lifetime": "invocation",
            "timeout_seconds": 900,
        },
        "claude": {
            "backend": "claude",
            "auth": "subscription",
            "model": None,
            "role": "chat",
            "lifetime": "invocation",
            "timeout_seconds": 900,
        },
        "local": {
            "backend": "aider_ollama",
            "auth": "local",
            "model": "ollama_chat/qwen3-coder:30b-a3b-q4_K_M",
            "role": "chat",
            "lifetime": "invocation",
            "timeout_seconds": 900,
        },
    },
    "workflow": {
        "planner_agent": "codex",
        "worker_agent": "local",
        "reviewer_agent": "codex",
        "debugger_agent": "codex",
    },
}

AGENT_BACKENDS = {"codex", "claude", "aider_ollama"}
AGENT_AUTH = {"subscription", "local", "api_key"}
AGENT_LIFETIMES = {"invocation"}
AGENT_ROLES = {"chat", "planner", "worker", "reviewer", "debugger"}
ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "magenta": "\033[35m",
    "blue": "\033[34m",
}


class WorkflowError(RuntimeError):
    pass


def status(label: str, message: str) -> None:
    ui.event("◌", label, message)


def success(message: str) -> None:
    ui.event("✓", "", message)


def failure(message: str) -> None:
    ui.event("✗", "", message)


def warning(message: str) -> None:
    ui.event("⚠", "", message)


def use_color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def color(text: str, name: str) -> str:
    if not use_color():
        return text
    return f"{ANSI.get(name, '')}{text}{ANSI['reset']}"


def print_rule(label: str = "") -> None:
    width = shutil.get_terminal_size((80, 20)).columns
    if label:
        text = f" {label} "
        left = max((width - len(text)) // 2, 1)
        right = max(width - left - len(text), 1)
        print(color(("─" * left) + text + ("─" * right), "dim"))
    else:
        print(color("─" * width, "dim"))


def find_repo(start: Path, *, require_git: bool = True) -> Path:
    if not shutil.which("git") and not require_git:
        return start.resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        if not require_git:
            return start.resolve()
        raise WorkflowError("Run agentdock inside a Git repository.")
    return Path(result.stdout.strip()).resolve()


def state_path(repo: Path, name: str) -> Path:
    return repo / STATE_DIR_NAME / name


def ensure_state(repo: Path) -> Path:
    directory = repo / STATE_DIR_NAME
    directory.mkdir(exist_ok=True)
    config_path = directory / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return directory


def save_config(repo: Path, config: dict[str, Any]) -> None:
    state_path(repo, "config.json").write_text(json.dumps(config, indent=2) + "\n")


def agent_model(config: dict[str, Any], agent_name: str, fallback: Optional[str] = None) -> Optional[str]:
    agent = config["agents"][agent_name]
    return agent.get("model") or fallback


def workflow_agent(config: dict[str, Any], key: str) -> str:
    return str(config["workflow"][key])


def agent_label(config: dict[str, Any], agent_name: str) -> str:
    agent = config["agents"][agent_name]
    return str(agent.get("backend") or agent_name)


def validate_agent_config(name: str, agent: Any) -> dict[str, Any]:
    if not isinstance(agent, dict):
        raise WorkflowError(f"agents.{name} must be a JSON object.")
    config = {
        "backend": agent.get("backend"),
        "auth": agent.get("auth", "subscription"),
        "model": agent.get("model"),
        "role": agent.get("role", "chat"),
        "lifetime": agent.get("lifetime", "invocation"),
        "timeout_seconds": agent.get("timeout_seconds", 900),
    }
    unknown = sorted(set(agent) - set(config))
    if unknown:
        raise WorkflowError(f"Unknown agents.{name} key(s): {', '.join(unknown)}")
    if config["backend"] not in AGENT_BACKENDS:
        raise WorkflowError(f"agents.{name}.backend must be one of: {', '.join(sorted(AGENT_BACKENDS))}.")
    if config["auth"] not in AGENT_AUTH:
        raise WorkflowError(f"agents.{name}.auth must be one of: {', '.join(sorted(AGENT_AUTH))}.")
    if config["role"] not in AGENT_ROLES:
        raise WorkflowError(f"agents.{name}.role must be one of: {', '.join(sorted(AGENT_ROLES))}.")
    if config["lifetime"] not in AGENT_LIFETIMES:
        raise WorkflowError("Only invocation agent lifetime is supported.")
    if config["model"] is not None and (not isinstance(config["model"], str) or not config["model"].strip()):
        raise WorkflowError(f"agents.{name}.model must be null or a non-empty string.")
    if isinstance(config["timeout_seconds"], bool) or not isinstance(config["timeout_seconds"], int):
        raise WorkflowError(f"agents.{name}.timeout_seconds must be an integer.")
    if config["timeout_seconds"] <= 0:
        raise WorkflowError(f"agents.{name}.timeout_seconds must be greater than zero.")
    return config


def validate_agents(config: dict[str, Any]) -> None:
    if config.get("theme", "violet") not in ui.THEMES:
        raise WorkflowError("theme must be violet, amber or mono.")
    if config.get("output_mode", "compact") not in {"compact", "raw"}:
        raise WorkflowError("output_mode must be compact or raw.")
    if config.get("chat_mode", "chat") not in {"chat", "build"}:
        raise WorkflowError("chat_mode must be chat or build.")
    stage_models = config.get("stage_models", {})
    if not isinstance(stage_models, dict) or set(stage_models) - {"planning", "coding", "review"}:
        raise WorkflowError("stage_models must contain planning, coding and/or review model overrides.")
    for model in stage_models.values():
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise WorkflowError("Stage models must be non-empty model IDs or null to inherit.")
    agents = config.get("agents")
    if not isinstance(agents, dict) or not agents:
        raise WorkflowError("agents must be a non-empty JSON object.")
    normalized: dict[str, dict[str, Any]] = {}
    for name, agent in agents.items():
        if not isinstance(name, str) or not name.strip():
            raise WorkflowError("agent names must be non-empty strings.")
        normalized[name] = validate_agent_config(name, agent)
    config["agents"] = normalized

    workflow_config = config.get("workflow")
    if not isinstance(workflow_config, dict):
        raise WorkflowError("workflow must be a JSON object.")
    required = {"planner_agent", "worker_agent", "reviewer_agent", "debugger_agent"}
    unknown = sorted(set(workflow_config) - required)
    if unknown:
        raise WorkflowError(f"Unknown workflow key(s): {', '.join(unknown)}")
    for key in sorted(required):
        value = workflow_config.get(key)
        if not isinstance(value, str) or value not in normalized:
            raise WorkflowError(f"workflow.{key} must name a configured agent.")

    default_agent = config.get("default_chat_agent")
    if not isinstance(default_agent, str) or default_agent not in normalized:
        raise WorkflowError("default_chat_agent must name a configured agent.")


def load_config(repo: Path) -> dict[str, Any]:
    config_path = state_path(repo, "config.json")
    try:
        user_config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Invalid {config_path}: {exc}") from exc
    if not isinstance(user_config, dict):
        raise WorkflowError(f"{config_path} must contain a JSON object.")
    unknown = sorted(set(user_config) - set(DEFAULT_CONFIG))
    if unknown:
        raise WorkflowError(f"Unknown config key(s): {', '.join(unknown)}")
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(user_config)
    if config.get("version") is None:
        config["version"] = 2
    if config.get("version") != 2:
        raise WorkflowError("Only config version 2 is supported.")
    if isinstance(config["max_repair_attempts"], bool) or not isinstance(config["max_repair_attempts"], int) or config["max_repair_attempts"] < 0:
        raise WorkflowError("max_repair_attempts must be a non-negative integer.")
    if not isinstance(config["final_codex_review"], bool):
        raise WorkflowError("final_codex_review must be true or false.")
    for key in ("qwen_model", "ollama_base_url"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise WorkflowError(f"{key} must be a non-empty string.")
    for key in ("codex_planner_model", "codex_reviewer_model", "gradle_command", "verification_command"):
        if config[key] is not None and (not isinstance(config[key], str) or not config[key].strip()):
            raise WorkflowError(f"{key} must be null or a non-empty string.")
    validate_agents(config)
    return config


def ollama_model_name(configured_model: str) -> str:
    return configured_model.split("/", 1)[1] if configured_model.startswith("ollama_chat/") else configured_model


def fetch_ollama_models(base_url: str) -> list[str]:
    url = base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Ollama is not reachable at {base_url}: {exc}") from exc
    return [entry.get("name", "") for entry in payload.get("models", [])]


def track_session_model(base: str, model: str) -> None:
    session = SESSION_MODELS.get()
    if session is None or urllib.parse.urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}:
        return
    canonical = lambda value: value if ":" in value.rsplit("/", 1)[-1] else value + ":latest"
    key = (base, canonical(model))
    if key in session:
        return
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=5) as response:
            payload = json.load(response)
        loaded = {canonical(entry["name"]) for entry in payload["models"]}
        session[key] = canonical(model) not in loaded
    except (OSError, ValueError, KeyError, TypeError):
        # Unknown ownership: do not unload someone else's model later.
        session[key] = False
        warning("Could not check running Ollama models; automatic unload disabled for this model")


def cleanup_session_models() -> None:
    session = SESSION_MODELS.get()
    if not session:
        return
    for (base, model), owned in list(session.items()):
        if not owned:
            continue
        status("Ollama", f"Unloading session model: {model}...")
        request = urllib.request.Request(base + "/api/generate", data=json.dumps({
            "model": model, "keep_alive": 0, "stream": False,
        }).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
            if payload.get("error") or not payload.get("done"):
                raise ValueError(payload.get("error", "incomplete response"))
            success(f"Unloaded {model}")
        except (OSError, ValueError, TypeError) as exc:
            warning(f"Could not unload {model}: {exc}. Run ollama stop {model} if needed.")
    session.clear()


def ensure_ollama_ready(repo: Path, config: dict[str, Any], model: str, *, warm: bool = True) -> None:
    base = str(config["ollama_base_url"]).rstrip("/")
    selected = ollama_runtime_model(model)
    try:
        models = fetch_ollama_models(base)
    except WorkflowError as exc:
        url = urllib.parse.urlsplit(base)
        reason = getattr(exc.__cause__, "reason", None)
        can_start = (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
                     and url.path in {"", "/"} and not url.username and not url.query and not url.fragment)
        if not can_start or not isinstance(reason, ConnectionRefusedError):
            raise WorkflowError(f"{exc}. Auto-start requires a local HTTP endpoint with a refused connection.") from exc
        executable = shutil.which("ollama")
        if not executable:
            raise WorkflowError("Ollama is not installed or not on PATH. Install Ollama, then retry.") from exc
        status("Ollama", "Starting local server...")
        log_path = ensure_state(repo) / "ollama-server.log"
        env = dict(os.environ, OLLAMA_HOST=base)
        with log_path.open("ab") as log:
            try:
                process = subprocess.Popen([executable, "serve"], stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, env=env,
                                           start_new_session=True, cwd=repo)
            except OSError as error:
                raise WorkflowError(f"Could not start Ollama: {error}") from error
        deadline = time.monotonic() + 30
        try:
            while True:
                try:
                    models = fetch_ollama_models(base)
                    break
                except WorkflowError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise WorkflowError(f"Ollama did not start. See {log_path}")
                    time.sleep(.25)
        except BaseException:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
        # The server is shared and stays up after chat exits; reap it if it exits first.
        threading.Thread(target=process.wait, daemon=True).start()
        success("Ollama server ready (left running for reuse)")
    canonical = lambda value: value if ":" in value.rsplit("/", 1)[-1] else value + ":latest"
    if canonical(selected) not in {canonical(name) for name in models}:
        command = shlex.join(["ollama", "pull", selected])
        raise WorkflowError(f"Model {selected} is not installed at {base}. Download explicitly with {command} (using OLLAMA_HOST={base}), then retry.")
    if not warm:
        return
    track_session_model(base, selected)
    status("Ollama", f"Loading {selected} (first load can take a while)...")
    request = urllib.request.Request(base + "/api/generate", data=json.dumps({
        "model": selected, "prompt": "", "stream": False, "keep_alive": "5m",
    }).encode(), headers={"Content-Type": "application/json"})
    try:
        with ElapsedTimer(sys.stdout, "Ollama loading"):
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
            if payload.get("error") or not payload.get("done"):
                raise WorkflowError(f"Ollama could not load {selected}: {payload.get('error', 'incomplete response')}")
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise WorkflowError(f"Could not load Ollama model {selected}: {exc}") from exc
    success(f"Local model ready: {selected}")


def aider_executable(repo: Path) -> Optional[str]:
    existing = shutil.which("aider")
    managed = repo / STATE_DIR_NAME / "tools" / "bin" / "aider"
    return existing or (str(managed) if managed.is_file() and os.access(managed, os.X_OK) else None)


def ensure_aider(repo: Path) -> str:
    existing = aider_executable(repo)
    if existing:
        return existing
    state = ensure_state(repo)
    root = state / "tools"
    root.mkdir(exist_ok=True)
    log = state / "aider-install.log"
    env = dict(os.environ, UV_TOOL_DIR=str(root / "environments"),
               UV_TOOL_BIN_DIR=str(root / "bin"), UV_CACHE_DIR=str(root / "cache"),
               UV_PYTHON_INSTALL_DIR=str(root / "python"))

    def install(argv: list[str]) -> None:
        result = run_logged(argv, repo, log, env=env, timeout=900, agent_name="Aider setup")
        if result.returncode:
            raise WorkflowError(f"Aider setup failed. See {log}: {one_line_error(result.stdout, 'installer failed')}")

    status("Aider", "Installing isolated coding tools; downloading dependencies may take several minutes...")
    uv = shutil.which("uv")
    if not uv:
        bootstrap = root / "bootstrap"
        install([sys.executable, "-m", "venv", str(bootstrap)])
        install([str(bootstrap / "bin" / "python"), "-m", "pip", "install", "uv"])
        uv = str(bootstrap / "bin" / "uv")
    install([uv, "tool", "install", "--python", "python3.12", "--with", "pip", "aider-chat"])
    executable = aider_executable(repo)
    if not executable:
        raise WorkflowError(f"Aider installation finished but its executable is missing. See {log}")
    success("Aider ready; this installation will be reused")
    return executable


def doctor(repo: Path, config: dict[str, Any], require_gradle: bool = True) -> bool:
    stages = ["planner_agent", "debugger_agent"]
    if config["final_codex_review"]:
        stages.append("reviewer_agent")
    checks = sorted({"ollama", "aider"} | {
        config["agents"][config["workflow"][stage]]["backend"] for stage in stages
    })
    okay = True
    for name in checks:
        path = aider_executable(repo) if name == "aider" else shutil.which(name)
        if path:
            success(f"{name}: {path}")
        else:
            failure(f"{name}: not found")
            okay = False

    try:
        models = fetch_ollama_models(str(config["ollama_base_url"]))
        success(f"Ollama reachable at {config['ollama_base_url']}")
        wanted = ollama_model_name(str(agent_model(config, config["workflow"]["worker_agent"], config["qwen_model"])))
        if wanted in models:
            success(f"Ollama model installed: {wanted}")
        else:
            failure(f"Ollama model not installed: {wanted}")
            okay = False
    except WorkflowError as exc:
        failure(str(exc))
        okay = False
    return okay


def run_logged(
    argv: Sequence[str],
    repo: Path,
    log_path: Path,
    *,
    input_text: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    timeout: Optional[int] = None,
    agent_name: Optional[str] = None,
    stream_output: Optional[bool] = None,
    progress_label: Optional[str] = None,
    progress_narration: bool = True,
) -> subprocess.CompletedProcess[str]:
    show_output = LIVE_OUTPUT.get() if stream_output is None else stream_output
    terminal = sys.stdout
    timer = ElapsedTimer(terminal, progress_label or agent_name) if progress_label or agent_name else None
    emit = timer.write if timer else terminal.write
    progress = LocalProgress(lambda message: emit(f"[{progress_label}] {message}\n")) if progress_label and progress_narration and not show_output else None
    activity = Activity(log_path.parent, agent_name or Path(argv[0]).name, Path(argv[0]).name)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {shlex.join(argv)}\n")
        log.flush()
        try:
            process = subprocess.Popen(
                list(argv),
                cwd=repo,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            activity.write(str(exc).encode())
            activity.finish("failed")
            raise WorkflowError(f"Could not start {argv[0]}: {exc}") from exc
        chunks: list[str] = []
        errors: list[Exception] = []

        def drain() -> None:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                while True:
                    block = os.read(process.stdout.fileno(), 8192)
                    if not block:
                        break
                    activity.write(block)
                    decoded = decoder.decode(block)
                    chunks.append(decoded)
                    log.write(decoded)
                    log.flush()
                    if progress:
                        progress.feed(decoded)
                    if show_output:
                        emit(decoded)
                        terminal.flush()
                rest = decoder.decode(b"", final=True)
                chunks.append(rest)
                log.write(rest)
                log.flush()
                if progress:
                    progress.feed(rest)
                    progress.finish()
                if show_output:
                    emit(rest)
                    if chunks and not "".join(chunks).endswith("\n"):
                        emit("\n")
                    terminal.flush()
            except Exception as exc:
                errors.append(exc)

        def feed() -> None:
            if process.stdin is not None:
                try:
                    process.stdin.write((input_text or "").encode())
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()

        reader = threading.Thread(target=drain, daemon=True)
        writer = threading.Thread(target=feed, daemon=True)
        reader.start()
        writer.start()
        outcome = "failed"
        try:
            if timer:
                timer.start()
            process.wait(timeout=timeout)
            outcome = "completed" if process.returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            outcome = "timed out"
            raise WorkflowError(f"Timed out after {timeout}s: {shlex.join(argv)}") from exc
        except KeyboardInterrupt:
            outcome = "interrupted"
            raise
        finally:
            # Stop the invocation's descendants too, so inherited pipes cannot hang the reader.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            writer.join()
            reader.join()
            process.stdout.close()
            if timer:
                timer.stop("failed" if errors else outcome)
            activity.finish("failed" if errors else outcome, process.returncode)
        if errors:
            raise WorkflowError(f"Could not capture agent output: {errors[0]}")
    return subprocess.CompletedProcess(argv, process.returncode, "".join(chunks), None)


def codex_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("CODEX_") and key != "CODEX_HOME":
            env.pop(key, None)
    return env


def run_codex(
    repo: Path,
    prompt: str,
    destination: Path,
    model: Optional[str],
    log_path: Path,
    *,
    inspect_repo: bool,
    skip_git_repo_check: bool = False,
    agent_name: str = "codex",
) -> None:
    with tempfile.TemporaryDirectory(prefix="agentdock-codex-") as temporary:
        working_dir = repo if inspect_repo else Path(temporary)
        argv = [
            "codex",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--cd",
            str(working_dir),
            "--output-last-message",
            str(destination),
        ]
        if skip_git_repo_check or not inspect_repo:
            argv.append("--skip-git-repo-check")
        if not inspect_repo:
            argv.append("--ignore-rules")
        if model:
            argv.extend(["--model", model])
        argv.append("-")
        result = run_logged(argv, working_dir, log_path, input_text=prompt, env=codex_subprocess_env(),
                            agent_name=agent_name, progress_label=agent_name, progress_narration=False)
    if result.returncode or not destination.exists() or not destination.read_text().strip():
        detail = one_line_error(result.stdout, f"see {log_path}")
        raise WorkflowError(f"Codex failed: {detail}")


def is_git_repo(path: Path) -> bool:
    if not shutil.which("git"):
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def has_git_baseline(repo: Path) -> bool:
    if not shutil.which("git"):
        return False
    return subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def run_claude(
    repo: Path,
    prompt: str,
    destination: Path,
    model: Optional[str],
    log_path: Path,
    *,
    timeout: Optional[int] = None,
    agent_name: str = "claude",
) -> None:
    argv = ["claude", "-p", "--output-format", "text"]
    if model:
        argv.extend(["--model", model])
    result = run_logged(argv, repo, log_path, input_text=prompt, timeout=timeout,
                        agent_name=agent_name, progress_label=agent_name, progress_narration=False)
    if result.returncode or not result.stdout.strip():
        detail = one_line_error(result.stdout, f"see {log_path}")
        raise WorkflowError(f"Claude failed: {detail}")
    destination.write_text(result.stdout.strip() + "\n")


def run_paid_agent(
    repo: Path,
    config: dict[str, Any],
    agent_name: str,
    prompt: str,
    destination: Path,
    log_path: Path,
    *,
    inspect_repo: bool,
    fallback_model: Optional[str] = None,
) -> None:
    agent = config["agents"][agent_name]
    model = agent_model(config, agent_name, fallback_model)
    timeout = int(agent["timeout_seconds"])
    if agent["backend"] == "codex":
        run_codex(repo, prompt, destination, model, log_path, inspect_repo=inspect_repo, agent_name=agent_name, skip_git_repo_check=not is_git_repo(repo))
    elif agent["backend"] == "claude":
        run_claude(repo, prompt, destination, model, log_path, timeout=timeout, agent_name=agent_name)
    else:
        raise WorkflowError(f"Agent {agent_name} uses backend {agent['backend']}, not a paid review/planning backend.")


def ollama_runtime_model(model: str) -> str:
    if model.startswith("ollama_chat/"):
        return model.split("/", 1)[1]
    return model


def run_chat_agent(repo: Path, config: dict[str, Any], agent_name: str, message: str) -> str:
    state = ensure_state(repo)
    log_path = state / "chat.log"
    agent = config["agents"][agent_name]
    model = agent_model(config, agent_name)
    timeout = int(agent["timeout_seconds"])
    prompt = f"""You are agent `{agent_name}` in a terminal coding assistant.

Answer the user's message clearly and concisely. Do not edit files, run commands, commit, push,
reset, discard changes, or open pull requests. If the user asks for repository-changing work,
explain that they should use `/code` for interactive coding or `/run TASK` for the staged workflow.
Do not claim a specific underlying model identity: the configured model is
{model or 'provider default (not verified)'}. Local chat has no repository tools.

User message:
{message}
"""
    if agent["backend"] == "codex":
        with tempfile.TemporaryDirectory(prefix="agentdock-chat-") as temporary:
            destination = Path(temporary) / "response.md"
            run_codex(
                repo,
                prompt,
                destination,
                model,
                log_path,
                inspect_repo=True,
                skip_git_repo_check=not is_git_repo(repo),
                agent_name=agent_name,
            )
            return destination.read_text().strip()
    if agent["backend"] == "claude":
        with tempfile.TemporaryDirectory(prefix="agentdock-chat-") as temporary:
            destination = Path(temporary) / "response.md"
            run_claude(repo, prompt, destination, model, log_path, timeout=timeout, agent_name=agent_name)
            return destination.read_text().strip()
    if agent["backend"] == "aider_ollama":
        selected = ollama_runtime_model(str(model or config["qwen_model"]))
        ensure_ollama_ready(repo, config, selected)
        argv = ["ollama", "run", selected, prompt]
        env = dict(os.environ, OLLAMA_HOST=str(config["ollama_base_url"]))
        result = run_logged(argv, repo, log_path, timeout=timeout, agent_name=agent_name, env=env)
        if result.returncode:
            raise WorkflowError(f"Ollama chat failed; see {log_path}")
        return result.stdout.strip()
    raise WorkflowError(f"Unsupported backend for {agent_name}: {agent['backend']}")


def planner_prompt(task: str, project_files: Optional[list[str]] = None) -> str:
    inventory = ""
    if project_files is not None:
        inventory = "\nFiltered project text-file inventory (tooling excluded; up to 200 paths):\n" + ("\n".join(project_files[:200]) or "(No eligible application text files yet.)") + "\n"
    return f"""You are the PLANNER ONLY for a coding task in this repository.

You may inspect repository files and run read-only discovery commands. Do not edit, create,
delete, format, or otherwise change any repository file. Do not run commands that mutate the
working tree. Return only a detailed Markdown implementation plan.

Inspect application source only. Do not scan .agentdock/, .aider*, .venv/, node_modules/,
build/, dist/ or dependency caches. These are tooling, not project source.
Never use an unrestricted recursive listing (including rg --files --hidden).
For discovery use: rg --files -g '!.agentdock/**' -g '!.aider*' -g '!.venv/**'
-g '!node_modules/**' -g '!build/**' -g '!dist/**'
If no application files exist, plan a new project without exploring installed tooling.
{inventory}

Original task:
{task}

The plan must include:
- a concise repository/architecture assessment
- likely files to change, using exact repository-relative paths in backticks
- numbered implementation steps
- architecture and compatibility considerations
- edge cases
- tests to add or update
- acceptance criteria
- one appropriate verification command for this project's actual tools, if available

Put the verification command on its own line in exactly this form:
VERIFY_COMMAND: <command and arguments>
Choose a command appropriate to the project (for example npm test, python -m pytest,
or ./gradlew test). Do not assume Java or Gradle exists. Do not use shell operators.
If there is no meaningful automated check, use VERIFY_COMMAND: NONE and include
specific manual verification steps. Never invent a test command just to fill this field.
Use a single command with no pipes, redirects, command substitution, or command chaining.
Do not implement anything.
"""


def extract_plan_paths(plan: str, repo: Path, limit: int = 40) -> list[str]:
    repo = repo.resolve()
    candidates: list[str] = []
    for token in re.findall(r"`([^`\n]+)`", plan):
        value = token.strip().lstrip("./")
        if not value or is_tool_artifact(token.strip()) or any(char in value for char in "*?{}$|"):
            continue
        path = (repo / value).resolve()
        try:
            path.relative_to(repo)
        except ValueError:
            continue
        if path.is_file() and value not in candidates:
            candidates.append(value)
        if len(candidates) >= limit:
            break
    return candidates


def changed_files(repo: Path) -> list[str]:
    if not has_git_baseline(repo):
        current = snapshot(repo)
        baseline = BASELINE.get()
        if baseline is None:
            return []
        return sorted(name for name in current if current.get(name) != baseline.get(name))
    commands = [
        ["git", "diff", "--name-only", "HEAD", "--"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    files: list[str] = []
    for argv in commands:
        result = subprocess.run(argv, cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise WorkflowError(result.stderr.strip() or f"Failed: {shlex.join(argv)}")
        for name in result.stdout.splitlines():
            if name and not is_tool_artifact(name) and (repo / name).is_file() and name not in files:
                files.append(name)
    return files


def worker_edit_files(repo: Path, baseline_files: set[str], planned_files: Iterable[str]) -> list[str]:
    planned = set(planned_files)
    return [name for name in changed_files(repo) if name not in baseline_files or name in planned]


def write_worker_prompt(path: Path, stage: str, extra: str = "") -> None:
    if stage == "implement":
        body = """Implement the task described in the read-only TASK.md and PLAN.md files.
Inspect the supplied repository files and repo map, make the smallest complete code changes,
and add or update the planned tests. Follow the project's language and framework conventions.
Do not make unrelated changes. Do not commit, reset, discard, push, or open a pull request.
Do not merely describe code: edit the files. The orchestrator will run the planned verification separately.
"""
    elif stage == "repair":
        body = """The project verification failed. Diagnose the failure output below and edit the
repository to fix the task implementation or its tests. Make focused changes only. Do not commit,
reset, discard, push, or open a pull request. Do not merely describe the fix: apply it.

FAILURE OUTPUT:
""" + extra
    elif stage == "debug":
        body = """Local repair attempts were exhausted. Apply the Codex debugging advice below,
using your own judgment and the repository context. Make focused edits only. Do not commit, reset,
discard, push, or open a pull request.

CODEX DEBUGGING ADVICE:
""" + extra
    else:
        body = """Read the review findings in the read-only REVIEW.md file and fix every actionable
finding that is correct and in scope. Add missing tests where requested. Leave non-actionable notes
alone. Do not commit, reset, discard, push, or open a pull request. Apply edits, do not just report.
"""
    path.write_text(body.rstrip() + "\n")


def run_aider(
    repo: Path,
    config: dict[str, Any],
    prompt_file: Path,
    read_files: Iterable[Path],
    edit_files: Iterable[str],
    log_path: Path,
    *,
    agent_name: Optional[str] = None,
) -> None:
    model = str(config["qwen_model"])
    timeout: Optional[int] = None
    if agent_name:
        agent = config["agents"][agent_name]
        if agent["backend"] != "aider_ollama":
            raise WorkflowError(f"Worker agent {agent_name} must use the aider_ollama backend.")
        model = str(agent.get("model") or config["qwen_model"])
        timeout = int(agent["timeout_seconds"])
    ensure_ollama_ready(repo, config, model)
    argv = [
        "aider",
        "--model",
        model,
        "--message-file",
        str(prompt_file),
        "--yes",
        "--no-auto-commits",
        "--no-dirty-commits",
        "--no-auto-lint",
        "--no-auto-test",
        "--stream",
        "--no-pretty",
        "--no-fancy-input",
        "--no-show-release-notes",
        "--no-check-update",
        "--chat-history-file", str(state_path(repo, "aider-chat-history.md")),
        "--input-history-file", str(state_path(repo, "aider-input-history.txt")),
    ]
    if not has_git_baseline(repo):
        argv.append("--no-git")
    argv[0] = ensure_aider(repo)
    for path in read_files:
        argv.extend(["--read", str(path)])
    argv.extend(name for name in edit_files if not is_tool_artifact(name))
    env = dict(os.environ)
    env["OLLAMA_API_BASE"] = str(config["ollama_base_url"])
    before_edit = snapshot(repo)
    try:
        result = run_logged(argv, repo, log_path, env=env, timeout=timeout,
                            agent_name=agent_name or "local", progress_label=agent_name or "local")
    finally:
        try:
            ui.show_diff(diff_snapshots(before_edit, snapshot(repo)), limit=120)
        except OSError as exc:
            warning(f"Could not display file changes: {exc}")
    if result.returncode:
        raise WorkflowError(f"Aider failed; see {log_path}")


def parse_gradle_command(plan: str, configured: Optional[str]) -> list[str]:
    command = configured
    if not command:
        match = re.search(r"(?m)^GRADLE_COMMAND:\s*(.+?)\s*$", plan)
        command = match.group(1) if match else "./gradlew test"
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise WorkflowError(f"Invalid Gradle command: {exc}") from exc
    if not argv or argv[0] not in {"./gradlew", "gradle"}:
        raise WorkflowError("Gradle command must start with ./gradlew or gradle.")
    forbidden = {"|", "||", "&&", ";", ">", ">>", "<"}
    if forbidden.intersection(argv):
        raise WorkflowError("Gradle command cannot contain shell operators.")
    return argv


def run_gradle(repo: Path, argv: Sequence[str], output_path: Path, log_path: Path) -> bool:
    result = run_logged(argv, repo, log_path)
    output_path.write_text(result.stdout)
    return result.returncode == 0


def parse_verification_command(plan: str, config: dict[str, Any]) -> list[str]:
    command = config.get("verification_command") or config.get("gradle_command")
    if not command:
        match = re.search(r"(?m)^(?:VERIFY_COMMAND|GRADLE_COMMAND):\s*([^\r\n]+)$", plan)
        if not match:
            raise WorkflowError("Plan is missing VERIFY_COMMAND. Specify a command or NONE in verification_command.")
        command = match.group(1).strip()
    if command.upper() == "NONE":
        return []
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise WorkflowError(f"Invalid verification command: {exc}") from exc
    if not argv or any(token in {"|", "||", "&&", ";", ">", ">>", "<", "&"} for token in argv):
        raise WorkflowError("Verification must be a single command without shell operators.")
    return argv


def run_verification(repo: Path, argv: Sequence[str], output_path: Path, log_path: Path) -> bool:
    if not argv:
        output_path.write_text("NOT RUN: No automated verification command. Manual verification required; see PLAN.md.\n")
        warning("Automated verification not run; manual verification required (see PLAN.md)")
        return True
    status("Verify", f"Running {shlex.join(argv)}")
    return run_gradle(repo, argv, output_path, log_path)


def make_diff(repo: Path) -> str:
    if not has_git_baseline(repo):
        return file_diff(repo)
    result = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--", ".",
         ":(exclude)**/.agentdock/**", ":(exclude).agentdock/**",
         ":(exclude)**/.aider*", ":(exclude).aider*", ":(exclude)**/.DS_Store", ":(exclude).DS_Store"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise WorkflowError(result.stderr.strip() or "git diff failed")
    pieces = [result.stdout]
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if untracked.returncode:
        raise WorkflowError(untracked.stderr.strip() or "Unable to list untracked files")
    for name in untracked.stdout.splitlines():
        if not name or is_tool_artifact(name) or not (repo / name).is_file():
            continue
        patch = subprocess.run(
            ["git", "diff", "--binary", "--no-index", "--", "/dev/null", name],
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if patch.returncode not in (0, 1):
            raise WorkflowError(patch.stderr.strip() or f"Unable to diff untracked file {name}")
        pieces.append(patch.stdout)
    return "".join(pieces)


def tail(text: str, characters: int = 16000) -> str:
    return text if len(text) <= characters else "[earlier output omitted]\n" + text[-characters:]


def one_line_error(output: str, fallback: str) -> str:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return fallback


def review_prompt(task: str, plan: str, diff: str, test_output: str) -> str:
    return f"""You are the REVIEWER ONLY. Do not inspect the repository, run commands, or change files.
Review only the supplied task, plan, patch, and verification output. NOT RUN means no tests passed.
Look for correctness problems,
missed requirements, regressions, architecture issues, security issues, and missing tests.
Return concise Markdown findings ordered by severity. Each actionable finding must name the relevant
file and a concrete fix. If there are no actionable findings, say exactly: No actionable findings.

# Original task
{task}

# Implementation plan
{plan}

# Git diff
{diff or '(empty diff)'}

# Verification output (tail)
{tail(test_output)}
"""


def debug_prompt(task: str, plan: str, diff: str, test_output: str) -> str:
    return f"""You are a debugging advisor only. Do not change files. Based only on the supplied
task, plan, current patch, and failing verification output, identify the likely root cause and give precise,
minimal instructions for the local Qwen worker. Do not request more context unless unavoidable.

# Task
{task}
# Plan
{plan}
# Current diff
{diff or '(empty diff)'}
# Failing test output (tail)
{tail(test_output)}
"""


STAGE_KEYS = {"planning": "planner_agent", "coding": "worker_agent", "review": "reviewer_agent"}


def resolved_workflow(config: dict[str, Any]) -> dict[str, Any]:
    resolved = copy.deepcopy(config)
    for stage, key in STAGE_KEYS.items():
        name = config["workflow"][key]
        agent = config["agents"][name]
        allowed = {"aider_ollama"} if stage == "coding" else {"codex", "claude"}
        if agent["backend"] not in allowed:
            raise WorkflowError(f"{stage} agent must use {' or '.join(sorted(allowed))}.")
        override = config.get("stage_models", {}).get(stage)
        if override:
            alias = f"{stage}:{name}"
            resolved["agents"][alias] = dict(agent, model=override)
            resolved["workflow"][key] = alias
    # When escalation uses the planner, retain its stage model override too.
    if config["workflow"]["debugger_agent"] == config["workflow"]["planner_agent"]:
        resolved["workflow"]["debugger_agent"] = resolved["workflow"]["planner_agent"]
    return resolved


def print_workflow(config: dict[str, Any]) -> None:
    resolved = resolved_workflow(config)
    for stage, key in STAGE_KEYS.items():
        print(f"{stage}: {agent_display(resolved, resolved['workflow'][key])}")
    print(f"review: {'enabled' if config['final_codex_review'] else 'disabled'}; input mode: {config.get('chat_mode', 'chat')}")
    print("Plan → local implementation/tests/repairs → review → local fixes → final tests")


def setup_workflow(repo: Path, config: dict[str, Any]) -> None:
    candidate = copy.deepcopy(config)
    candidate.setdefault("stage_models", {})
    print("Choose an agent and optional model override for each stage. Ctrl-C cancels setup.")
    for stage, key in STAGE_KEYS.items():
        allowed = {"aider_ollama"} if stage == "coding" else {"codex", "claude"}
        choices = [name for name, agent in config["agents"].items() if agent["backend"] in allowed]
        current = config["workflow"][key]
        print(f"{stage} agents: {', '.join(choices)}")
        selected = input(f"{stage} agent [{current}]: ").strip() or current
        if selected not in choices:
            raise WorkflowError(f"Choose one of: {', '.join(choices)}. Use /create to add an agent first.")
        candidate["workflow"][key] = selected
        existing = config.get("stage_models", {}).get(stage)
        value = input(f"{stage} model [{existing or 'inherit agent model'}]; 'inherit' clears override: ").strip()
        model = existing if not value else (None if value == "inherit" else value)
        if stage == "coding" and model and not model.startswith("ollama_chat/"):
            model = "ollama_chat/" + model
        candidate["stage_models"][stage] = model
    candidate["workflow"]["debugger_agent"] = candidate["workflow"]["planner_agent"]
    candidate["final_codex_review"] = True
    mode = input("Treat ordinary messages as build tasks? [y/N]: ").strip().lower()
    candidate["chat_mode"] = "build" if mode in {"y", "yes"} else "chat"
    validate_agents(candidate)
    resolved_workflow(candidate)
    save_config(repo, candidate)
    config.clear()
    config.update(candidate)
    print_workflow(config)
    success("Workflow saved")


def workflow(repo: Path, task: str, config: dict[str, Any], skip_doctor: bool = False) -> None:
    token = BASELINE.set(None if has_git_baseline(repo) else snapshot(repo))
    output_token = LIVE_OUTPUT.set(config.get("output_mode", "compact") == "raw")
    try:
        _workflow(repo, task, config, skip_doctor)
    finally:
        BASELINE.reset(token)
        LIVE_OUTPUT.reset(output_token)


def _workflow(repo: Path, task: str, config: dict[str, Any], skip_doctor: bool = False) -> None:
    config = resolved_workflow(config)
    state = ensure_state(repo)
    task_path = state / "TASK.md"
    plan_path = state / "PLAN.md"
    worker_log = state / "worker.log"
    test_output = state / "test-output.txt"
    diff_path = state / "diff.patch"
    review_path = state / "REVIEW.md"
    final_output = state / "final-test-output.txt"
    prompt_path = state / ".worker-prompt.md"
    debug_path = state / ".DEBUG.md"
    planner_agent = workflow_agent(config, "planner_agent")
    worker_agent = workflow_agent(config, "worker_agent")
    reviewer_agent = workflow_agent(config, "reviewer_agent")
    debugger_agent = workflow_agent(config, "debugger_agent")

    if not skip_doctor:
        ensure_aider(repo)
        ensure_ollama_ready(repo, config, str(agent_model(config, worker_agent, config["qwen_model"])), warm=False)
    if not skip_doctor and not doctor(repo, config):
        raise WorkflowError("Preflight checks failed; no agent was started.")

    baseline_files = set(changed_files(repo))
    if baseline_files:
        warning("Existing working-tree changes detected; they will not be reset or discarded")

    task_path.write_text(f"# Task\n\n{task.strip()}\n")
    worker_log.write_text("")
    for path in (plan_path, test_output, diff_path, review_path, final_output):
        path.write_text("")

    try:
        status(agent_label(config, planner_agent), "Planning...")
        run_paid_agent(
            repo,
            config,
            planner_agent,
            planner_prompt(task, sorted(snapshot(repo))),
            plan_path,
            worker_log,
            inspect_repo=True,
            fallback_model=config["codex_planner_model"],
        )
        success("Plan generated")
        plan = plan_path.read_text()
        if not LIVE_OUTPUT.get():
            print_agent_response(planner_agent, plan)
        gradle_argv = parse_verification_command(plan, config)
        planned_files = extract_plan_paths(plan, repo)

        status(agent_label(config, worker_agent), "Implementing...")
        write_worker_prompt(prompt_path, "implement")
        run_aider(
            repo,
            config,
            prompt_path,
            [task_path, plan_path],
            planned_files,
            worker_log,
            agent_name=worker_agent,
        )
        success("Implementation completed")

        status("Verify", "Testing...")
        passed = run_verification(repo, gradle_argv, test_output, worker_log)
        if passed and gradle_argv:
            success("Tests passed")
        for attempt in range(1, config["max_repair_attempts"] + 1):
            if passed:
                break
            failure("Tests failed")
            status(agent_label(config, worker_agent), f"Repair attempt {attempt}...")
            write_worker_prompt(prompt_path, "repair", tail(test_output.read_text()))
            run_aider(
                repo,
                config,
                prompt_path,
                [task_path, plan_path, test_output],
                worker_edit_files(repo, baseline_files, planned_files),
                worker_log,
                agent_name=worker_agent,
            )
            success("Changes made")
            status("Verify", "Testing...")
            passed = run_verification(repo, gradle_argv, test_output, worker_log)
            if passed:
                success("Tests passed")

        if not passed:
            warning(f"Local repair attempts exhausted; escalating once to {debugger_agent}")
            diff = make_diff(repo)
            run_paid_agent(
                repo,
                config,
                debugger_agent,
                debug_prompt(task, plan, diff, test_output.read_text()),
                debug_path,
                worker_log,
                inspect_repo=False,
                fallback_model=config["codex_reviewer_model"],
            )
            status(agent_label(config, worker_agent), "Applying debugging advice...")
            write_worker_prompt(prompt_path, "debug", debug_path.read_text())
            run_aider(
                repo,
                config,
                prompt_path,
                [task_path, plan_path, test_output],
                worker_edit_files(repo, baseline_files, planned_files),
                worker_log,
                agent_name=worker_agent,
            )
            status("Verify", "Testing after escalation...")
            passed = run_verification(repo, gradle_argv, test_output, worker_log)
            debug_path.unlink(missing_ok=True)
            if not passed:
                raise WorkflowError(f"Tests still fail after escalation; see {test_output}")
            success("Tests passed")

        diff = make_diff(repo)
        diff_path.write_text(diff)

        if config["final_codex_review"]:
            status(agent_label(config, reviewer_agent), "Reviewing...")
            run_paid_agent(
                repo,
                config,
                reviewer_agent,
                review_prompt(task, plan, diff, test_output.read_text()),
                review_path,
                worker_log,
                inspect_repo=False,
                fallback_model=config["codex_reviewer_model"],
            )
            review = review_path.read_text().strip()
            if not LIVE_OUTPUT.get():
                print_agent_response(reviewer_agent, review)
            if review == "No actionable findings.":
                success("No actionable review findings")
            else:
                warning("Review findings generated")
                status(agent_label(config, worker_agent), "Applying review...")
                write_worker_prompt(prompt_path, "review")
                run_aider(
                    repo,
                    config,
                    prompt_path,
                    [task_path, plan_path, review_path],
                    worker_edit_files(repo, baseline_files, planned_files),
                    worker_log,
                    agent_name=worker_agent,
                )
                updated_diff = make_diff(repo)
                if updated_diff == diff:
                    raise WorkflowError("Review-fix agent made no project changes. Findings remain unresolved; see REVIEW.md and worker.log.")
                success("Review-fix edits applied; findings have not been re-reviewed")
        else:
            review_path.write_text("Codex review disabled in config.json.\n")
            warning("Final Codex review disabled")

        status("Verify", "Final verification...")
        if not run_verification(repo, gradle_argv, final_output, worker_log):
            raise WorkflowError(f"Final verification failed; see {final_output}")
        if gradle_argv:
            success("Final verification passed")
        diff = make_diff(repo)
        diff_path.write_text(diff)
        if LIVE_OUTPUT.get():
            print("\n" + diff, end="" if diff.endswith("\n") else "\n")
        else:
            print(f"Diff saved to {diff_path}. Use /diff to inspect it.")
        print("DONE", flush=True)
    finally:
        prompt_path.unlink(missing_ok=True)
        debug_path.unlink(missing_ok=True)


def print_agents(config: dict[str, Any]) -> None:
    for name in sorted(config["agents"]):
        agent = config["agents"][name]
        marker = " (default)" if name == config["default_chat_agent"] else ""
        model = agent.get("model") or "(default)"
        print(f"{name}{marker}: backend={agent['backend']} role={agent['role']} model={model}")


def show_agent(config: dict[str, Any], name: str) -> None:
    if name not in config["agents"]:
        raise WorkflowError(f"Unknown agent: {name}")
    print(json.dumps(config["agents"][name], indent=2))


def add_agent(repo: Path, config: dict[str, Any], args: argparse.Namespace) -> None:
    name = args.name.strip()
    if not name:
        raise WorkflowError("Agent name cannot be empty.")
    if name in config["agents"] and not args.replace:
        raise WorkflowError(f"Agent already exists: {name}. Use --replace to overwrite it.")
    agent = {
        "backend": args.backend,
        "auth": args.auth,
        "model": args.model,
        "role": args.role,
        "lifetime": "invocation",
        "timeout_seconds": args.timeout_seconds,
    }
    config["agents"][name] = validate_agent_config(name, agent)
    if args.default:
        config["default_chat_agent"] = name
    validate_agents(config)
    save_config(repo, config)
    success(f"Saved agent: {name}")


def remove_agent(repo: Path, config: dict[str, Any], name: str) -> None:
    if name not in config["agents"]:
        raise WorkflowError(f"Unknown agent: {name}")
    if name in set(config["workflow"].values()):
        raise WorkflowError(f"Agent {name} is used by workflow config; update workflow before removing it.")
    if name == config["default_chat_agent"]:
        raise WorkflowError(f"Agent {name} is the default chat agent; change default_chat_agent before removing it.")
    del config["agents"][name]
    save_config(repo, config)
    success(f"Removed agent: {name}")


CHAT_COMMANDS = {
    "/theme": "Choose /theme violet, /theme amber or /theme mono",
    "/output": "Choose /output compact (results only) or /output raw (all provider logs)",
    "/workflow": "Show stage assignments; /workflow setup configures agents and models",
    "/mode": "Choose /mode build (automatic workflow) or /mode chat",
    "/build": "Plan, implement locally, review and verify: /build TASK",
    "/views": "Read-only agent panes (q returns); also: agentdock watch in another terminal",
    "/help": "Show chat commands",
    "/agents": "List configured agents",
    "/create": "Create an agent interactively",
    "/default": "Make the selected agent the startup default",
    "/code": "Start interactive coding with the selected agent",
    "/agent": "Switch agent: /agent codex",
    "/model": "Show or set current agent model: /model gpt-5.5",
    "/models": "Show configured agent models",
    "/native": "Open the selected agent's native CLI with its full commands",
    "/codex": "Open native Codex CLI",
    "/claude": "Open native Claude CLI",
    "/run": "Start the implementation workflow",
    "/status": "Show repo, agent, model, and state path",
    "/diff": "Print current git diff",
    "/clear": "Clear the terminal",
    "/new": "Start a fresh local chat context",
    "/exit": "Exit chat",
    "/quit": "Exit chat",
}
MODEL_SUGGESTIONS = {
    "codex": [],
    "claude": [],
    "aider_ollama": ["ollama_chat/qwen3-coder:30b-a3b-q4_K_M"],
}


def create_agent_interactively(repo: Path, config: dict[str, Any]) -> str:
    print("Create agent · Ctrl-C cancels · settings are saved for this project")
    name = input("Agent name: ").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise WorkflowError("Use letters, numbers, hyphens or underscores for the agent name.")
    if name in config["agents"]:
        raise WorkflowError(f"Agent already exists: {name}. Select it with /agent {name}.")
    backend = input("Backend [codex / claude / local]: ").strip().lower()
    backend = {"local": "aider_ollama"}.get(backend, backend)
    if backend not in AGENT_BACKENDS:
        raise WorkflowError("Choose codex, claude, or local.")
    default_model = config["qwen_model"] if backend == "aider_ollama" else None
    model = input(f"Model ID [Enter = {default_model or 'provider default'}]: ").strip() or default_model
    if backend == "aider_ollama" and model and not model.startswith("ollama_chat/"):
        model = "ollama_chat/" + model
    make_default = input("Use as startup agent? [y/N]: ").strip().lower() in {"y", "yes"}
    add_agent(repo, config, argparse.Namespace(
        name=name, backend=backend, auth="local" if backend == "aider_ollama" else "subscription",
        model=model, role="chat", timeout_seconds=900, default=make_default, replace=False,
    ))
    return name


def print_chat_help() -> None:
    print(ui.styled("\n  AgentDock · Command palette", "bold"))
    for command, description in CHAT_COMMANDS.items():
        print(f"  {command:<8} {description}")
    print()
    print("Provider commands:")
    print("  Use /native, /codex, or /claude to open the real CLI for full native slash commands and autocomplete.")


def agent_display(config: dict[str, Any], name: str) -> str:
    agent = config["agents"][name]
    model = agent.get("model") or "(default)"
    return f"{name} [{agent['backend']}, model={model}]"


def agent_prompt(config: dict[str, Any], name: str) -> str:
    if config.get("chat_mode") == "build":
        stages = config["workflow"]
        route = f"plan:{stages['planner_agent']} → code:{stages['worker_agent']}"
        if config["final_codex_review"]:
            route += f" → review:{stages['reviewer_agent']}"
        prompt = ui.styled("  BUILD", "accent") + ui.styled(f"  {route}", "muted") + ui.styled("\n  ❯ ")
        return re.sub(r"(\x1b\[[0-9;]*m)", r"\001\1\002", screen.paint_prompt(prompt))
    backend = config["agents"][name]["backend"]
    model = config["agents"][name].get("model") or "provider default"
    prompt = ui.styled(f"  {name}") + ui.styled(f"  {model}", "muted") + ui.styled("\n  ❯ ")
    return re.sub(r"(\x1b\[[0-9;]*m)", r"\001\1\002", screen.paint_prompt(prompt))


def print_chat_header(repo: Path, config: dict[str, Any], agent_name: str) -> None:
    agents = []
    if config.get("chat_mode") == "build":
        resolved = resolved_workflow(config)
        for label, key in [("PLAN", "planner_agent"), ("CODE", "worker_agent"), ("REVIEW", "reviewer_agent")]:
            name = resolved["workflow"][key]
            agent = resolved["agents"][name]
            model = str(agent.get("model") or "provider default").removeprefix("ollama_chat/")
            agents.append((label, name, model) if label != "REVIEW" or config["final_codex_review"] else (label, "disabled", ""))
    else:
        agent = config["agents"][agent_name]
        agents.append(("CHAT", agent_name, str(agent.get("model") or "provider default").removeprefix("ollama_chat/")))
    ui.welcome(str(repo), config.get("chat_mode", "chat"), config.get("output_mode", "compact"), agents)


def print_agent_response(agent_name: str, text: str) -> None:
    ui.response(agent_name, text)


def print_models(config: dict[str, Any]) -> None:
    for name in sorted(config["agents"]):
        marker = " *" if name == config["default_chat_agent"] else ""
        print(f"{agent_display(config, name)}{marker}")


def print_model_help(config: dict[str, Any], agent_name: str) -> None:
    agent = config["agents"][agent_name]
    current = agent.get("model") or "(default)"
    suggestions = ", ".join(MODEL_SUGGESTIONS.get(str(agent["backend"]), [])) or "(none)"
    print(f"current model for {agent_name}: {current}")
    print("usage:")
    print("  /model MODEL_NAME")
    print("  /model set MODEL_NAME")
    print("  /model reset")
    print(f"suggestions for {agent['backend']}: {suggestions}")


def set_agent_model(repo: Path, config: dict[str, Any], agent_name: str, value: str, *, announce: bool = True) -> None:
    requested = value.strip()
    if requested.startswith("set "):
        requested = requested.split(None, 1)[1].strip()
    if requested in {"reset", "default", "none"}:
        requested = ""
    config["agents"][agent_name]["model"] = requested or None
    validate_agents(config)
    save_config(repo, config)
    if announce:
        success(f"{agent_name} model set to {config['agents'][agent_name].get('model') or '(default)'}")


def configure_readline(config: dict[str, Any]) -> None:
    words = sorted(set(CHAT_COMMANDS) | {f"/agent {name}" for name in config["agents"]})
    words.extend(f"/model {agent['model']}" for agent in config["agents"].values() if agent.get("model"))
    for suggestions in MODEL_SUGGESTIONS.values():
        words.extend(f"/model {model}" for model in suggestions)
        words.extend(f"/model set {model}" for model in suggestions)
    words.extend(["/model reset", "/model default"])
    matches: list[str] = []

    def complete(text: str, state: int) -> Optional[str]:
        nonlocal matches
        if state == 0:
            buffer = readline.get_line_buffer()
            if buffer.startswith("/agent "):
                prefix = buffer[len('/agent '):]
                matches = [name for name in sorted(config["agents"]) if name.startswith(prefix)]
            elif buffer.startswith("/model "):
                prefix = buffer[len('/model '):]
                configured = sorted(
                    str(agent["model"]) for agent in config["agents"].values() if agent.get("model")
                )
                matches = [model for model in sorted(set(configured + ["reset", "default"])) if model.startswith(prefix)]
            else:
                matches = [word for word in words if word.startswith(text)]
        try:
            value = matches[state]
        except IndexError:
            return None
        return value + (" " if value.startswith("/") else "")

    readline.set_completer(complete)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("bind ^I rl_complete" if "libedit" in (readline.__doc__ or "") else "tab: complete")


def native_agent_argv(repo: Path, config: dict[str, Any], agent_name: str) -> list[str]:
    agent = config["agents"][agent_name]
    model = agent.get("model")
    if agent["backend"] == "codex":
        argv = ["codex", "--cd", str(repo)]
        if model:
            argv.extend(["--model", str(model)])
        return argv
    if agent["backend"] == "claude":
        argv = ["claude"]
        if model:
            argv.extend(["--model", str(model)])
        return argv
    if agent["backend"] == "aider_ollama":
        selected = str(model or config["qwen_model"])
        if not selected.startswith("ollama_chat/"):
            selected = "ollama_chat/" + selected
        return ["aider", "--model", selected, "--no-auto-commits", "--no-dirty-commits"]
    raise WorkflowError(f"Unsupported native backend for {agent_name}: {agent['backend']}")


def open_native_agent(repo: Path, config: dict[str, Any], agent_name: str) -> None:
    argv = native_agent_argv(repo, config, agent_name)
    local = config["agents"][agent_name]["backend"] == "aider_ollama"
    if local:
        argv[0] = ensure_aider(repo)
        if not has_git_baseline(repo):
            argv.append("--no-git")
    if not shutil.which(argv[0]):
        raise WorkflowError(f"{argv[0]} is not installed or not on PATH. Install it before using /code.")
    print(f"Opening native {agent_name}. Exit it to return to agentdock.")
    env = codex_subprocess_env() if argv[0] == "codex" else dict(os.environ)
    if local:
        ensure_ollama_ready(repo, config, str(agent_model(config, agent_name, config["qwen_model"])))
        env["OLLAMA_API_BASE"] = str(config["ollama_base_url"])
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            activity = Activity(repo / STATE_DIR_NAME, agent_name, argv[0])
            with screen.suspend():
                code = capture_native(argv, repo, env, activity)
        else:
            code = subprocess.run(argv, cwd=repo, env=env).returncode
    except OSError as exc:
        raise WorkflowError(f"Could not start {argv[0]}: {exc}") from exc
    if code:
        warning(f"Native {agent_name} exited with status {code}")


def chat_loop(repo: Path, config: dict[str, Any], initial_agent: Optional[str], first_message: Optional[str]) -> None:
    agent_name = initial_agent or str(config["default_chat_agent"])
    if agent_name not in config["agents"]:
        raise WorkflowError(f"Unknown agent: {agent_name}")
    histories: dict[str, list[dict[str, str]]] = {}

    def handle(message: str) -> None:
        nonlocal agent_name
        text = message.strip()
        if not text:
            return
        if text in {"/exit", "/quit"}:
            raise EOFError
        if text == "/help":
            print_chat_help()
            return
        if text == "/theme":
            print(f"Theme: {config.get('theme', 'violet')}. Choose /theme violet, /theme amber or /theme mono.")
            return
        if text.startswith("/theme "):
            requested = text.split(None, 1)[1]
            if requested not in ui.THEMES:
                raise WorkflowError("Choose violet, amber or mono.")
            config["theme"] = requested
            save_config(repo, config)
            ui.theme = requested
            print_chat_header(repo, config, agent_name)
            return
        if text == "/output":
            print(f"Output: {config.get('output_mode', 'compact')}. Use /output compact or /output raw.")
            return
        if text.startswith("/output "):
            mode = text.split(None, 1)[1]
            if mode not in {"compact", "raw"}:
                raise WorkflowError("Use /output compact or /output raw.")
            config["output_mode"] = mode
            save_config(repo, config)
            success(f"Output: {mode}")
            return
        if text == "/workflow":
            print_workflow(config)
            return
        if text == "/workflow setup":
            setup_workflow(repo, config)
            return
        if text == "/mode":
            print(f"Mode: {config.get('chat_mode', 'chat')}. Use /mode build or /mode chat.")
            return
        if text.startswith("/mode "):
            mode = text.split(None, 1)[1]
            if mode not in {"chat", "build"}:
                raise WorkflowError("Use /mode build or /mode chat.")
            config["chat_mode"] = mode
            save_config(repo, config)
            success(f"Input mode: {mode}")
            return
        if text == "/views":
            try:
                with screen.suspend():
                    dashboard(repo / STATE_DIR_NAME, list(config["agents"]))
            except ValueError as exc:
                raise WorkflowError(str(exc)) from exc
            return
        if text == "/agents":
            print_agents(config)
            return
        if text == "/create":
            agent_name = create_agent_interactively(repo, config)
            configure_readline(config)
            success(f"Using agent: {agent_display(config, agent_name)}")
            return
        if text == "/default":
            config["default_chat_agent"] = agent_name
            save_config(repo, config)
            success(f"Startup agent: {agent_name}")
            return
        if text == "/models":
            print_models(config)
            return
        if text == "/codex":
            open_native_agent(repo, config, "codex")
            return
        if text == "/claude":
            open_native_agent(repo, config, "claude")
            return
        if text.startswith("/agent "):
            requested = text.split(None, 1)[1].strip()
            if requested not in config["agents"]:
                raise WorkflowError(f"Unknown agent: {requested}")
            agent_name = requested
            success(f"Using agent: {agent_display(config, agent_name)}")
            return
        if text == "/model":
            print_model_help(config, agent_name)
            return
        if text.startswith("/model "):
            set_agent_model(repo, config, agent_name, text.split(None, 1)[1])
            configure_readline(config)
            return
        if text in {"/native", "/code"}:
            open_native_agent(repo, config, agent_name)
            return
        if text.startswith(("/run ", "/build ")):
            workflow(repo, text.split(None, 1)[1], config)
            return
        if text == "/status":
            print(f"repo: {repo}")
            if config.get("chat_mode") == "build":
                print_workflow(config)
            else:
                print(f"chat agent: {agent_display(config, agent_name)}")
            print(f"state: {repo / STATE_DIR_NAME}")
            return
        if text == "/diff":
            ui.show_diff(make_diff(repo))
            return
        if text == "/clear":
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            print_chat_header(repo, config, agent_name)
            return
        if text == "/new":
            histories.pop(agent_name, None)
            success(f"Cleared chat context for {agent_name}")
            return
        if text.startswith("/"):
            raise WorkflowError(f"Unknown command: {text}. Type /help.")
        if config.get("chat_mode") == "build":
            workflow(repo, text, config)
            return
        status(config["agents"][agent_name]["backend"], f"{agent_name} thinking...")
        history = histories.setdefault(agent_name, [])
        context = "Previous conversation (JSON):\n" + json.dumps(history) + "\n\nCurrent message:\n" + text if history else text
        response = run_chat_agent(repo, config, agent_name, context)
        history.extend([{"role": "user", "content": tail(text, 12000)}, {"role": "assistant", "content": tail(response, 12000)}])
        while len(history) > 2 and (len(history) > 12 or sum(len(item["content"]) for item in history) > 24000):
            del history[:2]
        print_agent_response(agent_name, response)

    if first_message:
        handle(first_message)
        return

    configure_readline(config)
    print_chat_header(repo, config, agent_name)
    while True:
        try:
            handle(input(agent_prompt(config, agent_name)))
        except EOFError:
            print("bye")
            return
        except KeyboardInterrupt:
            print("\nCancelled. /exit leaves chat.")
        except (WorkflowError, OSError, subprocess.SubprocessError) as exc:
            failure(str(exc))


def agentdock_main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"--agent", "--fullscreen", "--no-fullscreen"}:
        args = ["chat", *args]
    main(args, prog="agentdock")


def build_parser(prog: str = "agentdock") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Terminal chat and staged coding-agent orchestration.",
    )
    subparsers = parser.add_subparsers(dest="command")
    workflow_parser = subparsers.add_parser("workflow", help="show or configure stage agents and models")
    workflow_parser.add_argument("action", choices=["show", "setup"], nargs="?", default="show")
    watch_parser = subparsers.add_parser("watch", help="read-only live agent panes")
    watch_parser.add_argument("--once", action="store_true", help="print an activity snapshot and exit")

    run_parser = subparsers.add_parser("run", help="run the planner/worker/reviewer workflow")
    run_parser.add_argument("task", help="coding task to implement")
    run_parser.add_argument("--skip-doctor", action="store_true", help="skip preflight checks")

    chat_parser = subparsers.add_parser("chat", help="open terminal chat with a configured agent")
    chat_parser.add_argument("message", nargs="?", help="single message; omit for interactive chat")
    chat_parser.add_argument("--agent", help="agent name")
    chat_parser.add_argument("--fullscreen", action=argparse.BooleanOptionalAction, default=True,
                             help="temporary dark full-screen workspace (default for interactive chat; --no-fullscreen for panel-only)")

    doctor_parser = subparsers.add_parser("doctor", help="check dependencies and Ollama")
    doctor_parser.add_argument("--no-gradle", action="store_true", help="Gradle is no longer required")

    agents_parser = subparsers.add_parser("agents", help="manage configured agents")
    agent_subparsers = agents_parser.add_subparsers(dest="agents_command", required=True)
    agent_subparsers.add_parser("list", help="list agents")
    show_parser = agent_subparsers.add_parser("show", help="show one agent")
    show_parser.add_argument("name")
    add_parser = agent_subparsers.add_parser("add", help="add or replace an agent")
    add_parser.add_argument("name")
    add_parser.add_argument("--backend", required=True, choices=sorted(AGENT_BACKENDS))
    add_parser.add_argument("--auth", default="subscription", choices=sorted(AGENT_AUTH))
    add_parser.add_argument("--model")
    add_parser.add_argument("--role", default="chat", choices=sorted(AGENT_ROLES))
    add_parser.add_argument("--timeout-seconds", type=int, default=900)
    add_parser.add_argument("--default", action="store_true", help="make this the default chat agent")
    add_parser.add_argument("--replace", action="store_true", help="replace an existing agent")
    remove_parser = agent_subparsers.add_parser("remove", help="remove an agent")
    remove_parser.add_argument("name")

    parser.add_argument("--doctor", action="store_true", help="check dependencies and Ollama, then exit")
    return parser


def main(argv: Optional[Sequence[str]] = None, *, prog: str = "agentdock") -> None:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    commands = {"run", "chat", "doctor", "agents", "watch", "workflow"}
    if raw_args and not raw_args[0].startswith("-") and raw_args[0] not in commands:
        raw_args = ["run", *raw_args]
    args = build_parser(prog).parse_args(raw_args)
    session_token = SESSION_MODELS.set({})
    try:
        repo = find_repo(Path.cwd(), require_git=False)
        if args.command == "watch":
            config = load_config(repo) if state_path(repo, "config.json").exists() else DEFAULT_CONFIG
            try:
                dashboard(repo / STATE_DIR_NAME, list(config["agents"]), once=args.once)
            except ValueError as exc:
                raise WorkflowError(str(exc)) from exc
            return
        ensure_state(repo)
        config = load_config(repo)
        ui.theme = config.get("theme", "violet")
        if args.command == "workflow":
            if args.action == "setup":
                setup_workflow(repo, config)
            else:
                print_workflow(config)
            return
        if args.doctor:
            raise SystemExit(0 if doctor(repo, config) else 1)
        if args.command == "doctor":
            raise SystemExit(0 if doctor(repo, config, require_gradle=not args.no_gradle) else 1)
        if args.command == "run":
            workflow(repo, args.task, config, args.skip_doctor)
            return
        if args.command == "chat":
            with screen.fullscreen(args.fullscreen and args.message is None):
                chat_loop(repo, config, args.agent, args.message)
            return
        if args.command == "agents":
            if args.agents_command == "list":
                print_agents(config)
            elif args.agents_command == "show":
                show_agent(config, args.name)
            elif args.agents_command == "add":
                add_agent(repo, config, args)
            elif args.agents_command == "remove":
                remove_agent(repo, config, args.name)
            return
        raise WorkflowError("Provide a task, run agentdock chat, or run agentdock doctor.")
    except WorkflowError as exc:
        failure(str(exc))
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        failure("Interrupted; no files were reset or discarded.")
        raise SystemExit(130)
    finally:
        try:
            cleanup_session_models()
        finally:
            SESSION_MODELS.reset(session_token)


if __name__ == "__main__":
    main()
