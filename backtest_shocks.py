"""Non-linearity analysis: does the mean-reversion edge grow with shock size?

For a sweep of thresholds (|6h move| > X), compute:
  - number of qualifying events
  - average fade-the-shock PnL per trade
  - hit rate
  - net PnL after various fee levels (maker 0%, sports 0.75%, politics 1.00%, crypto 1.80%)

Also scans multiple forward horizons (12h, 24h, 48h) to find where reversion peaks.
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
    threshold_6h: float,
    fwd_hours: int,
    price_min: float = 0.10,
    price_max: float = 0.90,
) -> pd.DataFrame:
    events = []
    for token, s in series_map.items():
        if len(s) < 6 + fwd_hours:
            continue
        dp_6 = s - s.shift(6)
        dp_fwd = s.shift(-fwd_hours) - s
        mask = (
            (dp_6.abs() > threshold_6h)
            & (s.between(price_min, price_max))
            & dp_fwd.notna()
        )
        idx = s.index[mask]
        for t in idx:
            events.append(
                {
                    "token": token,
                    "p_t": float(s.loc[t]),
                    "dp_6h": float(dp_6.loc[t]),
                    "dp_fwd": float(dp_fwd.loc[t]),
                }
            )
    return pd.DataFrame(events)


def fade_stats(events: pd.DataFrame) -> dict:
    if events.empty:
        return {"n": 0, "avg_fade": np.nan, "hit": np.nan, "std": np.nan}
    trade_pnl = -np.sign(events["dp_6h"]) * events["dp_fwd"]
    return {
        "n": len(events),
        "avg_fade": float(trade_pnl.mean()),
        "hit": float((trade_pnl > 0).mean()),
        "std": float(trade_pnl.std()),
    }


def main() -> None:
    console = Console(width=200)
    series_map = load_series()
    console.print(f"[bold]Loaded {len(series_map)} markets with >=48 hourly points[/bold]\n")

    thresholds = [0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]
    horizons = [12, 24, 48]

    for fwd in horizons:
        console.print(f"\n[bold]Forward horizon: {fwd}h[/bold]")
        table = Table(show_lines=False)
        table.add_column("|6h move| >", justify="right")
        table.add_column("N events", justify="right")
        table.add_column("Hit %", justify="right")
        table.add_column("Avg fade PnL", justify="right", style="magenta")
        table.add_column("Std", justify="right", style="dim")
        table.add_column("Net maker 0%", justify="right", style="green")
        table.add_column("Net sports 0.75%", justify="right")
        table.add_column("Net politics 1.00%", justify="right")
        table.add_column("Net crypto 1.80%", justify="right", style="red")

        for t in thresholds:
            events = collect_events(series_map, threshold_6h=t, fwd_hours=fwd)
            stats = fade_stats(events)
            if stats["n"] == 0:
                continue
            gross = stats["avg_fade"]
            row_color = lambda net: f"[green]{net:+.4f}[/green]" if net > 0 else f"[red]{net:+.4f}[/red]"
            table.add_row(
                f"{t:.02f}",
                str(stats["n"]),
                f"{stats['hit']:.1%}",
                f"{gross:+.4f}",
                f"{stats['std']:.4f}",
                row_color(gross - 0.0),
                row_color(gross - 0.0075),
                row_color(gross - 0.010),
                row_color(gross - 0.018),
            )
        console.print(table)

    console.print(
        "\n[dim]Fee assumption: one-sided taker fee. Round-trip would be 2x "
        "unless you close as maker. Geopolitics tier = 0% (== maker).[/dim]"
    )

    console.print("\n[bold]Signal-to-noise at threshold 0.05, horizon 24h:[/bold]")
    e = collect_events(series_map, threshold_6h=0.05, fwd_hours=24)
    s = fade_stats(e)
    if s["n"] > 0:
        sharpe_like = s["avg_fade"] / s["std"] if s["std"] > 0 else float("nan")
        t_stat = s["avg_fade"] / (s["std"] / np.sqrt(s["n"])) if s["std"] > 0 else float("nan")
        console.print(
            f"  per-trade avg/std: {sharpe_like:.3f}  "
            f"(think of as 'unit-risk return')"
        )
        console.print(
            f"  t-statistic of mean: {t_stat:.2f}  "
            f"(>2.0 ~= signal is not chance, at this sample size)"
        )


if __name__ == "__main__":
    main()
