"""Fetch active crypto-related Polymarket markets and print a ranked summary.

Usage:
    python fetch_crypto_markets.py
"""
from __future__ import annotations

import re

from polymarket_client import PolymarketClient
from rich.console import Console
from rich.table import Table

CRYPTO_PATTERN = re.compile(
    r"\b(?:bitcoin|btc|ethereum|eth|megaeth|solana|sol|crypto|xrp|ripple|"
    r"dogecoin|doge|binance|bnb|cardano|ada|polkadot|dot|avalanche|avax|"
    r"chainlink|link|altcoin|memecoin|stablecoin|usdc|usdt|"
    r"coinbase|tether)\b",
    re.IGNORECASE,
)


def is_crypto(text: str) -> bool:
    return bool(CRYPTO_PATTERN.search(text or ""))


def main() -> None:
    console = Console()
    client = PolymarketClient()

    console.print("[bold]Fetching top 500 active markets by 24h volume...[/bold]")
    batches = []
    for offset in (0, 100, 200, 300, 400):
        batches.extend(
            client.list_markets(limit=100, offset=offset, active=True, closed=False)
        )
    markets = batches
    console.print(f"  fetched: {len(markets)} markets\n")

    crypto = [m for m in markets if is_crypto(m.question) or is_crypto(m.slug)]
    crypto.sort(key=lambda m: m.volume_24hr, reverse=True)
    console.print(f"[bold]Crypto-related: {len(crypto)}[/bold]\n")

    table = Table(
        title="Top Crypto Markets on Polymarket (by 24h volume)",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("Question", style="cyan", max_width=55)
    table.add_column("Vol 24h $", justify="right", style="green")
    table.add_column("Liquidity $", justify="right")
    table.add_column("Ends", style="dim")
    table.add_column("YES / NO", justify="right", style="magenta")

    for idx, m in enumerate(crypto[:25], 1):
        if len(m.outcome_prices) >= 2:
            yes_no = f"{m.outcome_prices[0]:.3f} / {m.outcome_prices[1]:.3f}"
        else:
            yes_no = "-"
        end = m.end_date[:10] if m.end_date else "-"
        table.add_row(
            str(idx),
            m.question,
            f"{m.volume_24hr:,.0f}",
            f"{m.liquidity_num:,.0f}",
            end,
            yes_no,
        )

    console.print(table)

    total_vol = sum(m.volume_24hr for m in crypto)
    console.print(
        f"\n[dim]Aggregate 24h volume across crypto markets: ${total_vol:,.0f}[/dim]"
    )


if __name__ == "__main__":
    main()
