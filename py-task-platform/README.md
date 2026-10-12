# PyTask Platform · Python 任务管理平台

一个本地运行的 Web 任务管理平台：在浏览器里登记 Python 任务模板、启动 / 停止 / 重跑任务、实时查看状态与日志，所有数据持久化到本地 MongoDB（`localhost:27017`）。

## 功能

- **任务模板**：登记固定任务（命令 + 参数表单 + 工作目录 + 超时），支持 `{参数名}` 占位符，运行时填参一键启动
- **自由运行**：临时执行任意命令，不保存为模板
- **运行管理**：启动 / 停止（递归结束进程树）/ 重跑，实时状态（排队中 / 运行中 / 成功 / 失败 / 已停止）
- **日志**：stdout / stderr 实时写入 MongoDB，页面自动轮询刷新，保留最近 5000 行
- **仪表盘**：状态统计、分布、正在运行任务、最近运行
- **持久化**：任务模板与运行记录全部存于 MongoDB `py_task_platform` 库（`tasks` / `runs` 集合）

## 快速启动

```bat
:: 方式一：双击
start.bat

:: 方式二：手动
cd py-task-platform
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

启动后浏览器打开：<http://127.0.0.1:8000>

> 首次启动会自动创建两个示例模板（`examples/` 目录下的演示脚本），可直接体验。

## 常驻运行（已配置开机自启）

平台已安装「开机自启」：登录 Windows 后会自动隐藏窗口启动，打开 <http://127.0.0.1:8000/> 即可使用，运行日志写入项目根目录 `server.log`。

- **立即启动（隐藏窗口）**：双击项目根目录 `start_hidden.vbs`
- **取消自启**：删除启动文件夹里的 `PyTaskPlatform.vbs`（路径：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`）

> 平台是本地全栈应用（Python 后端 + 本地 MongoDB），仅监听本机 `127.0.0.1`，无法发布为公网在线应用；如需局域网内其他设备访问，需改监听 `0.0.0.0` 并先做好访问控制（当前无鉴权，且平台可执行任意命令，直接暴露有安全风险）。

> 首次启动会自动创建两个示例模板（`examples/` 目录下的演示脚本），可直接体验。

## 环境要求

- Python 3.10+（开发时使用 3.13）
- MongoDB 已在本机运行（默认 `localhost:27017`，无需账号密码）
- 首次启动会创建 `.venv` 虚拟环境并安装依赖（fastapi / uvicorn / pymongo）

## 配置（环境变量，可选）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MONGO_HOST` | `localhost` | MongoDB 地址 |
| `MONGO_PORT` | `27017` | MongoDB 端口 |
| `MONGO_DB` | `py_task_platform` | 数据库名 |
| `API_HOST` | `127.0.0.1` | Web 服务监听地址（改 `0.0.0.0` 可局域网访问） |
| `API_PORT` | `8000` | Web 服务端口 |

## 自测

```bat
.venv\Scripts\python verify_e2e.py
```

脚本会按「启动 → 成功 / 失败 / 停止 → 日志 → 重跑 → Mongo 核对」全链路跑一遍并把结果写入 `%TEMP%\ptp_e2e.txt`，末尾 `RESULT: ALL PASS` 即全部通过。

## REST API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（含 MongoDB 状态） |
| GET | `/api/stats` | 运行统计 |
| GET/POST | `/api/tasks` | 任务模板列表 / 新建 |
| PUT/DELETE | `/api/tasks/{id}` | 更新 / 删除模板 |
| POST | `/api/tasks/{id}/run` | 按模板启动（body: `{params, timeout}`） |
| POST | `/api/runs` | 启动运行（body: `{template_id}` 或 `{command, name?, interpreter?, cwd?, timeout?}`） |
| GET | `/api/runs` | 运行记录分页（`status` / `keyword` / `page` / `page_size`） |
| GET | `/api/runs/{id}` | 运行详情（含日志） |
| GET | `/api/runs/{id}/logs?offset=` | 增量拉取日志 |
| POST | `/api/runs/{id}/stop` | 停止任务 |
| POST | `/api/runs/{id}/retry` | 重跑（沿用原参数） |

## 说明与边界

- **仅本机使用**：默认只监听 `127.0.0.1`，无登录鉴权，请勿直接暴露到公网
- **数据位置**：全部存于本机 MongoDB `py_task_platform` 库，换机器不共享
- **停止实现**：Windows 下使用 `taskkill /T /F` 递归终止进程树
- **日志编码**：子进程输出按 UTF-8 解码，失败自动回退 GBK，中文不乱码

## 目录结构

```
py-task-platform/
├── app/
│   ├── config.py        # 配置（MongoDB / 端口）
│   ├── db.py            # MongoDB 连接与索引
│   ├── runner.py        # 子进程执行器（启动/监控/停止/日志落库）
│   ├── main.py          # FastAPI 路由
│   └── static/          # 前端（index.html / css / js）
├── examples/            # 示例任务脚本
├── requirements.txt
├── run.py               # 启动入口
└── start.bat            # 一键启动
```
