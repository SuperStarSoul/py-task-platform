"""演示任务：循环打印进度并成功退出。

用法: python demo_task.py [loops] [sleep]
  loops  循环轮数，默认 5
  sleep  每轮间隔秒数，默认 0.5
"""
import sys
import time


def main():
    loops = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    sleep = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    print(f"[demo] 启动，共 {loops} 轮，每轮间隔 {sleep}s")
    for i in range(1, loops + 1):
        print(f"[demo] 第 {i}/{loops} 轮执行中...")
        sys.stdout.flush()
        time.sleep(sleep)
    print("[demo] 全部完成")


if __name__ == "__main__":
    main()
