"""启动入口：python run.py"""
import uvicorn

from app import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.API_HOST, port=config.API_PORT, log_level="info")
