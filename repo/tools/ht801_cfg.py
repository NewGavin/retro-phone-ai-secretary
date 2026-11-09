"""HT801 web 配置工具（curl 负责 HTTP 会话，Python 负责解析与提交）。

用法：
    py tools/ht801_cfg.py status          # 读 Basic Settings 摘要
    py tools/ht801_cfg.py set-ip          # 改为静态 IP 10.13.162.60/23，网关 10.13.163.254
    py tools/ht801_cfg.py reboot          # 重启
说明：Grandstream 的会话在短时间过期，每个命令都会重新登录。
"""
import base64
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
COOKIE_JAR = LOG_DIR / "ht801-cookies.txt"
BASE = "http://10.13.162.60"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

TARGET = {
    "P8": "1",                     # 1 = statically configured
    "P9": "10", "P10": "13", "P11": "162", "P12": "60",
    "P13": "255", "P14": "255", "P15": "254", "P16": "0",
    "P17": "10", "P18": "13", "P19": "163", "P20": "254",
    "P21": "223", "P22": "5", "P23": "5", "P24": "5",
}


def curl(args, timeout=40):
    cmd = ["curl.exe", "-sS", "-m", str(timeout), "-A", UA] + args
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"curl 失败({p.returncode}): {p.stderr.decode('utf-8', 'replace')[:300]}")
    return p.stdout.decode("utf-8", "replace")


def get(path, timeout=40):
    return curl(["-b", str(COOKIE_JAR), "-c", str(COOKIE_JAR), BASE + path], timeout)


def post(path, fields, timeout=40):
    args = ["-b", str(COOKIE_JAR), "-c", str(COOKIE_JAR), "-X", "POST", "-H",
            "Content-Type: application/x-www-form-urlencoded", "-H",
            f"Referer: {BASE}/cgi-bin/config2", BASE + path]
    for k, v in fields.items():
        args += ["--data-urlencode", f"{k}={v}"]
    return curl(args, timeout)


def login():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_JAR.unlink(missing_ok=True)
    page = get("/cgi-bin/login")
    m = re.search(r'name="?session_token"?[^>]*value="([^"]*)"', page)
    token = m.group(1) if m else ""
    b64 = base64.b64encode(b"admin").decode()
    resp = post("/cgi-bin/dologin", {
        "session_token": token, "username": "admin", "P2": b64,
        "Login": "Login", "gnkey": "0b82",
    })
    if "STATUS" not in resp and "MAC" not in resp:
        raise RuntimeError("登录失败，响应片段：" + re.sub(r"\s+", " ", resp)[:200])
    return resp


def form_fields(html, form_name):
    """取指定 form 内的控件默认值：text/hidden 取 value，radio/checkbox 只取 checked，select 取 selected。"""
    m = re.search(r"<form[^>]*name=[\"']?%s[\"']?[^>]*>(.*?)</form>" % re.escape(form_name), html, re.S | re.I)
    if not m:
        raise RuntimeError(f"页面里找不到 form {form_name}")
    seg = m.group(1)
    fields = {}
    for tag in re.finditer(r"<input[^>]*>", seg, re.I):
        t = tag.group(0)
        name = re.search(r"name=[\"']?([A-Za-z0-9_]+)", t, re.I)
        if not name:
            continue
        name = name.group(1)
        typ = (re.search(r"type=[\"']?([A-Za-z]+)", t, re.I) or [None, "text"])[1].lower()
        val = re.search(r"value=[\"']?([^\"'>\s]*)", t, re.I)
        val = val.group(1) if val else ""
        if typ in ("radio", "checkbox"):
            if "checked" in t.lower():
                fields[name] = val
        elif typ == "submit":
            continue
        else:
            fields[name] = val
    for sel in re.finditer(r"<select[^>]*name=[\"']?([A-Za-z0-9_]+)[\"']?[^>]*>(.*?)</select>", seg, re.S | re.I):
        name, inner = sel.group(1), sel.group(2)
        cur = ""
        for opt in re.finditer(r"<option([^>]*)>(.*?)</option>", inner, re.S | re.I):
            attrs = opt.group(1)
            v = re.search(r"value=[\"']?([^\"'>\s]*)", attrs, re.I)
            v = v.group(1) if v else re.sub(r"<[^>]+>", "", opt.group(2)).strip()
            if "selected" in attrs.lower():
                cur = v
        fields[name] = cur
    return fields


