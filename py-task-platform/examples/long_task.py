"""演示任务：长时间运行，用于测试「停止」与「超时」。

用法: python long_task.py [seconds]
"""
import sys
import time


def main():
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print(f"[long] 开始运行，预计 {total}s")
    for i in range(1, total + 1):
        print(f"[long] 已运行 {i}s / {total}s")
        sys.stdout.flush()
        time.sleep(1)
    print("[long] 完成")


if __name__ == "__main__":
    main()
