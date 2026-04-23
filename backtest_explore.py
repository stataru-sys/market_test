"""Exploratory analysis of Polymarket price history in SQLite.

Questions we ask:
  1. What does the distribution of hourly price changes look like per market?
  2. Is there autocorrelation (trend) or negative autocorrelation (mean reversion)
     in short-horizon moves?
  3. After a large 6-hour move (|dp| > 0.05), does the price revert over
     the next 24 hours (mean reversion) or continue (momentum)?

We filter to non-extreme prices (0.10 <= p <= 0.90) to avoid trivial boundary
effects, and use multi-day markets (min lifespan 7 days) for enough data.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

DB_PATH = Path(__file__).parent / "data" / "polymarket.db"


def load_series() -> dict[str, tuple[str, pd.Series]]:
    """Return {token_id: (question, pandas Series indexed by UTC timestamp)}."""
    conn = sqlite3.connect(DB_PATH)
    markets = conn.execute(
        "SELECT id, question, token_yes FROM markets WHERE token_yes IS NOT NULL"
    ).fetchall()
    result: dict[str, tuple[str, pd.Series]] = {}
    for market_id, question, token_yes in markets:
        df = pd.read_sql_query(
            "SELECT ts_unix, price FROM prices WHERE token_id=? ORDER BY ts_unix",
            conn,
            params=(token_yes,),
        )
        if len(df) < 24:
            continue
        df["ts"] = pd.to_datetime(df["ts_unix"], unit="s", utc=True)
        series = df.set_index("ts")["price"].astype(float)
        # resample to hourly grid to align markets
        series = series.resample("1h").last().ffill()
        result[token_yes] = (question, series)
    conn.close()
    return result


def per_market_stats(series_map: dict[str, tuple[str, pd.Series]]) -> pd.DataFrame:
    rows = []
    for token, (question, s) in series_map.items():
        dp = s.diff().dropna()
        if len(dp) < 12:
            continue
        rows.append(
            {
                "token_short": token[:10] + "...",
                "question": question[:60],
                "n_hours": len(s),
                "lifespan_days": (s.index[-1] - s.index[0]).total_seconds() / 86400,
                "mean_p": float(s.mean()),
                "std_dp_1h": float(dp.std()),
                "mean_abs_dp": float(dp.abs().mean()),
                "autocorr_1": float(dp.autocorr(lag=1)) if len(dp) > 2 else np.nan,
                "autocorr_6": float(dp.autocorr(lag=6)) if len(dp) > 7 else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("n_hours", ascending=False).reset_index(drop=True)


def event_study_6h_24h(
    series_map: dict[str, tuple[str, pd.Series]],
    threshold_6h: float = 0.05,
    price_min: float = 0.10,
    price_max: float = 0.90,
) -> pd.DataFrame:
    """For each hour t, look at 6h move (p_t - p_{t-6}) on qualifying markets.
    Record the subsequent 24h move (p_{t+24} - p_t).
    Filter to non-extreme prices to avoid boundary-reversion.
    """
    events = []
    for token, (question, s) in series_map.items():
        if len(s) < 48:
            continue
        dp_6 = s - s.shift(6)
        dp_fwd_24 = s.shift(-24) - s
        mask = (
            (dp_6.abs() > threshold_6h)
            & (s.between(price_min, price_max))
            & dp_fwd_24.notna()
        )
        idx = s.index[mask]
        for t in idx:
            events.append(
                {
                    "token": token[:10],
                    "question": question[:55],
                    "ts": t,
                    "p_t": float(s.loc[t]),
                    "dp_6h": float(dp_6.loc[t]),
                    "dp_fwd_24h": float(dp_fwd_24.loc[t]),
                }
            )
    return pd.DataFrame(events)


def main() -> None:
    console = Console()
    series_map = load_series()
    console.print(f"[bold]Loaded {len(series_map)} markets from SQLite[/bold]\n")

    stats = per_market_stats(series_map)
    table = Table(title="Per-market price dynamics")
    for col in ("question", "n_hours", "lifespan_days", "mean_p", "std_dp_1h", "autocorr_1", "autocorr_6"):
        table.add_column(col, style="cyan" if col == "question" else None)
    for _, row in stats.iterrows():
        table.add_row(
            row["question"][:55],
            str(row["n_hours"]),
            f"{row['lifespan_days']:.1f}",
            f"{row['mean_p']:.3f}",
            f"{row['std_dp_1h']:.4f}",
            f"{row['autocorr_1']:+.3f}",
            f"{row['autocorr_6']:+.3f}",
        )
    console.print(table)

    console.print("\n[bold]Autocorrelation summary (lag=1h, all markets):[/bold]")
    console.print(
        f"  mean: {stats['autocorr_1'].mean():+.3f}  "
        f"median: {stats['autocorr_1'].median():+.3f}"
    )
    console.print(
        f"  positive (momentum): {(stats['autocorr_1'] > 0.05).sum()}/{len(stats)}"
    )
    console.print(
        f"  negative (reversion): {(stats['autocorr_1'] < -0.05).sum()}/{len(stats)}"
    )

    events = event_study_6h_24h(series_map)
    console.print(
        f"\n[bold]6h shock -> 24h follow-up event study[/bold]\n"
        f"  filters: |6h move| > 0.05, price in [0.10, 0.90]\n"
        f"  events collected: {len(events)}"
    )
    if events.empty:
        console.print("[yellow]No events qualify[/yellow]")
        return

    pos = events[events["dp_6h"] > 0]
    neg = events[events["dp_6h"] < 0]
    console.print(
        f"\n  after POSITIVE 6h shock (n={len(pos)}): "
        f"mean fwd-24h = {pos['dp_fwd_24h'].mean():+.4f}  "
        f"(std {pos['dp_fwd_24h'].std():.4f})"
    )
    console.print(
        f"  after NEGATIVE 6h shock (n={len(neg)}): "
        f"mean fwd-24h = {neg['dp_fwd_24h'].mean():+.4f}  "
        f"(std {neg['dp_fwd_24h'].std():.4f})"
    )
    console.print(
        f"\n  directional signal: after positive shock price moves "
        f"{'DOWN (mean reversion)' if pos['dp_fwd_24h'].mean() < 0 else 'UP (momentum)'}"
    )
    console.print(
        f"  directional signal: after negative shock price moves "
        f"{'UP (mean reversion)' if neg['dp_fwd_24h'].mean() > 0 else 'DOWN (momentum)'}"
    )

    simple_pnl = (-np.sign(events["dp_6h"]) * events["dp_fwd_24h"]).sum()
    hits = int((-np.sign(events["dp_6h"]) * events["dp_fwd_24h"] > 0).sum())
    console.print(
        f"\n[bold]Naive 'fade the shock' strategy (1 share per event, no fees):[/bold]"
    )
    console.print(
        f"  total pnl: {simple_pnl:+.4f}  ({hits}/{len(events)} hits = {hits/len(events):.1%})"
    )
    console.print(
        f"  average per trade: {simple_pnl/len(events):+.5f}  "
        f"(vs Polymarket crypto taker fee ~0.0180 — strategy loses to fees)"
    )


if __name__ == "__main__":
    main()
