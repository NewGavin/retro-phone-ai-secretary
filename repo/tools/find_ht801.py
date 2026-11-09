# -*- coding: utf-8 -*-
"""在局域网里找 Grandstream HT801（或其它 ATA）的 Web 管理页。

用法：python tools/find_ht801.py
原理：解析本机 IPv4 + 子网掩码 → 并发扫 80/443/8080 → 看 HTTP 响应里有没有 Grandstream/HT8。
辅助：打印 ARP 表里 Grandstream OUI（00:0B:82）的设备。
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import subprocess
import urllib.request

TIMEOUT = 0.6
PORTS = (80, 443, 8080)


def local_ipv4_and_prefix() -> tuple[str, int]:
    out = subprocess.run(["ipconfig"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    ip = mask = None
    for line in out.splitlines():
        m = re.search(r"IPv4.*?:\s*([\d.]+)", line)
        if m and "169.254" not in m.group(1) and not m.group(1).startswith("127."):
            cur_ip = m.group(1)
        m = re.search(r"Subnet Mask.*?:\s*([\d.]+)|子网掩码.*?:\s*([\d.]+)", line)
        if m:
            cur_mask = m.group(1) or m.group(2)
            if cur_ip and cur_mask:
                ip, mask = cur_ip, cur_mask
                break
    if not ip:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        mask = "255.255.255.0"
    prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    return ip, prefix


async def probe(ip: str, port: int, sem: asyncio.Semaphore) -> tuple[str, int] | None:
    async with sem:
        try:
            fut = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(fut, timeout=TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return (ip, port)
        except Exception:
            return None


def http_title(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            body = r.read(64 * 1024).decode("utf-8", "replace")
        m = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        return title
    except Exception as e:
        return f"(无法读取: {e})"


async def main() -> None:
    ip, prefix = local_ipv4_and_prefix()
    net = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
    print(f"本机 {ip}/{prefix} → 扫描网段 {net}")

    sem = asyncio.Semaphore(400)
    targets = [str(h) for h in net.hosts() if str(h) != ip]
    jobs = [probe(h, p, sem) for h in targets for p in PORTS]
    print(f"扫描 {len(targets)} 台主机 × {len(PORTS)} 端口 …")
    results = [r for r in await asyncio.gather(*jobs) if r]

    print(f"开放端口: {len(results)} 个")
    found = []
    for host, port in results:
        scheme = "https" if port == 443 else "http"
        title = http_title(f"{scheme}://{host}:{port}/") if port != 443 else ""
        print(f"  {host}:{port}  {title}")
        if re.search(r"grandstream|HT8\d\d|gateway", title, re.I):
            found.append((host, port, title))

    print("\n=== 判定 ===")
    if found:
        for host, port, title in found:
            print(f"✅ 很可能是 ATA: http://{host}:{port}/  ({title})")
    else:
        print("未在开放的 Web 页面里发现 Grandstream 字样。")
        print("看下 ARP 表里有没有 Grandstream 的 MAC 前缀 00:0B:82：")
        arp = subprocess.run(["arp", "-a"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        hits = [ln for ln in arp.splitlines() if "00-0b-82" in ln.lower() or "00:0b:82" in ln.lower()]
        print("\n".join(hits) if hits else "  (ARP 里也没有)")


if __name__ == "__main__":
    asyncio.run(main())
