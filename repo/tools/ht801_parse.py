import re
import sys


def strip_tags(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


def parse_rows(html):
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        items = []
        for m in re.finditer(r"<input([^>]*)>", row, flags=re.I):
            attrs = m.group(1)
            def a(name):
                mm = re.search(name + r"=\"([^\"]*)\"", attrs, flags=re.I)
                return mm.group(1) if mm else ""
            items.append({"tag": "input", "name": a("name"), "type": (a("type") or "text").lower(),
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
            cur = next((o["value"] for o in opts if o["selected"]), "")
            items.append({"tag": "select", "name": mm.group(1) if mm else "", "type": "select",
                          "value": cur, "options": opts})
        label = strip_tags(row)
        if items:
            rows.append({"label": label[:150], "items": items})
    return rows


if __name__ == "__main__":
    path = sys.argv[1]
    kw = sys.argv[2] if len(sys.argv) > 2 else None
    html = open(path, encoding="utf-8", errors="replace").read()
    for r in parse_rows(html):
        if kw and kw.lower() not in r["label"].lower() and not any(kw.lower() in (i["name"] or "").lower() for i in r["items"]):
            continue
        for i in r["items"]:
            if not i["name"]:
                continue
            if i["tag"] == "select":
                opts = " | ".join(f"{o['value']}={o['text']}" for o in i["options"])
                print(f"{r['label'][:80]!r}\n    [{i['name']}] select cur={i['value']!r}  opts: {opts}")
            else:
                print(f"{r['label'][:80]!r}\n    [{i['name']}] {i['type']} = {i['value']!r} checked={i['checked']}")
