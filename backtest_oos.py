"""Out-of-sample validation of the fade-the-shock signal.

Procedure:
  1. Collect all (market, timestamp) events where |6h move| >= 0.02 with
     forward returns at 12h, 24h, 48h.
  2. Split globally by event timestamp — first half is TRAIN, second half is TEST.
  3. Grid-search (threshold, horizon) on TRAIN by net PnL at a chosen fee tier.
  4. Take the best (threshold, horizon) from TRAIN and apply to TEST without
     any further optimization. Report both sides.
  5. Also report: TRAIN-best applied to TEST when filtering on different fee
     tiers, so we can see which fee tier it survives on OOS.

This is the discipline that separates 'we found a pattern' from 'we have a
strategy'. If TEST performance is close to TRAIN, signal is real. If TEST
degrades sharply, we curve-fit noise.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

DB_PATH = Path(__file__).parent / "data" / "polymarket.db"


def load_series() -> dict[str, pd.Series]:
    conn = sqlite3.connect(DB_PATH)
    markets = conn.execute(
        "SELECT token_yes FROM markets WHERE token_yes IS NOT NULL"
    ).fetchall()
    out: dict[str, pd.Series] = {}
    for (token_yes,) in markets:
        df = pd.read_sql_query(
            "SELECT ts_unix, price FROM prices WHERE token_id=? ORDER BY ts_unix",
            conn,
            params=(token_yes,),
        )
        if len(df) < 48:
            continue
        df["ts"] = pd.to_datetime(df["ts_unix"], unit="s", utc=True)
        s = df.set_index("ts")["price"].astype(float)
        s = s.resample("1h").last().ffill()
        out[token_yes] = s
    conn.close()
    return out


def collect_events(
    series_map: dict[str, pd.Series],
    min_threshold: float = 0.02,
    price_min: float = 0.10,
    price_max: float = 0.90,
) -> pd.DataFrame:
    """One row per (market, timestamp) event with |6h move| > min_threshold.
    Forward returns computed at 12h, 24h, 48h.
    """
    events = []
    horizons = (12, 24, 48)
    for token, s in series_map.items():
        if len(s) < 6 + max(horizons):
            continue
        dp_6 = s - s.shift(6)
        fwd = {h: s.shift(-h) - s for h in horizons}
        mask = (
            (dp_6.abs() > min_threshold)
            & (s.between(price_min, price_max))
        )
        for h in horizons:
            mask &= fwd[h].notna()
        idx = s.index[mask]
        for t in idx:
            events.append(
                {
                    "token": token,
                    "ts": t,
                    "p_t": float(s.loc[t]),
                    "dp_6h": float(dp_6.loc[t]),
                    "fwd_12h": float(fwd[12].loc[t]),
                    "fwd_24h": float(fwd[24].loc[t]),
                    "fwd_48h": float(fwd[48].loc[t]),
                }
            )
    df = pd.DataFrame(events)
    if not df.empty:
        df.sort_values("ts", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


def fade_pnl(events: pd.DataFrame, horizon: int) -> pd.Series:
    return -np.sign(events["dp_6h"]) * events[f"fwd_{horizon}h"]


def grid_stats(
    events: pd.DataFrame,
    thresholds: list[float],
    horizons: list[int],
    fee: float = 0.0,
) -> pd.DataFrame:
    rows = []
    for t in thresholds:
        sub_by_t = events[events["dp_6h"].abs() > t]
        for h in horizons:
            if sub_by_t.empty:
                continue
            pnl = fade_pnl(sub_by_t, h)
            if len(pnl) < 10:
                continue
            net = pnl - fee
            rows.append(
                {
                    "threshold": t,
                    "horizon": h,
                    "n": len(pnl),
                    "gross": float(pnl.mean()),
                    "net": float(net.mean()),
                    "hit": float((net > 0).mean()),
                    "std": float(net.std()),
                    "t_stat": float(net.mean() / (net.std() / np.sqrt(len(net))))
                    if net.std() > 0
                    else np.nan,
                }
            )
    if not rows:
        return pd.DataFrame(columns=["threshold", "horizon", "n", "gross", "net", "hit", "std", "t_stat"])
    return pd.DataFrame(rows).sort_values("net", ascending=False).reset_index(drop=True)


def main() -> None:
    console = Console(width=200)
    series_map = load_series()
    console.print(f"[bold]Loaded {len(series_map)} markets[/bold]")

    all_events = collect_events(series_map, min_threshold=0.02)
    console.print(f"[bold]Total events (|6h|>0.02, price in [0.10, 0.90]): {len(all_events)}[/bold]\n")
    if all_events.empty:
        return

    all_events["ts_unix"] = all_events["ts"].apply(lambda x: int(x.timestamp()))
    cutoff = int(all_events["ts_unix"].median())
    cutoff_date = pd.to_datetime(cutoff, unit="s", utc=True)
    train = all_events[all_events["ts_unix"] < cutoff].reset_index(drop=True)
    test = all_events[all_events["ts_unix"] >= cutoff].reset_index(drop=True)
    console.print(
        f"Split cutoff: [cyan]{cutoff_date.strftime('%Y-%m-%d %H:%M UTC')}[/cyan]  "
        f"train_events={len(train)}, test_events={len(test)}\n"
    )

    thresholds = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    horizons = [12, 24, 48]
    fee_tiers = {
        "maker 0%": 0.0,
        "sports 0.75%": 0.0075,
        "politics 1%": 0.010,
        "crypto 1.8%": 0.018,
    }

    for fee_name, fee in fee_tiers.items():
        console.print(f"\n[bold]Fee tier: {fee_name} ({fee:.2%})[/bold]")

        train_stats = grid_stats(train, thresholds, horizons, fee=fee)
        if train_stats.empty:
            continue
        best_train = train_stats.iloc[0]
        best_t = best_train["threshold"]
        best_h = int(best_train["horizon"])

        # Apply best train parameters to TEST without re-optimization
        test_sub = test[test["dp_6h"].abs() > best_t]
        if test_sub.empty:
            console.print(f"  no test events for threshold={best_t:.02f}")
            continue
        test_pnl = fade_pnl(test_sub, best_h) - fee
        test_n = len(test_pnl)
        test_gross = test_pnl.mean()
        test_std = test_pnl.std()
        test_hit = (test_pnl > 0).mean()
        test_t = test_gross / (test_std / np.sqrt(test_n)) if test_std > 0 else float("nan")

        table = Table(show_lines=False)
        table.add_column("", style="bold")
        table.add_column("threshold", justify="right")
        table.add_column("horizon", justify="right")
        table.add_column("N", justify="right")
        table.add_column("Net mean", justify="right")
        table.add_column("Std", justify="right", style="dim")
        table.add_column("Hit", justify="right")
        table.add_column("t-stat", justify="right", style="magenta")

        table.add_row(
            "TRAIN best",
            f"{best_t:.02f}",
            str(best_h),
            str(int(best_train["n"])),
            f"[green]{best_train['net']:+.4f}[/green]",
            f"{best_train['std']:.4f}",
            f"{best_train['hit']:.1%}",
            f"{best_train['t_stat']:.2f}",
        )
        color = "green" if test_gross > 0 else "red"
        table.add_row(
            "TEST (OOS)",
            f"{best_t:.02f}",
            str(best_h),
            str(test_n),
            f"[{color}]{test_gross:+.4f}[/{color}]",
            f"{test_std:.4f}",
            f"{test_hit:.1%}",
            f"{test_t:.2f}",
        )
        degradation = (test_gross - best_train["net"]) / abs(best_train["net"]) if best_train["net"] != 0 else 0
        verdict = "HOLDS" if test_gross > 0 and abs(test_t) > 1.5 else ("WEAK" if test_gross > 0 else "FAILS OOS")
        console.print(table)
        console.print(
            f"  relative change from train -> test: {degradation*100:+.1f}%   "
            f"verdict: [bold]{verdict}[/bold]"
        )

    console.print(
        "\n[dim]Caveats: cutoff is simple median of events — no care for regime shifts. "
        "Events across markets can be correlated (same shock triggers positions in 2-3 "
        "related markets). Effective N is lower than shown.[/dim]"
    )


if __name__ == "__main__":
    main()
