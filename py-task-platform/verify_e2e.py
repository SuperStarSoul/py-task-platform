"""端到端验证脚本：创建模板 -> 启动 -> 状态流转 -> 日志 -> 停止 -> 自由命令 -> Mongo 核对。"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(path, method="GET", body=None):
    req = urllib.request.Request(BASE + path, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    lines = []
    ok = True

    # 1. 健康检查
    h = call("/api/health")
    lines.append(f"[1] health ok={h['ok']} mongo={h['mongo']}")
    ok = ok and h["ok"]

    # 2. 任务模板
    tasks = call("/api/tasks")["items"]
    lines.append(f"[2] templates={len(tasks)}: {[t['name'] for t in tasks]}")
    demo = next((t for t in tasks if "快速任务" in t["name"]), None)
    if not demo:
        ok = False
        lines.append("[2] FAILED: 未找到示例模板")

    # 3. 按模板启动（成功路径）
    run = call(f"/api/tasks/{demo['id']}/run", "POST", {"params": {"loops": "3", "sleep": "0.2"}})
    rid = run["id"]
    lines.append(f"[3] launched run={rid} name={run['template_name']} status={run['status']}")
    for i in range(10):
        time.sleep(1)
        r = call(f"/api/runs/{rid}")
        if r["status"] != "running":
            break
    lines.append(f"[4] final status={r['status']} exit={r['exit_code']} dur={r['duration_ms']}ms logs={len(r['logs'])}")
    lines.append(f"[4] logs sample: {[e['line'] for e in r['logs'][:3]]}")
    ok = ok and r["status"] == "success" and r["exit_code"] == 0 and len(r["logs"]) > 0

    # 5. 日志增量接口
    lg = call(f"/api/runs/{rid}/logs?offset=0")
    lines.append(f"[5] logs endpoint total={lg['total']} status={lg['status']}")

    # 6. 启动长任务并停止
    long_tpl = next((t for t in tasks if "长任务" in t["name"]), None)
    run2 = call(f"/api/tasks/{long_tpl['id']}/run", "POST", {})
    rid2 = run2["id"]
    time.sleep(2)
    st = call(f"/api/runs/{rid2}")
    lines.append(f"[6] long task status={st['status']} pid={st['pid']}")
    ok = ok and st["status"] == "running"
    call(f"/api/runs/{rid2}/stop", "POST")
    for i in range(8):
        time.sleep(1)
        st2 = call(f"/api/runs/{rid2}")
        if st2["status"] != "running":
            break
    lines.append(f"[7] after stop status={st2['status']} killed_by={st2['killed_by']}")
    ok = ok and st2["status"] == "stopped"

    # 8. 失败路径（运行一个必然失败的脚本，cwd 相对平台目录 examples）
    bad = call("/api/runs", "POST", {"command": "python fail_task.py", "cwd": "examples", "name": "失败演示"})
    time.sleep(3)
    rb = call(f"/api/runs/{bad['id']}")
    lines.append(f"[8] fail task status={rb['status']} exit={rb['exit_code']} logs={len(rb['logs'])}")
    ok = ok and rb["status"] == "failed" and rb["exit_code"] != 0

    # 9. 重跑
    rr = call(f"/api/runs/{rid}/retry", "POST")
    lines.append(f"[9] retry created run={rr['id']} status={rr['status']}")

    # 10. Mongo 直查
    import pymongo
    mc = pymongo.MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
    mdb = mc["py_task_platform"]
    lines.append(f"[10] mongo collections: tasks={mdb['tasks'].count_documents({})} runs={mdb['runs'].count_documents({})}")
    lines.append(f"[10] run doc has fields: {sorted(set(rr.keys()) & {'status','pid','exit_code','duration_ms','logs','created_at'})}")

    # 11. 统计接口
    st3 = call("/api/stats")
    lines.append(f"[11] stats by_status={st3['by_status']} total={st3['total']} templates={st3['templates']}")

    # 12. 首页静态
    req = urllib.request.Request(BASE + "/")
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode("utf-8")
    lines.append(f"[12] index.html served, len={len(html)}, has title={'PyTask Platform' in html}")

    lines.append("RESULT: " + ("ALL PASS" if ok else "SOME FAILED"))
    with open(r"C:\Users\dell\AppData\Local\Temp\ptp_e2e.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("done")


if __name__ == "__main__":
    main()
