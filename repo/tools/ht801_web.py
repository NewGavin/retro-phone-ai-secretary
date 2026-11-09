"""Small HTTP client for the HT801 web UI (stdlib only).

Commands:
  dump <page>            print label -> field mapping for a config page
  get <page>             print raw form fields (name=value)
  apply <page> <json>    POST form fields, overridden by the JSON dict
  reboot                 POST /cgi-bin/reboot
"""
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request

BASE = "http://10.13.162.60"
CJ = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CJ))


def req(path, data=None, timeout=25):
    url = BASE + path
    if data is not None:
        body = urllib.parse.urlencode(data, doseq=True).encode()
        r = urllib.request.Request(url, data=body, method="POST")
        r.add_header("Content-Type", "application/x-www-form-urlencoded")
    else:
        r = urllib.request.Request(url)
    r.add_header("User-Agent", "Mozilla/5.0")
    with OPENER.open(r, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def login(pwd="admin"):
    import base64
    req("/cgi-bin/login")
    body = req("/cgi-bin/dologin", {
        "session_token": "",
        "username": "admin",
        "P2": base64.b64encode(pwd.encode()).decode(),
        "Login": "\u767b\u5f55",
        "gnkey": "0b82",
    })
    if "\u5bc6\u7801\u9519\u8bef" in body:
        raise SystemExit("login failed: wrong password")
    return body


def strip_tags(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = txt.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", txt).strip()


def parse_form(html):
    """Return list of rows: dict(label, inputs=[{name,type,value,options}])"""
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        inputs = []
        for m in re.finditer(r"<input([^>]*)>", row, flags=re.I):
            attrs = m.group(1)
            def a(name):
                mm = re.search(name + r"=\"([^\"]*)\"", attrs, flags=re.I)
                return mm.group(1) if mm else ""
            inputs.append({"tag": "input", "name": a("name"), "type": (a("type") or "text").lower(),
                           "value": a("value"), "checked": "checked" in attrs.lower()})
        for m in re.finditer(r"<select([^>]*)>(.*?)</select>", row, flags=re.S | re.I):
            attrs, inner = m.group(1), m.group(2)
            mm = re.search(r"name=\"([^\"]*)\"", attrs, flags=re.I)
            opts = []
            for om in re.finditer(r"<option([^>]*)>(.*?)</option>", inner, flags=re.S | re.I):
                oattrs, otext = om.group(1), om.group(2)
                ov = re.search(r"value=\"([^\"]*)\"", oattrs, flags=re.I)
                opts.append({"value": ov.group(1) if ov else strip_tags(otext), "text": strip_tags(otext),
                             "selected": "selected" in oattrs.lower()})
            inputs.append({"tag": "select", "name": mm.group(1) if mm else "", "type": "select",
                           "value": (next((o["value"] for o in opts if o["selected"]), opts[0]["value"] if opts else "")),
                           "options": opts})
        label = strip_tags(row)
        if inputs:
            rows.append({"label": label[:120], "inputs": inputs})
    return rows


def dump(page, keyword=None):
    html = req("/cgi-bin/" + page)
    for r in parse_form(html):
        if keyword and keyword.lower() not in r["label"].lower():
            continue
        for i in r["inputs"]:
            if not i["name"]:
                continue
            if i["tag"] == "select":
                opts = " | ".join(f"{o['value']}={o['text']}" for o in i["options"])
                print(f"{r['label'][:70]!r} [{i['name']}] select cur={i['value']!r} opts: {opts}")
            else:
                print(f"{r['label'][:70]!r} [{i['name']}] {i['type']} = {i['value']!r}")
    return html


def collect(html):
    d = {}
    for r in parse_form(html):
        for i in r["inputs"]:
            if not i["name"]:
                continue
            if i["tag"] == "input" and i["type"] in ("text", "hidden", "password", "radio", "checkbox"):
                if i["type"] in ("radio", "checkbox") and not i["checked"]:
                    continue
                d[i["name"]] = i["value"]
            elif i["tag"] == "select":
                d[i["name"]] = i["value"]
    return d


def apply(page, overrides):
    html = req("/cgi-bin/" + page)
    fields = collect(html)
    fields.update(overrides)
    fields.setdefault("session_token", "")
    out = req("/cgi-bin/update", fields)
    print("POST /cgi-bin/update ->", len(out), "bytes; changed:", list(overrides))
    for kw in ("\u5bc6\u7801\u9519\u8bef", "error", "\u9519\u8bef", "success", "\u6210\u529f"):
        if kw in out:
            print("response contains:", kw)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"
    login()
    if cmd == "dump":
        page = sys.argv[2] if len(sys.argv) > 2 else "config2"
        kw = sys.argv[3] if len(sys.argv) > 3 else None
        dump(page, kw)
    elif cmd == "get":
        page = sys.argv[2]
        html = req("/cgi-bin/" + page)
        print(json.dumps(collect(html), ensure_ascii=False, indent=1))
    elif cmd == "apply":
        page = sys.argv[2]
        overrides = json.loads(sys.argv[3])
        apply(page, overrides)
    elif cmd == "reboot":
        print(req("/cgi-bin/reboot", {})[:300])
    else:
        raise SystemExit("unknown cmd")
