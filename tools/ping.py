#!/usr/bin/env python3
"""ping.py "text"  -> posts into Yusuf's Blueprint Telegram thread (32877) as Builder.
Token is read from the blahbot profile .env and never printed."""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

H = Path.home() / ".hermes"
CHAT, THREAD = "6352851713", "32877"


def token():
    for line in (H / "profiles" / "blahbot" / ".env").read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("no token")


text = " ".join(sys.argv[1:]).replace("\u2014", ",").replace("\u2013", ",")
if not text:
    sys.exit(__doc__)
data = urllib.parse.urlencode({"chat_id": CHAT, "message_thread_id": THREAD, "text": text}).encode()
try:
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token()}/sendMessage", data, timeout=20))
except Exception as e:
    sys.exit(f"send failed: {type(e).__name__}")
if not r.get("ok"):
    sys.exit(f"send failed: {r.get('description')}")
with open(H / "shared" / "tell_yusuf.log", "a") as f:
    f.write(time.strftime("%F %T ") + "blahbot: " + text.replace("\n", " ")[:600] + "\n")
print("sent, message_id", r["result"]["message_id"])
