#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""老座机 AI 秘书 —— 软件链路（ATA + FreeSWITCH 版）。

架构：
  座机摘机 → HT801 自动呼叫 6001 → FreeSWITCH 接听并录音（8kHz wav）
  → 挂机触发本脚本 listen → 本地 Whisper 转写 → Agent 执行
  → edge-tts 生成回复 → FreeSWITCH 呼叫座机分机 100 → 座机真振铃 → 播放 TTS

用法：
  python oldphone.py selftest                 # 无需硬件：TTS → 8k wav → ASR 回读
  python oldphone.py tts --text "你好" -o tts/out.wav
  python oldphone.py asr --wav rec.wav
  python oldphone.py ring --wav tts/out.wav   # 只让座机振铃并播放
  python oldphone.py reply --text "任务完成"   # TTS 后立即回铃
  python oldphone.py listen --wav rec.wav     # 完整链路：ASR → Agent → TTS → 回铃
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}

# 告诉 agent：这段话会被念到电话里，别写论文。
PHONE_HINT = (
    "\n\n（补充要求：这段回答会被语音合成后念到电话听筒里，"
    "请直接用不超过 120 字的中文口语回答，不要用 Markdown 表格、代码块、链接或分点列表，"
    "细节可以省略。）"
)

# Windows 控制台默认 GBK，统一转 UTF-8，避免中文输出乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def cfg(path: str, default=None):
    node = CONFIG
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def log(*args) -> None:
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def find_ffmpeg() -> str:
    """找 ffmpeg：配置 → PATH → 常见安装位置。

    挂机钩子由 FreeSWITCH 服务以 SYSTEM 身份拉起，SYSTEM 的 PATH 里没有用户装的
    ffmpeg，所以不能只依赖 "ffmpeg" 这个名字。
    """
    candidates = [
        str(cfg("ffmpeg", "") or ""),
        shutil.which("ffmpeg") or "",
        r"F:\projects\ffmpeg-n9.0-latest-win64-gpl-9.0\bin\ffmpeg.EXE",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise SystemExit("找不到 ffmpeg：请把 config.yaml 的 ffmpeg 改成绝对路径。")


# ---------------------------------------------------------------- TTS
def tts_to_wav8k(text: str, out_wav: str | Path) -> Path:
    """edge-tts 合成中文语音，转成电话线/FreeSWITCH 可用的 8kHz 16bit 单声道 wav。"""
    import edge_tts

    out = Path(out_wav)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    mp3 = out.with_suffix(".mp3")

    async def _run() -> None:
        voice = cfg("tts.voice", "zh-CN-XiaoxiaoNeural")
        await edge_tts.Communicate(text, voice).save(str(mp3))

    asyncio.run(_run())
    subprocess.run(
        [
            find_ffmpeg(), "-y", "-loglevel", "error", "-i", str(mp3),
            "-ar", "8000", "-ac", "1", "-acodec", "pcm_s16le", str(out),
        ],
        check=True,
    )
    mp3.unlink(missing_ok=True)
    log("TTS 完成:", out, f"({out.stat().st_size // 1024} KB)")
    return out


# ---------------------------------------------------------------- ASR
_model = None


def transcribe(wav_path: str | Path) -> str:
    engine = cfg("asr.engine", "local")
    if engine != "local":
        raise SystemExit(
            "config.yaml 里 asr.engine 目前只实现了 local。"
            "要用火山引擎，请先在 src 层接好 volcengine SDK，把 key 填进 config.yaml。"
        )

    if cfg("asr.hf_mirror", True):
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    # 缓存目录放项目内：挂机钩子由 FreeSWITCH 服务（SYSTEM）拉起，默认缓存路径会变
    hf_home = str(cfg("asr.hf_home", "") or "").strip()
    if hf_home:
        hf = Path(hf_home)
        if not hf.is_absolute():
            hf = ROOT / hf
        hf.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(hf)
        os.environ.setdefault("HF_HUB_CACHE", str(hf / "hub"))

    from faster_whisper import WhisperModel

    global _model
    if _model is None:
        name = cfg("asr.model", "small")
        log("加载 Whisper 模型:", name, "(首次运行会自动下载)")
        _model = WhisperModel(name, device="cpu", compute_type="int8")

    segments, info = _model.transcribe(
        str(wav_path),
        language="zh",
        vad_filter=True,
        initial_prompt=(
            "以下是普通话电话录音，请用简体中文书写，可能带有电话线路噪声。"
            "说话人可能会自称「老座机」。"
        ),
    )
    text = "".join(seg.text for seg in segments).strip()
    log(f"ASR 完成（音频 {info.duration:.1f}s）:", text or "<空>")
    return text


# ---------------------------------------------------------------- Agent
def load_dsh_key() -> str:
    """DSH 的 API key：优先环境变量，其次 ~/.dsh/.credentials.yaml 的 refs 段。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key

    ref = str(cfg("agent.dsh.key_ref", "DEEPSEEK_API_KEY"))
    cred = Path(str(cfg("agent.dsh.credentials", "~/.dsh/.credentials.yaml"))).expanduser()
    if cred.exists():
        data = yaml.safe_load(cred.read_text(encoding="utf-8")) or {}
        value = (data.get("refs") or {}).get(ref, "")
        if isinstance(value, str) and value.strip():
            return value.strip()

    raise SystemExit(
        "找不到 DEEPSEEK_API_KEY。\n"
        f"  已查环境变量，以及 {cred} 的 refs.{ref}\n"
        "  修复：打开 DSH 桌面版「模型设置」填一次 key，或 set DEEPSEEK_API_KEY=sk-... 再重试。"
    )


def dsh_home() -> str:
    """私有 DSH_HOME（config 的 agent.dsh.home）；空字符串 = 用默认 ~/.dsh。"""
    return str(cfg("agent.dsh.home", "") or "").strip()


def ensure_dsh_home() -> None:
    """首次运行时，把桌面版 ~/.dsh/profiles/<profile> 复制到私有 home。

    桌面版和 CLI 同时往 ~/.dsh/profiles/headless 写 cordis.yml 时会互抢，
    表现为 EPERM；复制到独立 home 后两边不再碰同一个文件。
    """
    home = dsh_home()
    if not home:
        return
    profile = str(cfg("agent.dsh.profile", "headless"))
    target = Path(home).expanduser() / "profiles" / profile
    if target.is_dir():
        return

    source = Path.home() / ".dsh" / "profiles" / profile
    # FS 服务以 SYSTEM 运行，Path.home() 会变成 systemprofile；优先按凭据文件所在目录推
    cred = Path(str(cfg("agent.dsh.credentials", ""))).expanduser()
    if cred.is_file():
        alt = cred.parent / "profiles" / profile
        if alt.is_dir():
            source = alt
    if not source.is_dir():
        raise SystemExit(
            f"找不到要复制的 DSH profile：{source}\n"
            "  请先在 DSH 桌面版里正常打开一次，或用默认 home（把 agent.dsh.home 留空）。"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    log("已初始化私有 DSH_HOME:", str(target))


def dsh_env() -> dict:
    """DSH CLI 跑在 Electron 的 Node 模式里，需要这些环境变量。"""
    env = dict(os.environ)
    env["ELECTRON_RUN_AS_NODE"] = "1"
    env["DEEPSEEK_API_KEY"] = load_dsh_key()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    home = dsh_home()
    if home:
        env["DSH_HOME"] = home
    # DSH 沙箱要求临时目录在 workspace 之外且可写；固定成配置里的独立目录。
    tmp = cfg("agent.dsh.temp", "")
    if tmp:
        try:
            Path(tmp).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        for var in ("TMP", "TEMP", "TMPDIR"):
            env[var] = tmp
    return env


def dsh_command(prompt: str) -> list[str]:
    """复用桌面版自带的 dsh CLI（打包在 app.asar 里），无需另装 Codex/Claude。"""
    exe = str(cfg("agent.dsh.exe", "D:/DSH/DeepSeek Harness.exe"))
    cli = str(cfg("agent.dsh.cli", ""))
    profile = str(cfg("agent.dsh.profile", "headless"))
    if not cli:
        raise SystemExit("config.yaml 缺 agent.dsh.cli（DSH 内置 CLI 的 bin.js 路径）")
    if not Path(exe).exists():
        raise SystemExit(f"找不到 DSH 桌面版：{exe}")
    # CLI 打包在 app.asar 里，Windows 文件系统看不到 asar 内部，只校验 asar 文件本身
    asar = cli.split(".asar/")[0] + ".asar" if ".asar/" in cli else cli
    if not Path(asar).exists():
        raise SystemExit(f"找不到 DSH CLI：{cli}")
    return [exe, cli, "--profile", profile, prompt]


def run_dsh(prompt: str) -> tuple[int, str, str]:
    """跑一次 headless 任务。Windows 上 profile 根文件偶发被占用（EPERM），重试到 5 次。"""
    ensure_dsh_home()
    attempts = int(cfg("agent.dsh.retries", 5))
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(
            dsh_command(prompt), capture_output=True, text=True,
            timeout=int(cfg("agent.dsh.timeout", 1800)),
            env=dsh_env(), cwd=str(ROOT), encoding="utf-8", errors="replace",
        )
        err = proc.stderr or ""
        if proc.returncode == 0 or "EPERM" not in err or attempt == attempts:
            return proc.returncode, proc.stdout or "", err
        log(f"DSH 启动遇到 EPERM（profile 文件被占用），3 秒后重试 {attempt}/{attempts - 1}")
        time.sleep(3)
    return 1, "", ""


def dispatch(prompt: str) -> str:
    mode = cfg("agent.mode", "echo")
    if mode == "echo":
        return f"收到指令：{prompt}。当前是演示模式，任务已完成。"

    if mode == "bridge":
        log("投递到桌面 DSH 会话：", prompt[:80])
        bridge_send(prompt)
        return "已投递到桌面 DSH 会话，答复会由会话侧回拨。"

    if mode == "dsh":
        log("调用 DSH headless，任务：", prompt[:80])
        code, stdout, stderr = run_dsh(prompt + PHONE_HINT)
        out = stdout.strip()
        if code != 0:
            log("DSH 退出码:", code, stderr[:300])
            out = out or f"任务执行失败，退出码 {code}。"
        return out[-800:] or "任务结束，但没有返回内容。"

    command = str(cfg("agent.command", 'codex exec "{prompt}"')).format(prompt=prompt)
    log("调用 agent:", command[:160])
    proc = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        timeout=int(cfg("agent.timeout", 900)),
    )
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0:
        log("agent 退出码:", proc.returncode)
    return out[-800:] or "任务结束，但没有返回内容。"


# ---------------------------------------------------------------- 桌面会话桥
# 用 dsh-idle-watchdog 的 HTTP 接口，把电话转写文本投进「当前桌面 DSH 会话」，
# 电话里说的话和 GUI 里是同一段上下文，不再另起 headless 会话。
def bridge_secret() -> str:
    """API secret：读文件（0600），不落配置、不打日志。"""
    path = Path(str(cfg("bridge.secret_file", "~/.dsh/idle-watchdog/api-secret"))).expanduser()
    if not path.is_file():
        raise SystemExit(
            f"找不到 idle-watchdog 的 API secret：{path}\n"
            "  先在 DSH 桌面端的插件市场里安装并启用 dsh-idle-watchdog。"
        )
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise SystemExit(f"API secret 文件是空的：{path}")
    return secret


def http_json(url: str, payload: dict | None = None, headers: dict | None = None,
              timeout: float = 5.0) -> dict:
    """极简 JSON HTTP 客户端（只用标准库，避免给电话链路再加依赖）。"""
    import json
    import urllib.error
    import urllib.request

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    return json.loads(body) if body else {}


def bridge_find_url() -> str:
    """找当前 DSH 桌面端的 web 端口。

    DSH 桌面端每次启动端口都会变（实测 3244 -> 1762），所以默认自动探测：
    遍历本机 LISTENING 的 127.0.0.1 端口，找 /dsh-idle-watchdog/api/health。
    """
    configured = str(cfg("bridge.url", "") or "").strip()
    if configured and configured.lower() != "auto":
        return configured.rstrip("/")

    import re

    proc = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    ports: list[int] = []
    for line in (proc.stdout or "").splitlines():
        m = re.search(r"127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING", line)
        if m:
            port = int(m.group(1))
            if port >= 1024 and port not in ports:
                ports.append(port)
    known = (3244, 1762, 3080, 8080)
    ports.sort(key=lambda p: (0 if p in known else 1, p))
    for port in ports[:40]:
        base = f"http://127.0.0.1:{port}"
        try:
            info = http_json(base + "/dsh-idle-watchdog/api/health", timeout=0.5)
        except Exception:
            continue
        if info.get("plugin") == "dsh-idle-watchdog":
            log("发现 DSH 桌面端：", base)
            return base
    raise SystemExit("找不到 DSH 桌面端（dsh-idle-watchdog 的 /health 没响应）。")


def _norm_path(value: str) -> str:
    """统一路径比较口径：Windows 反斜杠与正斜杠、大小写都不算差异。"""
    return str(value or "").replace("\\", "/").rstrip("/").lower()


def bridge_pick_chat(base: str) -> str:
    """目标会话：bridge.chat 显式指定最稳；auto = 最近活跃的 GUI 会话。"""
    chat = str(cfg("bridge.chat", "auto") or "auto").strip()
    if chat and chat.lower() != "auto":
        return chat

    wanted_cwd = _norm_path(cfg("bridge.cwd", ""))
    rows = http_json(base + "/dsh-idle-watchdog/api/chats?refresh", timeout=120).get("rows", [])
    # 优先活跃会话；DSH 刚重启时全是冷的，此时退回全体会话，靠插件 wakeColdForApi 唤醒
    pool = [r for r in rows if r.get("live")] or rows
    if wanted_cwd:
        matched = [r for r in pool if _norm_path(r.get("cwd", "")) == wanted_cwd]
        if not matched:
            raise SystemExit(
                f"没有 cwd 匹配 {wanted_cwd} 的会话：先在 GUI 里打开目标会话，"
                "或把 config.yaml 的 bridge.cwd 留空。"
            )
        pool = matched
    if not pool:
        raise SystemExit("桌面端没有任何可投递的会话：先在 GUI 里打开一个会话再试。")

    # 「最新活跃」按会话日志的最后写入时间算（createdAt 只是创建时间，不代表最近用过）
    def _last_active(row: dict) -> float:
        path = session_log_path(str(row.get("sessionId", "")))
        try:
            return path.stat().st_mtime if path else 0.0
        except OSError:
            return 0.0

    pool.sort(key=lambda r: (_last_active(r), r.get("createdAt", 0)), reverse=True)
    return str(pool[0]["sessionId"])


def bridge_phone_message(text: str) -> str:
    """投进桌面会话的正文：电话原话 + 处理要求（回电由 watcher 自动完成）。"""
    return (
        "【座机来电】用户是通过老式座机话筒说的这句话（语音识别结果，可能有错字）：\n\n"
        f"「{text}」\n\n"
        "请像平常一样处理这条指令，然后正常回答（一两句话即可）。\n"
        "如果这句话明确要求转给别的会话（例如「插到聊 XX 的那个会话」），先运行\n"
        f'  "{sys.executable}" "{Path(__file__).resolve()}" route --chat "<会话id或标题片段>" --text "<原话>"\n'
        "把原话转发过去，再在本会话简短确认；回电会跟着目标会话的回答走。\n"
        "回电由本机 watcher 自动完成，不需要你执行任何回拨命令。\n"
    )


def bridge_send(text: str, chat: str | None = None) -> dict:
    """把电话指令投进桌面 DSH 会话（user 角色消息），返回插件响应。

    chat 为空时按配置（bridge.chat=auto → 同目录最新的活跃会话）。
    """
    base = bridge_find_url()
    target = chat or bridge_pick_chat(base)
    payload = {
        "chat": target,
        "message": bridge_phone_message(text),
        "provenance": "oldphone-ata/phone",
    }
    headers = {
        "content-type": "application/json",
        "x-idle-watchdog-secret": bridge_secret(),
    }
    try:
        result = http_json(base + "/dsh-idle-watchdog/api/prompt", payload, headers,
                           timeout=float(cfg("bridge.timeout", 60)))
    except RuntimeError as exc:
        raise SystemExit(f"投递到桌面会话失败：{exc}") from None
    resolved = str((result or {}).get("chat") or target)
    log("投递结果：", result)
    write_pending(resolved)
    return result


# ------------------------------------------------ 确定性回电（监听会话日志）
# 不再依赖 agent 自觉执行回拨命令：桥接投递后在 .tmp 里记一条「待回电」，
# watcher 轮询 DSH 会话日志，一旦出现「【座机来电】」并走完一轮，就自动 TTS 回拨。
def _pending_file() -> Path:
    return ROOT.parent / ".tmp" / "phone-pending.json"


def write_pending(chat: str) -> None:
    now = int(time.time() * 1000)
    ttl = int(cfg("bridge.callback_ttl_seconds", 900))
    path = _pending_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "chat": chat,
        "injectedAt": now,
        "expiresAt": now + ttl * 1000,
    }, ensure_ascii=False), encoding="utf-8")


def read_pending() -> dict | None:
    path = _pending_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_pending() -> None:
    try:
        _pending_file().unlink()
    except OSError:
        pass


def session_log_path(chat: str) -> Path | None:
    """按会话 id 找 DSH 的 session.v4.jsonl.zstd。"""
    base = Path(str(cfg("bridge.sessions_dir", "~/.dsh/sessions"))).expanduser()
    if not base.is_dir():
        return None
    for pattern in (f"*/{chat}", f"*/{chat}*"):
        for folder in base.glob(pattern):
            path = folder / "session.v4.jsonl.zstd"
            if path.is_file():
                return path
    return None


def read_session_events(path: Path) -> list[dict]:
    """解压并解析会话 JSONL（zstd 帧无 content size，只能流式读）。"""
    import zstandard as zstd

    dctx = zstd.ZstdDecompressor()
    with path.open("rb") as fh, dctx.stream_reader(fh) as reader:
        raw = reader.read()
    events: list[dict] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def _event_text(event: dict) -> str:
    data = event.get("data") or {}
    content = data.get("content")
    if content is None:
        content = (data.get("message") or {}).get("content") or []
    return "".join(
        str(part.get("text") or "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )


_last_scan: dict[str, tuple[int, int]] = {}


def check_phone_callback() -> bool:
    """发现「【座机来电】」这一轮答完，就自动回拨。返回是否触发了回拨。"""
    pending = read_pending()
    if not pending:
        return False
    if time.time() * 1000 > int(pending.get("expiresAt", 0)):
        log("回电待办已超时，放弃（答复仍保留在会话里）")
        clear_pending()
        return False

    path = session_log_path(str(pending.get("chat", "")))
    if path is None:
        return False

    # 会话日志可能很大：文件没变 + 待办没变就跳过解压（watcher 每秒轮询）
    try:
        signature = (path.stat().st_mtime_ns, int(pending.get("injectedAt", 0)))
    except OSError:
        return False
    if _last_scan.get(str(path)) == signature:
        return False
    _last_scan[str(path)] = signature

    events = read_session_events(path)

    start_seq = None
    injected_at = int(pending.get("injectedAt", 0))
    for event in events:
        if event.get("type") != "user/message":
            continue
        if int(event.get("time") or 0) < injected_at:
            continue
        if "【座机来电】" in _event_text(event):
            start_seq = int(event.get("seq") or 0)
            break
    if start_seq is None:
        return False

    texts: list[str] = []
    finished = False
    for event in events:
        seq = int(event.get("seq") or 0)
        if seq <= start_seq:
            continue
        kind = event.get("type")
        if kind == "assistant/message":
            text = _event_text(event)
            if text.strip():
                texts.append(text)
        elif kind == "turn/end":
            finished = True
            break
    if not finished or not texts:
        return False

    answer = texts[-1]
    clear_pending()
    outbox = ROOT / "outbox"
    outbox.mkdir(exist_ok=True)
    (outbox / f"reply-{datetime.now():%Y%m%d-%H%M%S}.txt").write_text(answer, encoding="utf-8")
    spoken = spoken_text(answer, int(cfg("agent.phone_reply_chars", 260)))
    log("会话答复（电话里要念的）：", spoken[:120])
    try:
        wav = tts_to_wav8k(spoken, ROOT / "tts" / f"reply-{datetime.now():%Y%m%d-%H%M%S}.wav")
        ring_and_play(wav)
    except Exception as exc:  # 回拨失败不影响已保存的答复
        log("自动回拨失败（答复仍已保存）：", repr(exc))
    return True


# ---------------------------------------------------------------- 回铃
def find_fs_cli() -> str:
    """按「配置 → C:\\FreeSWITCH → Program Files → PATH」顺序找 fs_cli，省得手改配置。"""
    import shutil

    candidates = [
        str(cfg("pbx.fs_cli", "")),
        r"C:\FreeSWITCH\fs_cli.exe",
        r"C:\Program Files\FreeSWITCH\fs_cli.exe",
        shutil.which("fs_cli") or "",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise SystemExit(
        "找不到 fs_cli.exe。\n"
        f"  配置里写的是：{candidates[0] or '<空>'}\n"
        "  已尝试：C:\\FreeSWITCH\\fs_cli.exe、C:\\Program Files\\FreeSWITCH\\fs_cli.exe、PATH\n"
        "  请先安装 FreeSWITCH MSI，或把 config.yaml 的 pbx.fs_cli 改成实际路径。"
    )


def ring_and_play(wav_path: str | Path) -> str:
    """让座机真振铃，接听后播放 wav。依赖 FreeSWITCH 的 fs_cli。"""
    fs_cli = find_fs_cli()
    dial = str(cfg("pbx.dial_string", "user/100"))
    wav = Path(wav_path)
    if not wav.is_absolute():
        wav = ROOT / wav
    wav_posix = wav.resolve().as_posix()

    opts = (
        "origination_caller_id_name=Secretary,"
        "origination_caller_id_number=6001,"
        f"originate_timeout={int(cfg('pbx.ring_timeout', 90))},"
        "ignore_early_media=true"
    )
    api = f"bgapi originate {{{opts}}}{dial} &playback({wav_posix})"
    log("发起回呼:", api)
    try:
        proc = subprocess.run(
            [fs_cli, "-x", api], capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        raise SystemExit(
            f"找不到 fs_cli：{fs_cli}\n"
            "请先安装 FreeSWITCH，或把 config.yaml 的 pbx.fs_cli 改成实际路径。"
        )
    if proc.returncode != 0:
        raise SystemExit(f"fs_cli 调用失败：{proc.stderr or proc.stdout}")
    return proc.stdout.strip()


# ---------------------------------------------------------------- 主流程
def wait_file_stable(path: Path, timeout: float = 20.0) -> None:
    """挂机瞬间录音文件可能还没 flush，等大小稳定再转写。"""
    last = -1
    deadline = time.time() + timeout
    while time.time() < deadline:
        size = path.stat().st_size if path.exists() else 0
        if size > 44 and size == last:
            return
        last = size
        time.sleep(0.3)
    log("警告：录音文件大小未稳定，可能是空录音")


def spawn_dsh_task(prompt: str) -> Path:
    """把任务转后台：本进程立刻退出，任务跑完后由子进程负责回拨。"""
    tasks = ROOT / "tasks"
    tasks.mkdir(exist_ok=True)
    prompt_file = tasks / f"prompt-{datetime.now():%Y%m%d-%H%M%S}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"dsh-{datetime.now():%Y%m%d-%H%M%S}.log"
    log_file = open(log_path, "a", encoding="utf-8")

    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [sys.executable, str(ROOT / "oldphone.py"), "dsh-task", "--prompt-file", str(prompt_file)],
        cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags,
    )
    return log_path


def handle_recording(wav_path: str | Path) -> None:
    wav = Path(wav_path)
    if not wav.exists():
        raise SystemExit(f"录音不存在：{wav}")
    wait_file_stable(wav)

    text = transcribe(wav)
    if not text:
        log("没有识别到语音，放弃回铃")
        return

    if str(cfg("agent.mode", "echo")) == "bridge":
        log("bridge 模式：投递到桌面会话，回复由会话侧回拨")
        dispatch(text)
        return

    if str(cfg("agent.mode", "echo")) == "dsh" and bool(cfg("agent.async", True)):
        log_path = spawn_dsh_task(text)
        log("已转后台执行 DSH，完成后回拨；日志：", log_path.name)
        return

    reply = dispatch(text)
    out = tts_to_wav8k(reply, ROOT / "tts" / f"reply-{datetime.now():%Y%m%d-%H%M%S}.wav")
    print(ring_and_play(out))
    log("回铃已发起，等座机接听")


def spoken_text(text: str, limit: int = 260) -> str:
    """把 Markdown/长篇答复压成电话里能听清的口语短句。"""
    import re

    s = text
    s = re.sub(r"```.*?```", " ", s, flags=re.S)      # 代码块整段不要
    s = re.sub(r"`([^`]*)`", r"\1", s)                # 行内代码去反引号
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)       # 图片
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)    # 链接只留文字
    lines = []
    for ln in s.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("|") or set(ln) <= set("-|: "):
            continue
        ln = re.sub(r"^#{1,6}\s*", "", ln)            # 标题井号
        ln = re.sub(r"^[-*+]\s+", "", ln)             # 列表符号
        ln = re.sub(r"^>\s*", "", ln)                 # 引用
        ln = ln.replace("**", "").replace("__", "").replace("*", "")
        lines.append(ln)
    s = "，".join(lines)
    s = re.sub(r"\s+", " ", s).strip(" ，。")
    if len(s) <= limit:
        return s
    cut = max(s.rfind(ch, 0, limit) for ch in "。！？；")
    if cut <= 40:
        cut = limit
    return s[: cut + 1] + "（完整内容已存到 outbox，回电脑可以看。）"


def handle_reply(text: str) -> None:
    spoken = spoken_text(text, int(cfg("agent.phone_reply_chars", 260)))
    log("电话里要念的答复：", spoken[:120])
    out = tts_to_wav8k(spoken, ROOT / "tts" / f"reply-{datetime.now():%Y%m%d-%H%M%S}.wav")
    print(ring_and_play(out))
    log("回铃已发起，等座机接听")


def cmd_listen(args: argparse.Namespace) -> None:
    """挂机钩子入口：立刻返回，把真正的处理交给独立后台进程。

    为什么不在 FreeSWITCH 的 api_hangup_hook 里直接跑完整流程：
    `system` 是同步执行，ASR 要十几秒，会把 FreeSWITCH 的挂机线程卡住十几秒。
    """
    wav = Path(args.wav)
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    out_log = logs / f"listen-{datetime.now():%Y%m%d-%H%M%S}.log"
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with open(out_log, "a", encoding="utf-8") as fh:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "listen-worker", "--wav", str(wav)],
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
            creationflags=flags,
        )
    log("已转后台处理:", out_log.name)


def cmd_dsh_task(args: argparse.Namespace) -> None:
    """后台子进程入口：跑 DSH headless → 结果存 outbox → 回拨念出来。"""
    prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    reply = dispatch(prompt)

    outbox = ROOT / "outbox"
    outbox.mkdir(exist_ok=True)
    reply_file = outbox / f"reply-{datetime.now():%Y%m%d-%H%M%S}.txt"
    reply_file.write_text(reply, encoding="utf-8")
    log("答复已存：", reply_file.name)

    try:
        handle_reply(reply)
    except BaseException as exc:  # 未装 FreeSWITCH 时不要把任务判成失败
        log("回铃失败（答复仍已保存）：", exc)


def cmd_selftest(_args: argparse.Namespace) -> None:
    import wave as wave_mod

    text = "老座机链路自检：现在时间十点三十分，语音合成与识别均正常。"
    log("1/3 合成语音")
    wav = tts_to_wav8k(text, ROOT / "tts" / "selftest.wav")
    log("2/3 检查音频参数")
    with wave_mod.open(str(wav), "rb") as f:
        log(f"    采样率 {f.getframerate()} Hz / 声道 {f.getnchannels()} / 位宽 {f.getsampwidth() * 8} bit")
    log("3/3 回读识别")
    got = transcribe(wav)
    print("\n原文：", text)
    print("识别：", got)
    print("结果：", "✅ 链路通" if got else "❌ 识别为空")


def cmd_chats(args) -> None:
    """列出桌面端会话，供「电话指令路由」挑选目标。"""
    base = bridge_find_url()
    rows = http_json(base + "/dsh-idle-watchdog/api/chats?refresh", timeout=120).get("rows", [])
    rows.sort(key=lambda r: r.get("createdAt", 0), reverse=True)
    rows = rows[: args.limit]
    for i, r in enumerate(rows, 1):
        ts = time.strftime("%m-%d %H:%M", time.localtime(int(r.get("createdAt", 0)) / 1000))
        print(f"[{i}] live={r.get('live')} running={r.get('running')} created={ts}")
        print(f"    id={r.get('sessionId')}")
        print(f"    cwd={r.get('cwd')}")
        print(f"    title={r.get('title')}")
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))


def cmd_route(args) -> None:
    """把电话原话转发到指定会话（chat 支持 id / 唯一前缀 / 标题）。"""
    result = bridge_send(args.text, chat=args.chat)
    print("投递结果：", result)


def main() -> None:
    parser = argparse.ArgumentParser(description="老座机 AI 秘书（ATA + FreeSWITCH）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("selftest", help="无需硬件的自检").set_defaults(func=cmd_selftest)

    p = sub.add_parser("tts", help="文本转 8k wav")
    p.add_argument("--text", required=True)
    p.add_argument("-o", "--out", default="tts/out.wav")
    p.set_defaults(func=lambda a: print(tts_to_wav8k(a.text, a.out)))

    p = sub.add_parser("asr", help="wav 转文本")
    p.add_argument("--wav", required=True)
    p.set_defaults(func=lambda a: print(transcribe(a.wav)))

    p = sub.add_parser("ring", help="让座机振铃并播放 wav")
    p.add_argument("--wav", required=True)
    p.set_defaults(func=lambda a: print(ring_and_play(a.wav)))

    p = sub.add_parser("reply", help="TTS 后立即回铃")
    p.add_argument("--text", required=True)
    p.set_defaults(func=lambda a: handle_reply(a.text))

    p = sub.add_parser("listen", help="录音 → ASR → Agent → TTS → 回铃（挂机钩子调这个）")
    p.add_argument("--wav", required=True)
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("listen-worker", help="内部用：真正的处理进程")
    p.add_argument("--wav", required=True)
    p.set_defaults(func=lambda a: handle_recording(a.wav))

    p = sub.add_parser("ask", help="直接问 Agent（不录音、不回铃），调通后接座机")
    p.add_argument("--text", required=True)
    p.set_defaults(func=lambda a: print(dispatch(a.text)))

    p = sub.add_parser("dsh-task", help="内部用：后台跑 DSH 任务并回拨")
    p.add_argument("--prompt-file", required=True)
    p.set_defaults(func=cmd_dsh_task)

    p = sub.add_parser("chats", help="列出桌面 DSH 会话（供电话指令路由选目标）")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_chats)

    p = sub.add_parser("route", help="把电话原话转发到指定桌面会话")
    p.add_argument("--chat", required=True, help="会话 id / ≥6 位唯一前缀 / 标题")
    p.add_argument("--text", required=True, help="电话原话（转发内容）")
    p.set_defaults(func=cmd_route)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
