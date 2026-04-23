"""Show what's currently stored in data/polymarket.db.

Lists each market with its price trajectory summary: first/last price,
change, min/max, number of hourly points, coverage window.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

import db


def fmt_ts(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    console = Console()
    with db.connect() as conn:
        m_count = db.market_count(conn)
        p_count = db.price_count(conn)
        console.print(f"[bold]DB summary[/bold]: {m_count} markets, {p_count} price points\n")

        rows = conn.execute(
            """
            SELECT m.id, m.question, m.volume_24hr, m.token_yes, m.end_date, m.closed
            FROM markets m
            ORDER BY m.volume_24hr DESC
            """
        ).fetchall()

        table = Table(title="Markets and YES-token price trajectories")
        table.add_column("Question", style="cyan", max_width=52)
        table.add_column("Ends", style="dim")
        table.add_column("Points", justify="right")
        table.add_column("First", justify="right")
        table.add_column("Last", justify="right")
        table.add_column("Chg", justify="right", style="magenta")
        table.add_column("Min..Max", justify="right")
        table.add_column("Range", style="dim")

        for mid, question, vol, token_yes, end_date, closed in rows:
            if not token_yes:
                continue
            stats = conn.execute(
                """
                SELECT MIN(ts_unix), MAX(ts_unix), MIN(price), MAX(price), COUNT(*)
                FROM prices WHERE token_id = ?
                """,
                (token_yes,),
            ).fetchone()
            if not stats or stats[4] == 0:
                continue
            ts_min, ts_max, p_min, p_max, n = stats
            first_p = conn.execute(
                "SELECT price FROM prices WHERE token_id=? AND ts_unix=?",
                (token_yes, ts_min),
            ).fetchone()[0]
            last_p = conn.execute(
                "SELECT price FROM prices WHERE token_id=? AND ts_unix=?",
                (token_yes, ts_max),
            ).fetchone()[0]
            delta = last_p - first_p
            delta_str = f"{delta:+.3f}"
            table.add_row(
                question,
                (end_date or "-")[:10],
                str(n),
                f"{first_p:.3f}",
                f"{last_p:.3f}",
                delta_str,
                f"{p_min:.3f}..{p_max:.3f}",
                f"{fmt_ts(ts_min)} .. {fmt_ts(ts_max)}",
            )

        console.print(table)


if __name__ == "__main__":
    main()
