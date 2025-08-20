import os, time, json, re, hashlib, requests
from pathlib import Path
from datetime import datetime, timezone

# === Config ===
BOT_TOKEN   = os.environ["BOT_TOKEN"]
CHAT_ID     = os.environ["CHAT_ID"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "90"))  # check every 90s
CACHE_FILE   = Path("seen.json")
UA = {"User-Agent": "SavPoliticianWatcher/2.0 (+telegram-bot)"}

# === Utils ===
def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }, timeout=25)
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
    return hashlib.sha256("||".join("" if p is None else str(p) for p in parts).encode()).hexdigest()

def fmt_amt(lo, hi):
    if lo and hi:
        return f"${lo}–${hi}"
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

# === Source 1: QuiverQuant ===
def fetch_quiver_web():
    url = "https://www.quiverquant.com/congresstrading/"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []
    results = []
    def walk(o):
        if isinstance(o, dict):
            if {"Ticker","Representative","Transaction","Date"}.issubset(o.keys()):
                ticker = (o.get("Ticker") or "").upper()
                pol    = o.get("Representative") or "Unknown"
                side   = (o.get("Transaction") or "").upper()
                date   = o.get("Date") or ""
                lo     = o.get("AmountMin") or None
                hi     = o.get("AmountMax") or None
                uid = mk_id("Quiver", pol, ticker, side, date)
                results.append({
                    "uid": uid, "source": "QuiverQuant", "politician": pol,
                    "ticker": ticker, "side": side, "date": date,
                    "amount_min": lo, "amount_max": hi
                })
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(data)
    return results

# === Source 2: CapitolTrades ===
def fetch_capitol_trades():
    url = "https://www.capitoltrades.com/trades"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    rows = re.findall(
        r'data-ticker="([A-Z.\-]+)".*?data-transaction="(Buy|Sell)".*?data-politician="([^"]+)".*?data-date="([^"]+)"',
        html, flags=re.S
    )
    results = []
    for ticker, side, pol, date in rows[:50]:
        uid = mk_id("Capitol", pol, ticker, side, date)
        results.append({
            "uid": uid, "source": "CapitolTrades", "politician": pol,
            "ticker": ticker.upper(), "side": side.upper(), "date": date,
            "amount_min": None, "amount_max": None
        })
    return results

# === Source 3: Unusual Whales (scrape HTML) ===
def fetch_unusual_whales():
    url = "https://unusualwhales.com/politics"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    rows = re.findall(
        r'data-ticker="([A-Z.\-]+)".*?data-transaction="(Buy|Sell)".*?data-politician="([^"]+)".*?data-date="([^"]+)"',
        html, flags=re.S
    )
    results = []
    for ticker, side, pol, date in rows[:50]:
        uid = mk_id("UW", pol, ticker, side, date)
        results.append({
            "uid": uid, "source": "UnusualWhales", "politician": pol,
            "ticker": ticker.upper(), "side": side.upper(), "date": date,
            "amount_min": None, "amount_max": None
        })
    return results

# === Main loop ===
def main():
    print("Sav Politician Watcher started.")
    send_telegram("✅ Bot is alive and running!")

    seen = load_seen()
    while True:
        try:
            items = []
            try: items.extend(fetch_quiver_web())
            except Exception as e: print("Quiver error:", e)
            try: items.extend(fetch_capitol_trades())
            except Exception as e: print("CapitolTrades error:", e)
            try: items.extend(fetch_unusual_whales())
            except Exception as e: print("UW error:", e)

            pushed = 0
            for it in items:
                if it["uid"] not in seen:
                    send_telegram(alert_text(it))
                    seen.add(it["uid"])
                    pushed += 1
                    time.sleep(0.4)
            if pushed: save_seen(seen)

            print(f"[{now_iso()}] checked {len(items)} items, sent {pushed} alerts.")
        except Exception as e:
            print("Loop error:", e)
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
