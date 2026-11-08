"""Diagnostyka łącza: ping, jitter, utrata pakietów i DNS -> SQLite -> wykres.
System obsługuje systemy Unix/Linux/Mac oraz Windows

Użycie:  python diag.py run     # pomiary co INTERVAL sekund (Ctrl+C kończy)
         python diag.py plot    # rysuje wykres z zapisanych danych
"""
import re, sqlite3, statistics, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

import platform
import dns.resolver
import matplotlib.pyplot as plt
import pandas as pd

# Constant parameters
TARGETS = ["google.com", "cloudflare.com", "github.com"]
INTERVAL = 4  # sekundy między seriami pomiarów
PINGS = 5      # pakietów na jeden pomiar
DB = "diag.db"

# Single measurement of network connection
def measure(host):
    t = time.time()

    # Work speed of DNS (or does it even work)
    try:
        dns.resolver.resolve(host)
        dns_ms = (time.time() - t) * 1000
    except Exception:
        dns_ms = None

    # support for Windows operation system (correction of flag)
    is_windows = platform.system() == "Windows"
    ping_flag = "-n" if is_windows else "-c"

    # ping
    try:
        out = subprocess.run(["ping", ping_flag, str(PINGS), host], capture_output=True, text=True, timeout=30).stdout
    except subprocess.TimeoutExpired:
        out = ""
    rtts = [float(x) for x in re.findall(r"time[=<]([\d.]+)", out)]
    
    # packet loss
    if is_windows:
        loss = re.search(r"([\d.]+)% loss", out)
    else:
        loss = re.search(r"([\d.]+)% packet loss", out)

    return (time.time(), host,
            statistics.mean(rtts) if rtts else None,
            statistics.pstdev(rtts) if rtts else None,  # jitter = odchylenie std. RTT
            float(loss[1]) if loss else 100.0,
            dns_ms)

# loop that acquires measurement data and stores it in a database file
def run():
    db = sqlite3.connect(DB)
    db.execute("CREATE TABLE IF NOT EXISTS m (ts REAL, host TEXT, ping REAL, jitter REAL, loss REAL, dns REAL)")

    # multi-thread data downloading
    while True:
        with ThreadPoolExecutor(len(TARGETS)) as pool:
            rows = list(pool.map(measure, TARGETS))
        db.executemany("INSERT INTO m VALUES (?,?,?,?,?,?)", rows)
        db.commit()

        # displaying a notification about measurements (to provide visibility into the operation)
        for r in rows:
            print(time.strftime("%H:%M:%S"), r[1], *("-" if v is None else round(v, 1) for v in r[2:]))
        time.sleep(INTERVAL)

# generating a chart of measurements from the current database
def plot():
    df = pd.read_sql("SELECT * FROM m", sqlite3.connect(DB))
    df["ts"] = pd.to_datetime(df["ts"], unit="s")
    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(10, 8))
    for ax, (col, label) in zip(axes, [("ping", "Ping [ms]"), ("jitter", "Jitter [ms]"),
                                       ("loss", "Packet loss [%]"), ("dns", "DNS [ms]")]):
        for host, g in df.groupby("host"):
            ax.plot(g["ts"], g[col], marker=".", label=host)
        ax.set_ylabel(label)
        ax.grid(alpha=.3)
    axes[0].legend()
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig("diag.png")
    plt.show()


if __name__ == "__main__":
    {"run": run, "plot": plot}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
