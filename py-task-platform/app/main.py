"""FastAPI 主入口：REST API + 静态前端。"""
import datetime as dt
import os
from pathlib import Path

from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Any, List, Optional

from . import config, db, runner

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLES_DIR = BASE_DIR / "examples"

app = FastAPI(title="PyTask Platform", version="1.0.0")


# ---------------------------------------------------------------- 模型
class ParamDef(BaseModel):
    key: str
    label: str = ""
    default: str = ""
    required: bool = False


class TaskIn(BaseModel):
    name: str
    description: str = ""
    command: str
    interpreter: str = "python"
    cwd: str = ""
    params: List[ParamDef] = []
    timeout: int = 0
    enabled: bool = True


class RunIn(BaseModel):
    template_id: Optional[str] = None   # 二选一：按模板运行
    command: Optional[str] = None       # 二选一：自由命令
    name: Optional[str] = None
    interpreter: Optional[str] = None
    cwd: Optional[str] = None
    params: Optional[dict] = None
    timeout: Optional[int] = 0


# ---------------------------------------------------------------- 依赖
def require_db():
    if not db.is_connected():
        raise HTTPException(503, "MongoDB 未连接，请检查 localhost:27017 服务状态")
    return True


# ---------------------------------------------------------------- 序列化
def _local_iso(value) -> str:
    """MongoDB 读回的 datetime 为 naive UTC，转为本地时间字符串。"""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc).astimezone()
        return value.isoformat()
    return value


def _doc(obj, *, with_logs: bool = False) -> dict:
    doc = dict(obj)
    doc["id"] = str(doc.pop("_id"))
    if not with_logs:
        doc.pop("logs", None)
    for k in ("created_at", "started_at", "finished_at"):
        if isinstance(doc.get(k), dt.datetime):
            doc[k] = _local_iso(doc[k])
    for entry in doc.get("logs", []):
        if isinstance(entry.get("ts"), dt.datetime):
            entry["ts"] = _local_iso(entry["ts"])
    return doc


def _task_spec(template: dict) -> dict:
    return {
        "template_id": str(template["_id"]),
        "name": template["name"],
        "command": template["command"],
        "interpreter": template["interpreter"],
        "cwd": template["cwd"] or "",
        "params": {p["key"]: p.get("default", "") for p in template.get("params", [])},
        "timeout": template.get("timeout", 0),
        "free": False,
    }


# ---------------------------------------------------------------- 启动种子数据
def _seed_demo_tasks():
    if not db.is_connected():
        return
    if db.tasks.count_documents({}) > 0:
        return
    demos = [
        {
            "name": "示例：快速任务",
            "description": "演示任务：循环打印进度并成功退出（examples/demo_task.py）",
            "command": "demo_task.py {loops} {sleep}",
            "interpreter": "python",
            "cwd": str(EXAMPLES_DIR),
            "params": [
                {"key": "loops", "label": "循环轮数", "default": "5", "required": True},
                {"key": "sleep", "label": "每轮间隔(秒)", "default": "0.5", "required": False},
            ],
            "timeout": 0,
            "enabled": True,
        },
        {
            "name": "示例：长任务（可停止）",
            "description": "演示任务：运行约 60 秒，可用来测试停止/超时（examples/long_task.py）",
            "command": "long_task.py",
            "interpreter": "python",
            "cwd": str(EXAMPLES_DIR),
            "params": [],
            "timeout": 0,
            "enabled": True,
        },
    ]
    try:
        db.tasks.insert_many(demos)
    except Exception:
        pass


@app.on_event("startup")
def _startup():
    try:
        db.connect()
        _seed_demo_tasks()
    except Exception as exc:
        print(f"[warn] MongoDB 连接失败（{exc}），页面将提示数据库不可用")


# ---------------------------------------------------------------- 健康检查
@app.get("/api/health")
def health():
    ok = db.is_connected()
    return {"ok": ok, "mongo": f"{config.MONGO_HOST}:{config.MONGO_PORT}", "db": config.MONGO_DB}


# ---------------------------------------------------------------- 统计
@app.get("/api/stats", dependencies=[Depends(require_db)])
def stats():
    statuses = ["pending", "running", "success", "failed", "stopped"]
    by_status = {}
    for s in statuses:
        by_status[s] = db.runs.count_documents({"status": s})
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    running = []
    for r in db.runs.find({"status": "running"}).sort("created_at", -1):
        running.append(_doc(r))
    return {
        "total": db.runs.count_documents({}),
        "by_status": by_status,
        "running": running,
        "today": db.runs.count_documents({"created_at": {"$gte": day_start}}),
        "last_24h": db.runs.count_documents({"created_at": {"$gte": now - dt.timedelta(hours=24)}}),
        "templates": db.tasks.count_documents({}),
    }


# ---------------------------------------------------------------- 任务模板 CRUD
@app.get("/api/tasks", dependencies=[Depends(require_db)])
def list_tasks(keyword: str = ""):
    query = {}
    if keyword:
        query["$or"] = [
            {"name": {"$regex": keyword, "$options": "i"}},
            {"description": {"$regex": keyword, "$options": "i"}},
        ]
    items = [_doc(t) for t in db.tasks.find(query).sort("name", 1)]
    return {"items": items, "total": len(items)}


