"""Download full price history for top crypto markets into SQLite.

Picks N markets by 24h volume, filtered to crypto-related questions with
non-trivial uncertainty (YES price not stuck at 0 or 1), downloads the "max"
history for both YES and NO tokens, and stores them in data/polymarket.db.
"""
from __future__ import annotations

import argparse
import time

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

import db
from fetch_crypto_markets import is_crypto
from polymarket_client import PolymarketClient


def pick_markets(
    client: PolymarketClient,
    n: int,
    only_crypto: bool,
    extreme_bound: float = 0.02,
    max_offset: int = 400,
    include_closed: bool = False,
) -> list:
    raw = []
    console = Console()
    offsets = range(0, max_offset + 1, 100)
    for offset in offsets:
        batch_active = client.list_markets(
            limit=100, offset=offset, active=True, closed=False
        )
        raw.extend(batch_active)
        if include_closed:
            batch_closed = client.list_markets(
                limit=100, offset=offset, active=True, closed=True
            )
            raw.extend(batch_closed)
    console.print(f"  fetched {len(raw)} markets from Gamma")

    filtered = []
    for m in raw:
        if only_crypto and not (is_crypto(m.question) or is_crypto(m.slug)):
            continue
        if not m.clob_token_ids:
            continue
        if not m.outcome_prices or len(m.outcome_prices) < 2:
            continue
        yes = m.outcome_prices[0]
        if yes < extreme_bound or yes > (1 - extreme_bound):
            continue
        filtered.append(m)

    filtered.sort(key=lambda x: x.volume_24hr, reverse=True)
    return filtered[:n]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--limit", type=int, default=15, help="number of markets")
    parser.add_argument("--no-crypto-filter", action="store_true")
    parser.add_argument(
        "--extreme-bound",
        type=float,
        default=0.02,
        help="reject markets where YES price is within this of 0 or 1",
    )
    parser.add_argument(
        "--max-offset",
        type=int,
        default=400,
        help="Gamma pagination depth (400 => 500 markets per snapshot)",
    )
    parser.add_argument("--include-closed", action="store_true")
    parser.add_argument("--fidelity", type=int, default=60, help="minutes per point")
    parser.add_argument("--interval", default="max")
    parser.add_argument("--sleep", type=float, default=0.3, help="delay between requests")
    args = parser.parse_args()

    console = Console()
    client = PolymarketClient()

    console.print("[bold]Selecting markets...[/bold]")
    markets = pick_markets(
        client,
        args.limit,
        only_crypto=not args.no_crypto_filter,
        extreme_bound=args.extreme_bound,
        max_offset=args.max_offset,
        include_closed=args.include_closed,
    )
    if not markets:
        console.print("[red]No markets matched filters[/red]")
        return

    console.print(f"  selected: {len(markets)}\n")
    for m in markets:
        yes = m.outcome_prices[0]
        console.print(
            f"  [cyan]{m.question[:70]:70}[/cyan] "
            f"vol24h=${m.volume_24hr:>10,.0f}  yes={yes:.3f}"
        )

    console.print("\n[bold]Downloading history...[/bold]")
    total_points = 0
    with db.connect() as conn:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("markets", total=len(markets))
            for m in markets:
                db.upsert_market(conn, m)

                for token_id in m.clob_token_ids[:2]:
                    if not token_id:
                        continue
                    try:
                        history = client.get_prices_history(
                            token_id,
                            interval=args.interval,
                            fidelity=args.fidelity,
                        )
                    except Exception as e:
                        console.print(f"  [red]error for {token_id[:12]}...: {e}[/red]")
                        continue
                    added = db.upsert_prices(conn, token_id, history)
                    total_points += added
                    time.sleep(args.sleep)

                progress.update(task, advance=1)
                conn.commit()

        m_count = db.market_count(conn)
        p_count = db.price_count(conn)

    console.print(
        f"\n[bold green]Done.[/bold green] "
        f"markets in db: {m_count}, price points in db: {p_count} "
        f"(+{total_points} this run)"
    )
    console.print(f"  db file: {db.DB_PATH}")


if __name__ == "__main__":
    main()
