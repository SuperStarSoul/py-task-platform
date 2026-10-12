"""演示任务：模拟执行失败（退出码 2），用于测试失败态展示。

用法: python fail_task.py
"""
import sys
import time


def main():
    print("[fail] 开始执行...")
    sys.stdout.flush()
    time.sleep(1)
    print("[fail] 处理数据时出现错误：磁盘空间不足", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
