#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""FreeSWITCH 安装后体检：一条命令看清「哪一环没通」。

用法：
    .\\.venv\\Scripts\\python.exe tools\\doctor.py
    .\\.venv\\Scripts\\python.exe tools\\doctor.py --full   # 额外跑一次 TTS/ASR 自检
"""
from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

import yaml  # noqa: E402

CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}

OK, BAD, WARN = "✅", "❌", "⚠️ "


def cfg(path: str, default=None):
    node = CONFIG
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def find_fs_cli() -> str | None:
    candidates = [
        str(cfg("pbx.fs_cli", "")),
        r"C:\FreeSWITCH\fs_cli.exe",
        r"C:\Program Files\FreeSWITCH\fs_cli.exe",
        shutil.which("fs_cli") or "",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "文件不存在"
    except subprocess.TimeoutExpired:
        return 124, "超时（FreeSWITCH 可能没启动）"


def fs(cli: str, command: str) -> tuple[int, str]:
    return run([cli, "-x", command])


def port_listening(port: int) -> bool:
    """粗查本机是否有进程在监听该端口（含 UDP，靠 netstat 文本）。"""
    code, out = run(["netstat", "-ano"], timeout=20)
    if code != 0:
        return False
    needle = f":{port} "
    return any(needle in line or line.rstrip().endswith(f":{port}") for line in out.splitlines())


def section(title: str) -> None:
    print(f"\n—— {title} ——")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="额外跑 TTS/ASR 自检")
    args = parser.parse_args()

    problems: list[str] = []
    print("老座机链路体检", time.strftime("%Y-%m-%d %H:%M:%S"))

    section("1. 运行环境")
    py_ok = sys.version_info >= (3, 9)
    print(f"{OK if py_ok else BAD} Python {sys.version.split()[0]}")
    if not py_ok:
        problems.append("Python 版本过低")

    ffmpeg = cfg("ffmpeg", "ffmpeg")
    print(f"{OK if shutil.which(ffmpeg) else BAD} ffmpeg: {shutil.which(ffmpeg) or '未找到'}")
    if not shutil.which(ffmpeg):
        problems.append("ffmpeg 不在 PATH，TTS 转 8k 会失败")

    rec = Path(str(cfg("paths.recordings", "C:/fs/recordings")))
    try:
        rec.mkdir(parents=True, exist_ok=True)
        probe = rec / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print(f"{OK} 录音目录可写: {rec}")
    except PermissionError:
        # 受限会话（如低完整性沙箱）会写不进去；FS 服务以 SYSTEM 运行，仍能正常录音
        if rec.is_dir():
            print(f"{WARN} 当前会话对录音目录无写权限: {rec}")
            print("   → 目录存在；FreeSWITCH 服务以 SYSTEM 运行，录音不受影响")
        else:
            print(f"{BAD} 录音目录不可用: {rec}")
            problems.append("录音目录不可用，检查权限或路径")
    except Exception as exc:
        print(f"{BAD} 录音目录不可写: {rec} ({exc})")
        problems.append("录音目录不可写，检查权限或路径")

    section("2. FreeSWITCH")
    cli = find_fs_cli()
    if not cli:
        print(f"{BAD} 找不到 fs_cli.exe")
        print("   期望位置：C:\\FreeSWITCH\\fs_cli.exe 或 C:\\Program Files\\FreeSWITCH\\fs_cli.exe")
        print("   修法：用 MSI 装到 C:\\FreeSWITCH 即可被自动识别；装别处就改 config.yaml 的 pbx.fs_cli")
        problems.append("未安装 FreeSWITCH（或路径不对）")
    else:
        print(f"{OK} fs_cli: {cli}")
        code, out = fs(cli, "status")
        up = "UP" in out and "0 years" not in out.replace("0 years, 0 days, 0 hours, 0 minutes", "X")
        if code == 0 and ("UP" in out or "FreeSWITCH" in out):
            head = out.strip().splitlines()[0] if out.strip() else ""
            print(f"{OK} 内核状态: {head[:100]}")
        else:
            print(f"{BAD} 内核未响应: {out.strip()[:200]}")
            problems.append("FreeSWITCH 服务没起来（Start-Service FreeSWITCH）")

        code, out = fs(cli, "sofia status")
        running = "RUNNING" in out.upper()
        print(f"{OK if running else BAD} SIP profile: {'RUNNING' if running else out.strip()[:200]}")
        if not running:
            problems.append("SIP profile 未 RUNNING（检查 conf/sip_profiles/internal.xml 与 IP）")

        # 分机挂在 domain 下（默认是本机 IP），不是挂在 "default" 分组名下
        _, dom_out = fs(cli, "global_getvar domain")
        domain = (dom_out.strip().splitlines() or [""])[0].strip() or "default"
        code, out = fs(cli, f"user_exists id 100 {domain}")
        exists = "true" in out.lower()
        print(f"{OK if exists else BAD} 分机 100（domain={domain}）: {'已加载' if exists else '不存在（没拷 100.xml 或没 reloadxml）'}")
        if not exists:
            problems.append("分机 100 未加载：拷 conf/directory/default/100.xml 后 reloadxml")

        # 用 xml_locate 查运行时 XML；show dialplan 只会列出拨号模块
        code, out = fs(cli, "xml_locate dialplan")
        has_6001 = "6001" in out
        print(f"{OK if has_6001 else BAD} 拨号计划 6001: {'存在' if has_6001 else '缺失（没拷 01_oldphone.xml 或没 reloadxml）'}")
        if not has_6001:
            problems.append("dialplan 6001 缺失：拷 conf/dialplan/default/01_oldphone.xml 后 reloadxml")

    section("3. 网络")
    for port, label in ((5060, "SIP"), (16384, "RTP 起始")):
        listening = port_listening(port)
        print(f"{OK if listening else WARN} UDP {port} ({label}): {'有监听' if listening else '未检测到（FS 没启动时正常）'}")
    ip = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    print(f"{OK if ip else WARN} 本机内网 IP: {ip or '未取到'}")
    if ip:
        print(f"   → HT801 的 SIP Server 要填 {ip}:5060")

    # 多网卡/VPN 是 Windows 上 FreeSWITCH 最常见的坑：FS 可能绑到错的那块网卡
    code, out = run(["ipconfig"], timeout=15)
    ipv4s = []
    for line in out.splitlines():
        if "IPv4" in line and ":" in line:
            addr = line.split(":")[-1].strip()
            if addr and addr not in ipv4s:
                ipv4s.append(addr)
    if len(ipv4s) > 1:
        print(f"{WARN} 检测到多块网卡/VPN：{', '.join(ipv4s)}")
        print("   → 如果 HT801 注册不上，在 conf\\vars.xml 里把 local_ip_v4 写死成座机同网段的那个 IP")

    section("4. 音频链路自检")
    if args.full:
        code, out = run([sys.executable, str(ROOT / "oldphone.py"), "selftest"], timeout=300)
        tail = "\n".join(out.strip().splitlines()[-3:])
        print(out.strip())
        if "链路通" not in out:
            problems.append("TTS/ASR 自检失败")
    else:
        print("（加 --full 可跑 TTS→8k→ASR 自检）")

    print("\n================ 结论 ================")
    if problems:
        print(f"{BAD} 有 {len(problems)} 项待处理：")
        for i, p in enumerate(problems, 1):
            print(f"  {i}. {p}")
    else:
        print(f"{OK} 全部通过。下一步：软电话注册 100，拨 6001 说一句话，挂机看回铃。")


if __name__ == "__main__":
    main()
