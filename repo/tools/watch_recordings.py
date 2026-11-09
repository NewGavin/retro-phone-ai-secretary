"""录音目录 watcher：代替 FreeSWITCH 的 api_hangup_hook 来触发处理流程。

为什么不再用钩子：
1. `api_hangup_hook` 里的 `system` 是同步执行，ASR 要十几秒，会把 FreeSWITCH
   的挂机线程卡住十几秒；
2. FreeSWITCH 服务以 SYSTEM 身份运行，钩子拉起的 Python/DSH 没有登录会话，
   DSH 的 Windows 沙箱起不来（报缺少登录 SID），只能读文件、跑不了命令，
   电话派下去的活它干不了。

所以改成：本脚本常驻在「当前登录用户」的会话里，轮询录音目录，发现新的
wav 就起一个 listen-worker 子进程（同一用户身份，DSH 沙箱正常）。
"""

from __future__ import annotations

import msvcrt
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oldphone  # noqa: E402  （复用 cfg/log 与项目路径）

LOG_FILE = ROOT / "logs" / "watch.log"
LOCK_FILE = ROOT / "logs" / ".watch.lock"
POLL_SECONDS = 1.0
SETTLE_SECONDS = 1.5


def log(*args: object) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(str(a) for a in args)
    print(line, flush=True)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def acquire_lock() -> object | None:
    """单实例：Windows 文件锁，进程退出锁自动释放。"""
    LOCK_FILE.parent.mkdir(exist_ok=True)
    fh = open(LOCK_FILE, "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    return fh


def wait_stable(path: Path) -> bool:
    """等文件大小稳定，避免读到写了一半的录音。"""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size == 0:
        return False
    time.sleep(0.6)
    try:
        return path.stat().st_size == size
    except OSError:
        return False


def spawn_worker(path: Path) -> None:
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    out_log = ROOT / "logs" / f"listen-{datetime.now():%Y%m%d-%H%M%S}.log"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with open(out_log, "a", encoding="utf-8") as fh:
        subprocess.Popen(
            [sys.executable, str(ROOT / "oldphone.py"), "listen-worker", "--wav", str(path)],
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
            creationflags=flags,
        )
    log("已启动 listen-worker，输出：", out_log.name)


def main() -> int:
    lock = acquire_lock()
    if lock is None:
        log("已有 watcher 在跑（锁被占用），本进程退出")
        return 0

    rec_dir = Path(str(oldphone.cfg("paths.recordings", "C:/fs/recordings")))
    rec_dir.mkdir(parents=True, exist_ok=True)

    # 启动前的已有录音只当作基线。但如果它是刚刚录完还没处理过的
    # （年龄 < 120 秒），也交给 worker，避免 watcher 重启时漏掉。
    seen: set[str] = set()
    pending: list[Path] = []
    now = time.time()
    for p in sorted(rec_dir.glob("*.wav")):
        seen.add(p.name)
        try:
            age = now - p.stat().st_mtime
        except OSError:
            continue
        if age < 120:
            pending.append(p)
    log(f"开始监听 {rec_dir}（基线 {len(seen)} 个文件，补处理 {len(pending)} 个）")
    for p in pending:
        if wait_stable(p):
            spawn_worker(p)

    while True:
        try:
            for p in sorted(rec_dir.glob("*.wav")):
                if p.name in seen:
                    continue
                try:
                    age = time.time() - p.stat().st_mtime
                except OSError:
                    continue
                if age < SETTLE_SECONDS:
                    continue
                if not wait_stable(p):
                    continue
                seen.add(p.name)
                log(f"发现新录音 {p.name}（{p.stat().st_size} B）")
                spawn_worker(p)
        except Exception as exc:  # watcher 不能因为单次异常退出
            log("轮询出错（继续）：", repr(exc))

        # 确定性回电：桥接投递后若会话已答完这一轮，自动 TTS 回拨
        try:
            oldphone.check_phone_callback()
        except Exception as exc:
            log("回电检查出错（继续）：", repr(exc))

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
