"""全局配置：MongoDB 连接与平台参数（支持环境变量覆盖）。"""
import os

# MongoDB（默认即用户本地库 localhost:27017）
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB = os.getenv("MONGO_DB", "py_task_platform")
MONGO_URI = os.getenv("MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}")

# Web 服务监听地址（仅本机访问，如需局域网访问改为 0.0.0.0）
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# 每条运行记录最多保留的日志行数（超出后丢弃最旧的）
MAX_LOG_LINES = 5000
