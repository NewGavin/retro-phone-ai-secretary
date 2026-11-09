#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单独用本机 DSH 跑一次性任务：py tools\\dsh.py "帮我把 README 里的错别字改掉"

等价于 `dsh headless "<task>"`，但自动处理两件麻烦事：
  1. 用 ELECTRON_RUN_AS_NODE=1 启动 DSH 桌面版，执行 app.asar 里打包的 CLI；
  2. 从 ~/.dsh/.credentials.yaml 取 DEEPSEEK_API_KEY（DSH 模型设置写入的）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import oldphone  # noqa: E402  （复用 dsh_command / dsh_env）


def main() -> int:
    task = " ".join(sys.argv[1:]).strip()
    if not task:
        print('用法: py tools\\dsh.py "任务内容"')
        return 2
    proc = subprocess.run(
        oldphone.dsh_command(task),
        env=oldphone.dsh_env(),
        cwd=str(oldphone.ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sys.stdout.write(proc.stdout or "")
    if proc.returncode != 0 and proc.stderr:
        sys.stderr.write(proc.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
