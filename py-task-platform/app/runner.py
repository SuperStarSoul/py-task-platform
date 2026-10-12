"""任务执行器：负责启动、监控、终止子进程，并把状态与日志写入 MongoDB。

- 启动：创建 run 记录 -> 拉起子进程 -> 状态置为 running
- 监控：独立线程读取 stdout/stderr，批量写入 run.logs（上限 MAX_LOG_LINES）
- 结束：按退出码与停止标记判定 success / failed / stopped
- 停止：taskkill /T 递归结束进程树（Windows），或 terminate() 兜底
"""
import datetime as dt
import os
import queue
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time

from bson import ObjectId

from . import config, db


class LaunchError(Exception):
    """任务无法启动（参数缺失、命令无效等）。"""


# run_id -> {"proc": Popen, "stop_event": Event}
_RUNNERS = {}
_RUNNERS_LOCK = threading.Lock()

_TS_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _now():
    return dt.datetime.now(dt.timezone.utc).astimezone()


def _decode(raw: bytes) -> str:
    """优先 UTF-8 解码，失败回退 GBK，避免 Windows 中文输出乱码。"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def _resolve(interpreter: str) -> str:
    if not interpreter:
        interpreter = "python"
    found = shutil.which(interpreter)
    return found or interpreter


def _resolve_first(argv):
    """argv[0] 是裸命令名时，解析为可执行文件完整路径。"""
    first = argv[0]
    if os.sep not in first and "/" not in first:
        found = shutil.which(first)
        if found:
            argv = [found] + argv[1:]
    return argv


def build_argv(command: str, params: dict, interpreter: str = "", free: bool = False):
    """构造子进程 argv。

    - 模板命令：将 {key} 占位符替换为参数值，interpreter 前置
    - 自由命令：按原样切分（posix=False 保留 Windows 反斜杠路径），可选前置 interpreter
    """
    if free:
        text = command
    else:
        missing = []

        def _repl(m):
            key = m.group(1)
            if key in params and params[key] not in ("", None):
                return str(params[key])
            missing.append(key)
            return ""

        text = _TS_PATTERN.sub(_repl, command)
        if missing:
            raise LaunchError("缺少必填参数：" + ", ".join(sorted(set(missing))))

    argv = shlex.split(text, posix=False) if text.strip() else []
    if not argv:
        raise LaunchError("命令为空")
    if interpreter:
        argv = [_resolve(interpreter)] + argv
    return _resolve_first(argv)


def _spawn(argv, cwd):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"  # 让子进程输出统一为 UTF-8
    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        argv,
        cwd=cwd or None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )


def _kill_tree(pid):
    """Windows 下递归结束进程树；taskkill 失败时用 os.kill(SIGTERM) 兜底。"""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            timeout=10, capture_output=True,
        )
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def launch(spec: dict) -> str:
    """按 spec 启动一次任务，返回 run_id。

    spec 字段: template_id / name / command / interpreter / cwd / params / timeout / free
    """
    params = spec.get("params") or {}
    timeout = int(spec.get("timeout") or 0)
    free = bool(spec.get("free"))
    command = spec["command"]
    interpreter = spec.get("interpreter") or ""
    cwd = spec.get("cwd") or ""

    argv = build_argv(command, params, interpreter, free=free)
    name = spec.get("name") or ("自由命令" if free else "未命名任务")

    run_doc = {
        "template_id": spec.get("template_id"),
        "template_name": name,
        "free": free,
        "command": command,
        "resolved_command": " ".join(argv),
        "interpreter": interpreter,
        "cwd": cwd,
        "params": params,
        "timeout": timeout,
        "status": "pending",
        "pid": None,
        "exit_code": None,
        "killed_by": None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "logs": [],
        "created_at": _now(),
    }
    run_id = str(db.runs.insert_one(run_doc).inserted_id)

    try:
        proc = _spawn(argv, cwd)
    except Exception as exc:  # 启动失败（路径不存在、命令无效等）
        msg = f"启动失败：{exc}"
        db.runs.update_one(
            {"_id": ObjectId(run_id)},
            {"$set": {
                "status": "failed", "exit_code": -1,
                "finished_at": _now(), "duration_ms": 0, "killed_by": "launch_error",
            },
             "$push": {"logs": {"$each": [{"ts": _now(), "stream": "stderr", "line": msg}],
                                "$slice": -config.MAX_LOG_LINES}}},
        )
        return run_id

    threading.Thread(
        target=_watch, args=(run_id, proc, timeout), daemon=True
    ).start()
    return run_id


def _watch(run_id: str, proc, timeout: int):
    ctx = {"proc": proc, "stop_event": threading.Event()}
    with _RUNNERS_LOCK:
        _RUNNERS[run_id] = ctx

    q = queue.Queue()

    def _pump(stream, name):
        for raw in iter(stream.readline, b""):
            if not raw:
                break
            q.put((name, _decode(raw).rstrip("\r\n")))
        stream.close()

    threading.Thread(target=_pump, args=(proc.stdout, "stdout"), daemon=True).start()
    threading.Thread(target=_pump, args=(proc.stderr, "stderr"), daemon=True).start()

    db.runs.update_one(
        {"_id": ObjectId(run_id)},
        {"$set": {"status": "running", "pid": proc.pid, "started_at": _now()}},
    )

    timer = None
    if timeout > 0:
        def _timeout_kill():
            if proc.poll() is None:
                ctx["stop_event"].set()
                _kill_tree(proc.pid)
                db.runs.update_one(
                    {"_id": ObjectId(run_id)},
                    {"$set": {"killed_by": "timeout"}},
                )

        timer = threading.Timer(timeout, _timeout_kill)
        timer.daemon = True
        timer.start()

    buffer = []

    def _flush():
        if buffer:
            db.runs.update_one(
                {"_id": ObjectId(run_id)},
                {"$push": {"logs": {"$each": buffer, "$slice": -config.MAX_LOG_LINES}}},
            )
            buffer.clear()

    # 等进程退出，且日志队列排空
    while True:
        try:
            stream, line = q.get(timeout=0.2)
            buffer.append({"ts": _now(), "stream": stream, "line": line})
            if len(buffer) >= 50:
                _flush()
        except queue.Empty:
            if proc.poll() is not None:
                break

    while True:
        try:
            stream, line = q.get_nowait()
            buffer.append({"ts": _now(), "stream": stream, "line": line})
        except queue.Empty:
            break
    _flush()

    exit_code = proc.poll()
    try:
        if ctx["stop_event"].is_set():
            status = "stopped"
        elif exit_code == 0:
            status = "success"
        else:
            status = "failed"

        finished = _now()
        doc = db.runs.find_one({"_id": ObjectId(run_id)}, {"started_at": 1})
        started = (doc or {}).get("started_at") or finished
        if started.tzinfo is None:  # MongoDB 读回的 datetime 为 naive UTC
            started = started.replace(tzinfo=dt.timezone.utc).astimezone()
        duration_ms = int((finished - started).total_seconds() * 1000)

        db.runs.update_one(
            {"_id": ObjectId(run_id)},
            {"$set": {
                "status": status, "exit_code": exit_code,
                "finished_at": finished, "duration_ms": duration_ms,
            }},
        )
    except Exception as exc:  # 兜底：状态结算失败时标记失败，避免永久卡在 running
        db.runs.update_one(
            {"_id": ObjectId(run_id)},
            {"$set": {"status": "failed", "exit_code": exit_code,
                      "finished_at": _now(), "killed_by": "internal_error"},
             "$push": {"logs": {"$each": [{"ts": _now(), "stream": "stderr",
                                           "line": f"[platform] 状态结算异常: {exc}"}],
                                "$slice": -config.MAX_LOG_LINES}}},
        )
    finally:
        with _RUNNERS_LOCK:
            _RUNNERS.pop(run_id, None)
        if timer:
            timer.cancel()


def stop(run_id: str) -> bool:
    """停止正在运行的任务，返回是否已发起停止。"""
    with _RUNNERS_LOCK:
        ctx = _RUNNERS.get(run_id)
    if not ctx:
        raise LaunchError("找不到该任务的进程句柄（可能平台重启过）")
    if ctx["proc"].poll() is not None:
        raise LaunchError("任务已结束，无需停止")
    ctx["stop_event"].set()
    _kill_tree(ctx["proc"].pid)
    db.runs.update_one(
        {"_id": ObjectId(run_id)},
        {"$set": {"killed_by": "user"}},
    )
    return True
