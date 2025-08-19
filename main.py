import requests, os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# send a test message when bot starts
requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={CHAT_ID}&text=✅ Bot is alive and running!")import os, time, json, re, hashlib, requests
from pathlib import Path
from datetime import datetime, timezone

# === Config ===
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
POLL_SECONDS = 90  # check every 90s
CACHE_FILE = Path("seen.json")
UA = {"User-Agent": "SavPoliticianWatcher/1.0 (+telegram-bot)"}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True}, timeout=25)
    r.raise_for_status()

def load_seen():
    if CACHE_FILE.exists():
        try:
            return set(json.loads(CACHE_FILE.read_text()))
        except Exception:
            return set()
    return set()

def save_seen(s):
    CACHE_FILE.write_text(json.dumps(list(s)))

def mk_id(*parts):
    return hashlib.sha256("||".join(map(lambda x: "" if x is None else str(x), parts)).encode()).hexdigest()

def fmt_amt(min_v, max_v):
    if min_v and max_v:
        return f"${min_v}–${max_v}"
    return "N/A"

def alert_text(item):
    return (
        "⚠️ Politician Trade Filed\n"
        f"👤 {item.get('politician','Unknown')}\n"
        f"🎯 {item.get('ticker','N/A')} | {item.get('side','?')}\n"
        f"💰 Amount: {fmt_amt(item.get('amount_min'), item.get('amount_max'))}\n"
        f"📅 Date: {item.get('date','')}\n"
        f"🏛️ Source: {item.get('source','')}\n"
        f"⏱️ {now_iso()}"
    )

def fetch_quiver_web():
    url = "https://www.quiverquant.com/congresstrading/"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html, re.S)
    if not m:
        return []
    try:
        next_json = json.loads(m.group(1))
    except Exception:
        return []
    results = []
    def walk(obj):
        if isinstance(obj, dict):
            if {"Ticker","Representative","Transaction","Date"}.issubset(set(obj.keys())):
                ticker = (obj.get("Ticker") or "").upper()
                pol = obj.get("Representative") or "Unknown"
                side = (obj.get("Transaction") or "").upper()
                date = obj.get("Date") or ""
                uid = mk_id("QuiverWeb", pol, ticker, side, date)
                results.append({
                    "uid":uid,"source":"Quiver (web)","politician":pol,
                    "ticker":ticker,"side":side,"date":date,
                    "amount_min":obj.get("AmountMin"),"amount_max":obj.get("AmountMax")
                })
            for v in obj.values(): walk(v)
        elif isinstance(obj, list):
            for v in obj: walk(v)
    walk(next_json)
    return results

def fetch_capitol_trades():
    url = "https://www.capitoltrades.com/trades"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    rows = re.findall(r'data-ticker="([A-Z.\-]+)".*?data-transaction="(Buy|Sell)".*?data-politician="([^"]+)".*?data-date="([^"]+)"', html, re.S)
    results = []
    for ticker, side, pol, date in rows[:50]:
        uid = mk_id("CapitolTrades", pol, ticker, side, date)
        results.append({"uid":uid,"source":"CapitolTrades","politician":pol,"ticker":ticker.upper(),
                        "side":side.upper(),"date":date,"amount_min":None,"amount_max":None})
    return results

def main():
    print("Sav Politician Watcher started.")
    seen = load_seen()
    while True:
        try:
            items = fetch_quiver_web() + fetch_capitol_trades()
            for it in items:
                if it["uid"] not in seen:
                    send_telegram(alert_text(it))
                    seen.add(it["uid"])
            save_seen(seen)
            print(f"[{now_iso()}] Checked, total seen={len(seen)}")
        except Exception as e:
            print("Error:", e)
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