@app.post("/api/tasks", dependencies=[Depends(require_db)])
def create_task(body: TaskIn):
    data = body.model_dump()
    data["params"] = [p.model_dump() for p in body.params]
    try:
        result = db.tasks.insert_one(data)
    except Exception as exc:  # 唯一索引冲突
        raise HTTPException(400, f"创建失败：{exc}")
    return _doc(db.tasks.find_one({"_id": result.inserted_id}))


@app.put("/api/tasks/{task_id}", dependencies=[Depends(require_db)])
def update_task(task_id: str, body: TaskIn):
    oid = _check_id(task_id)
    data = body.model_dump()
    data["params"] = [p.model_dump() for p in body.params]
    try:
        result = db.tasks.update_one({"_id": oid}, {"$set": data})
    except Exception as exc:
        raise HTTPException(400, f"保存失败：{exc}")
    if result.matched_count == 0:
        raise HTTPException(404, "任务模板不存在")
    return _doc(db.tasks.find_one({"_id": oid}))


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(require_db)])
def delete_task(task_id: str):
    oid = _check_id(task_id)
    result = db.tasks.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "任务模板不存在")
    return {"ok": True}


# ---------------------------------------------------------------- 运行
@app.post("/api/runs", dependencies=[Depends(require_db)])
def create_run(body: RunIn):
    if body.template_id:
        template = db.tasks.find_one({"_id": _check_id(body.template_id)})
        if not template:
            raise HTTPException(404, "任务模板不存在")
        spec = _task_spec(template)
        if body.params is not None:
            spec["params"].update({k: v for k, v in body.params.items()})
        if body.timeout:
            spec["timeout"] = body.timeout
        if body.cwd:
            spec["cwd"] = body.cwd
        spec["params"] = {k: str(v) for k, v in spec["params"].items()}
    elif body.command:
        spec = {
            "template_id": None,
            "name": body.name or "自由命令",
            "command": body.command,
            "interpreter": body.interpreter or "",
            "cwd": body.cwd or "",
            "params": {},
            "timeout": body.timeout or 0,
            "free": True,
        }
    else:
        raise HTTPException(400, "请提供 template_id 或 command")
    try:
        run_id = runner.launch(spec)
    except runner.LaunchError as exc:
        raise HTTPException(400, str(exc))
    return get_run(run_id)


@app.post("/api/tasks/{task_id}/run", dependencies=[Depends(require_db)])
def run_template(task_id: str, body: RunIn = None):
    body = body or RunIn()
    body.template_id = task_id
    return create_run(body)


@app.get("/api/runs", dependencies=[Depends(require_db)])
def list_runs(
    status: str = "",
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = {}
    if status:
        query["status"] = status
    if keyword:
        query["$or"] = [
            {"template_name": {"$regex": keyword, "$options": "i"}},
            {"command": {"$regex": keyword, "$options": "i"}},
            {"resolved_command": {"$regex": keyword, "$options": "i"}},
        ]
    total = db.runs.count_documents(query)
    items = [
        _doc(r)
        for r in db.runs.find(query)
        .sort("created_at", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_db)])
def get_run(run_id: str):
    doc = db.runs.find_one({"_id": _check_id(run_id)})
    if not doc:
        raise HTTPException(404, "运行记录不存在")
    return _doc(doc, with_logs=True)


@app.get("/api/runs/{run_id}/logs", dependencies=[Depends(require_db)])
def get_logs(run_id: str, offset: int = Query(0, ge=0)):
    doc = db.runs.find_one({"_id": _check_id(run_id)}, {"logs": 1, "status": 1})
    if not doc:
        raise HTTPException(404, "运行记录不存在")
    logs = doc.get("logs", [])
    tail = logs[offset:]
    return {"offset": offset + len(tail), "total": len(logs), "status": doc.get("status"),
            "items": [_fmt_log_entry(e) for e in tail]}


def _fmt_log_entry(entry: dict) -> dict:
    e = dict(entry)
    if isinstance(e.get("ts"), dt.datetime):
        e["ts"] = _local_iso(e["ts"])
    return e


@app.post("/api/runs/{run_id}/stop", dependencies=[Depends(require_db)])
def stop_run(run_id: str):
    try:
        runner.stop(run_id)
    except runner.LaunchError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}


@app.post("/api/runs/{run_id}/retry", dependencies=[Depends(require_db)])
def retry_run(run_id: str):
    doc = db.runs.find_one({"_id": _check_id(run_id)})
    if not doc:
        raise HTTPException(404, "运行记录不存在")
    spec = {
        "template_id": doc.get("template_id"),
        "name": doc.get("template_name") or "未命名任务",
        "command": doc.get("command"),
        "interpreter": doc.get("interpreter") or "",
        "cwd": doc.get("cwd") or "",
        "params": dict(doc.get("params") or {}),
        "timeout": doc.get("timeout") or 0,
        "free": bool(doc.get("free")),
    }
    try:
        new_id = runner.launch(spec)
    except runner.LaunchError as exc:
        raise HTTPException(400, str(exc))
    return get_run(new_id)


# ---------------------------------------------------------------- 工具
def _check_id(run_id: str) -> ObjectId:
    try:
        return ObjectId(run_id)
    except Exception:
        raise HTTPException(400, f"无效的 ID：{run_id}")


# ---------------------------------------------------------------- 静态前端
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))
