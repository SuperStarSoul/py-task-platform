"""MongoDB 连接与集合访问。"""
from pymongo import ASCENDING, DESCENDING, MongoClient

from . import config

_client = None
db = None
tasks = None  # 任务模板集合
runs = None   # 运行记录集合


def connect():
    """建立连接并初始化索引。MongoDB 不可用时抛异常，由调用方处理。"""
    global _client, db, tasks, runs
    _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=3000)
    _client.admin.command("ping")  # 强制校验连通性
    db = _client[config.MONGO_DB]
    tasks = db["tasks"]
    runs = db["runs"]
    tasks.create_index([("name", ASCENDING)], unique=True)
    runs.create_index([("created_at", DESCENDING)])
    runs.create_index([("status", ASCENDING)])
    runs.create_index([("template_id", ASCENDING)])
    return db


def is_connected() -> bool:
    try:
        if _client is None:
            return False
        _client.admin.command("ping")
        return True
    except Exception:
        return False
