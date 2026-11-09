#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Codex notify 钩子：一个回合结束时，让座机回铃提醒。

用法（~/.codex/config.toml）：
    notify = ["C:\\Users\\Gavin\\oldphone-ata\\.venv\\Scripts\\python.exe",
              "C:\\Users\\Gavin\\oldphone-ata\\hooks\\codex_notify.py"]

Codex 会把 JSON 作为最后一个参数传进来，payload 形如：
    {"type": "agent-turn-complete", "turn-id": "...", "cwd": "...",
     "input-messages": [...], "last-assistant-message": "..."}

注意：不要在这里放代码、diff、终端输出；只取一句话做语音提醒。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

data = {}
if len(sys.argv) > 1:
    try:
        data = json.loads(sys.argv[-1])
    except json.JSONDecodeError:
        data = {}

if data.get("type") != "agent-turn-complete":
    sys.exit(0)

last = str(data.get("last-assistant-message") or "").strip()
# 首行、去 markdown 标记、限长——语音提醒不需要贴全文
first_line = next((line.strip() for line in last.splitlines() if line.strip()), "")
msg = first_line.lstrip("#*- ").strip()[:120] or "任务已完成"
text = f"任务已完成。{msg}"

subprocess.run(
    [sys.executable, str(ROOT / "oldphone.py"), "reply", "--text", text],
    cwd=str(ROOT),
    check=False,
)
