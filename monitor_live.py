"""Walk-forward live monitor for the fade-the-shock strategy on Polymarket.

On each run:
  1. Fetch top active markets (price 0.10-0.90).
  2. For each market pull recent CLOB history (last ~1 week, hourly).
  3. Detect fresh shocks: |price_now - price_6h_ago| >= THRESHOLD.
  4. Open a paper position on the fade side if no open position exists on that token.
  5. Close any open position whose target_close_ts has passed, recording PnL.
  6. Append a run-summary to data/monitor_log.jsonl.

State is persisted to data/paper_positions.json (full list of positions, rewritten each run).

Intended to run hourly via GitHub Actions or a local scheduler.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from polymarket_client import PolymarketClient

# --- strategy parameters (tuned from backtest_oos.py) ---
THRESHOLD = 0.15         # |6h move| required to open a position
HORIZON_HOURS = 24       # hold for 24h after open
PRICE_MIN = 0.10
PRICE_MAX = 0.90
MAX_MARKETS = 120        # top markets to track per run
NOTIONAL = 1.0           # notional PnL reported as price delta (not dollars)

DATA_DIR = Path(__file__).parent / "data"
POSITIONS_PATH = DATA_DIR / "paper_positions.json"
LOG_PATH = DATA_DIR / "monitor_log.jsonl"


def load_positions() -> list[dict]:
    if POSITIONS_PATH.exists():
        return json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
    return []


def save_positions(positions: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    POSITIONS_PATH.write_text(
        json.dumps(positions, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def append_log(entry: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def pick_active_markets(client: PolymarketClient, limit: int) -> list:
    raw = []
    for offset in (0, 100, 200, 300):
        raw.extend(
            client.list_markets(limit=100, offset=offset, active=True, closed=False)
        )
    picked = []
    seen = set()
    for m in raw:
        if m.id in seen:
            continue
        seen.add(m.id)
        if not m.clob_token_ids:
            continue
        if not m.outcome_prices or len(m.outcome_prices) < 2:
            continue
        yes = m.outcome_prices[0]
        if not (PRICE_MIN < yes < PRICE_MAX):
            continue
        picked.append(m)
    picked.sort(key=lambda x: x.volume_24hr, reverse=True)
    return picked[:limit]


def find_price_at_target_ts(history: list[dict], target_ts: int, tolerance_s: int = 3600) -> dict | None:
    """Find the history point closest to target_ts, within tolerance."""
    best = None
    best_dt = tolerance_s + 1
    for p in history:
        dt = abs(p["t"] - target_ts)
        if dt < best_dt:
            best_dt = dt
            best = p
    if best_dt > tolerance_s:
        return None
    return best


def close_due_positions(
    positions: list[dict], now_ts: int, latest_by_token: dict[str, dict]
) -> int:
    closed = 0
    for pos in positions:
        if pos.get("status") != "open":
            continue
        if now_ts < pos["target_close_ts"]:
            continue
        token = pos["token_id"]
        if token not in latest_by_token:
            # can't get latest price; defer to next run
            continue
        latest = latest_by_token[token]
        close_price = latest["p"]
        close_ts = latest["t"]
        direction_mult = -1 if pos["shock_dir"] == "up" else +1
        gross_pnl = direction_mult * (close_price - pos["open_price"]) * NOTIONAL

        pos["close_ts"] = close_ts
        pos["close_price"] = close_price
        pos["gross_pnl"] = gross_pnl
        pos["status"] = "closed"
        closed += 1
    return closed


def detect_shocks_and_open(
    positions: list[dict],
    markets: list,
    price_by_token: dict[str, dict],
    now_ts: int,
) -> int:
    opened = 0
    already_open_tokens = {
        p["token_id"] for p in positions if p.get("status") == "open"
    }
    recent_closed_tokens: set[str] = set()
    cooldown_s = 6 * 3600
    for p in positions:
        if p.get("status") == "closed" and p.get("close_ts", 0) > now_ts - cooldown_s:
            recent_closed_tokens.add(p["token_id"])

    for m in markets:
        if not m.clob_token_ids:
            continue
        token = m.clob_token_ids[0]
        if token in already_open_tokens or token in recent_closed_tokens:
            continue
        data = price_by_token.get(token)
        if not data:
            continue
        history = data["history"]
        if len(history) < 7:
            continue
        history_sorted = sorted(history, key=lambda x: x["t"])
        latest = history_sorted[-1]
        target_ts = latest["t"] - 6 * 3600
        six_h = find_price_at_target_ts(history_sorted[:-1], target_ts, tolerance_s=3600)
        if six_h is None:
            continue
        dp = latest["p"] - six_h["p"]
        if abs(dp) < THRESHOLD:
            continue
        if not (PRICE_MIN < latest["p"] < PRICE_MAX):
            continue
        pos = {
            "id": f"{token[:12]}_{latest['t']}",
            "token_id": token,
            "market_id": m.id,
            "question": m.question,
            "slug": m.slug,
            "open_ts": latest["t"],
            "open_price": latest["p"],
            "six_h_ago_ts": six_h["t"],
            "six_h_ago_price": six_h["p"],
            "dp_6h": dp,
            "shock_dir": "up" if dp > 0 else "down",
            "fade_side": "NO" if dp > 0 else "YES",
            "target_close_ts": latest["t"] + HORIZON_HOURS * 3600,
            "status": "open",
            "opened_at_run_ts": now_ts,
        }
        positions.append(pos)
        opened += 1
    return opened


def main() -> None:
    now_ts = int(time.time())
    run_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
    print(f"[{run_iso}] monitor starting; threshold={THRESHOLD}, horizon={HORIZON_HOURS}h")

    client = PolymarketClient()
    markets = pick_active_markets(client, limit=MAX_MARKETS)
    print(f"  eligible markets: {len(markets)}")

    price_by_token: dict[str, dict[str, Any]] = {}
    fetch_errors = 0
    for m in markets:
        token = m.clob_token_ids[0]
        try:
            history = client.get_prices_history(token, interval="1w", fidelity=60)
        except Exception as e:
            fetch_errors += 1
            print(f"  ! fetch error {token[:12]}...: {e}", file=sys.stderr)
            continue
        if not history:
            continue
        price_by_token[token] = {
            "question": m.question,
            "history": history,
        }
        time.sleep(0.1)
    print(f"  history fetched for {len(price_by_token)} tokens (errors: {fetch_errors})")

    latest_by_token = {
        t: sorted(d["history"], key=lambda x: x["t"])[-1]
        for t, d in price_by_token.items()
        if d["history"]
    }

    positions = load_positions()
    closed_this_run = close_due_positions(positions, now_ts, latest_by_token)
    opened_this_run = detect_shocks_and_open(positions, markets, price_by_token, now_ts)
    save_positions(positions)

    closed_all = [p for p in positions if p.get("status") == "closed"]
    open_count = sum(1 for p in positions if p.get("status") == "open")
    cum_pnl = sum(p.get("gross_pnl", 0) for p in closed_all)
    hit = (
        sum(1 for p in closed_all if p.get("gross_pnl", 0) > 0) / len(closed_all)
        if closed_all
        else 0.0
    )
    avg_pnl = cum_pnl / len(closed_all) if closed_all else 0.0

    log_entry = {
        "run_ts": now_ts,
        "run_iso": run_iso,
        "markets_tracked": len(markets),
        "tokens_with_history": len(price_by_token),
        "fetch_errors": fetch_errors,
        "opened_this_run": opened_this_run,
        "closed_this_run": closed_this_run,
        "total_open": open_count,
        "total_closed": len(closed_all),
        "cumulative_pnl": round(cum_pnl, 5),
        "avg_pnl_per_trade": round(avg_pnl, 5),
        "hit_rate": round(hit, 4),
        "threshold": THRESHOLD,
        "horizon_hours": HORIZON_HOURS,
    }
    append_log(log_entry)
    print(json.dumps(log_entry, indent=2))


if __name__ == "__main__":
    main()