def parse_basic(html):
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        txt = re.sub(r"<[^>]+>", " ", row)
        txt = re.sub(r"\s+", " ", txt).strip()
        names = re.findall(r"name=[\"']?(P\d+)", row, re.I)
        if names and txt:
            rows.append((txt[:90], names))
    return rows


def cmd_status():
    login()
    html = get("/cgi-bin/config2")
    LOG_DIR.joinpath("ht801-config2.html").write_text(html, encoding="utf-8")
    fields = form_fields(html, "basic_form")
    print("=== 关键字段 ===")
    for k in ["P8", "P9", "P10", "P11", "P12", "P13", "P14", "P15", "P16",
              "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24"]:
        print(f"  {k} = {fields.get(k)!r}")
    print("=== 页面行（含 P 字段的）===")
    for label, names in parse_basic(html):
        if any(n in TARGET or n in ("P8",) for n in names):
            print(f"  {label} :: {names}")


def cmd_set_ip():
    login()
    html = get("/cgi-bin/config2")
    fields = form_fields(html, "basic_form")
    if "session_token" not in fields:
        raise RuntimeError("缺少 session_token，登录态可能失效")
    before = {k: fields.get(k) for k in TARGET}
    fields.update(TARGET)
    fields["update"] = "Update"
    resp = post("/cgi-bin/update", fields)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp))
    print("提交前:", before)
    print("提交后:", {k: fields.get(k) for k in TARGET})
    print("响应片段:", text[:300])
    ok = any(w in text for w in ("Updated", "成功", "成功", "Settings"))
    print("疑似成功:", ok, "| 响应长度:", len(resp))
    return ok


def cmd_dump(page):
    login()
    html = get("/cgi-bin/" + page)
    LOG_DIR.joinpath("ht801-" + page.replace("/", "_") + ".html").write_text(html, encoding="utf-8")
    print("页面长度:", len(html))
    kw = sys.argv[2].lower() if len(sys.argv) > 2 else ""
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", row)).strip()
        names = re.findall(r"name=[\"']?([A-Za-z0-9_]+)", row)
        if names and (not kw or kw in txt.lower()):
            print(f"  {txt[:100]} :: {names}")


FXS_TARGET = {
    "P271": "1",            # Account Active = Yes
    "P47": "10.13.162.128",  # Primary SIP Server
    "P967": "",             # Failover SIP Server
    "P48": "",              # Outbound Proxy
    "P35": "100",           # SIP User ID
    "P36": "100",           # Authenticate ID
    "P34": "phone1234",     # Authenticate Password
    "P3": "zuoji",          # Name
    "P71": "6001",          # Offhook Auto-Dial
    "P40": "5060",          # Local SIP Port
}


def cmd_fxs_status():
    login()
    html = get("/cgi-bin/config_a1")
    LOG_DIR.joinpath("ht801-config_a1.html").write_text(html, encoding="utf-8")
    f = form_fields(html, "a1")
    for k in ["P271", "P47", "P967", "P48", "P35", "P36", "P3", "P71", "P40", "P52", "P57"]:
        print(f"  {k} = {f.get(k)!r}")
    print("  P34 已设置:", "有值" if f.get("P34") else "空（页面不回显）")


def cmd_set_fxs():
    login()
    html = get("/cgi-bin/config_a1")
    f = form_fields(html, "a1")
    f.update(FXS_TARGET)
    f["update"] = "Update"
    resp = post("/cgi-bin/update", f)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp))
    print("响应片段:", txt[:200])
    print("响应长度:", len(resp))
    return resp


def cmd_reboot():
    login()
    html = get("/cgi-bin/config2")
    rs = form_fields(html, "rs_form")
    rs.setdefault("session_token", "")
    rs.setdefault("gnkey", "0b82")
    resp = post("/cgi-bin/rs", rs)
    print("reboot 响应长度:", len(resp), "| 片段:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp))[:200])


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "dump":
        cmd_dump(sys.argv[2])
    else:
        {"status": cmd_status, "set-ip": cmd_set_ip, "reboot": cmd_reboot,
         "set-fxs": cmd_set_fxs, "fxs-status": cmd_fxs_status}[action]()
