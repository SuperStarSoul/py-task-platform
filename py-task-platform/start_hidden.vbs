' PyTask Platform 隐藏启动脚本（供开机自启/手动双击使用）
' 以隐藏窗口启动平台，输出写入项目根目录 server.log
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\dell\Doubao\chats\2026-10-12\new-chat\py-task-platform"
sh.Run "cmd /c .venv\Scripts\python.exe run.py >> server.log 2>&1", 0, False
