"""Minimal DHCP listener / targeted responder for HT801 bring-up.

Modes:
  --listen SECONDS            listen only, log DISCOVER/REQUEST from any client
  --serve --mac AA-BB-CC-DD-EE-FF [--ip 10.13.162.60] [--seconds 120]
                             reply OFFER/ACK only to that MAC

Why targeted: the office LAN has no DHCP server; answering only one known MAC
avoids handing addresses to other devices.
"""
import argparse
import binascii
import socket
import struct
import sys
import time

MAGIC = b"\x63\x82\x53\x63"
MSG_DISCOVER, MSG_OFFER, MSG_REQUEST, MSG_ACK = 1, 2, 3, 5


def parse(pkt):
    if len(pkt) < 240 or pkt[236:240] != MAGIC:
        return None
    xid, flags = struct.unpack("!I", pkt[4:8])[0], struct.unpack("!H", pkt[10:12])[0]
    chaddr = pkt[28:44]
    opts, i = {}, 240
    while i < len(pkt):
        code = pkt[i]
        i += 1
        if code == 255:
            break
        if code == 0:
            continue
        ln = pkt[i]
        i += 1
        opts[code] = pkt[i:i + ln]
        i += ln
    mtype = opts.get(53, b"\x00")[0]
    return xid, flags, chaddr, mtype, opts


def mac_str(chaddr):
    h = binascii.hexlify(chaddr[:6]).decode()
    return "-".join(h[i:i + 2] for i in range(0, 12, 2)).upper()


def build_reply(xid, flags, chaddr, yiaddr, mtype, server, mask, gw, dns, lease=3600):
    pkt = struct.pack(
        "!BBBBIHH4s4s4s4s16s64s128s",
        2, 1, 6, 0, xid, 0, flags,
        b"\x00" * 4, socket.inet_aton(yiaddr), socket.inet_aton(server), b"\x00" * 4,
        chaddr, b"\x00" * 64, b"\x00" * 128,
    )
    pkt += MAGIC
    def opt(c, v):
        return bytes([c, len(v)]) + v
    pkt += opt(53, bytes([mtype]))
    pkt += opt(54, socket.inet_aton(server))
    pkt += opt(51, struct.pack("!I", lease))
    pkt += opt(1, socket.inet_aton(mask))
    pkt += opt(3, socket.inet_aton(gw))
    pkt += opt(6, socket.inet_aton(dns))
    pkt += b"\xff"
    return pkt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=0)
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--mac", default="")
    ap.add_argument("--ip", default="10.13.162.60")
    ap.add_argument("--server", default="10.13.162.128")
    ap.add_argument("--mask", default="255.255.254.0")
    ap.add_argument("--gw", default="10.13.163.254")
    ap.add_argument("--dns", default="10.13.163.254")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--log", default="")
    args = ap.parse_args()

    logf = open(args.log, "a", encoding="utf-8") if args.log else None
    def log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        if logf:
            logf.write(line + "\n")
            logf.flush()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("", 67))
    s.settimeout(1.0)
    log(f"dhcp tool start mode={'serve' if args.serve else 'listen'} mac={args.mac} ip={args.ip}")

    deadline = time.time() + (args.seconds if (args.serve or args.listen) else 120)
    seen = set()
    while time.time() < deadline:
        try:
            pkt, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError as e:
            log(f"recv error {e}")
            break
        parsed = parse(pkt)
        if not parsed:
            continue
        xid, flags, chaddr, mtype, opts = parsed
        mac = mac_str(chaddr)
        if mac in seen and mtype == MSG_REQUEST:
            pass
        seen.add(mac)
        kind = {1: "DISCOVER", 3: "REQUEST"}.get(mtype, f"type{mtype}")
        log(f"{kind} from {mac} @{addr[0]} xid={xid:08x}")
        if not args.serve:
            continue
        if args.mac and mac.replace("-", "").upper() != args.mac.replace("-", "").replace(":", "").upper():
            log(f"  ignore {mac} (not target)")
            continue
        if mtype == MSG_DISCOVER:
            reply = build_reply(xid, flags, chaddr, args.ip, MSG_OFFER, args.server, args.mask, args.gw, args.dns)
            s.sendto(reply, ("255.255.255.255", 68))
            log(f"  OFFER {args.ip} -> {mac}")
        elif mtype == MSG_REQUEST:
            reply = build_reply(xid, flags, chaddr, args.ip, MSG_ACK, args.server, args.mask, args.gw, args.dns)
            s.sendto(reply, ("255.255.255.255", 68))
            log(f"  ACK {args.ip} -> {mac}")
    log("dhcp tool exit")


if __name__ == "__main__":
    main()
