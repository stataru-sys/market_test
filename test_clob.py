"""Probe CLOB prices-history endpoint to verify shape before building storage."""
from __future__ import annotations

from datetime import datetime, timezone

from polymarket_client import PolymarketClient
from rich.console import Console


def main() -> None:
    console = Console()
    client = PolymarketClient()

    console.print("[bold]Picking a non-extreme multi-day crypto market...[/bold]")
    markets = client.list_markets(limit=200, active=True, closed=False, order="volume24hr")
    candidates = [
        m for m in markets
        if m.clob_token_ids
        and m.outcome_prices
        and 0.1 < m.outcome_prices[0] < 0.9
        and any(kw in m.question.lower() for kw in ("bitcoin", "ethereum", "btc", "eth"))
    ]
    if not candidates:
        console.print("[red]No suitable market found[/red]")
        return

    m = candidates[0]
    token_yes = m.clob_token_ids[0]
    console.print(f"Market: [cyan]{m.question}[/cyan]")
    console.print(f"  YES price: {m.outcome_prices[0]:.3f}")
    console.print(f"  YES token: {token_yes}")
    console.print(f"  ends: {m.end_date}")
    console.print()

    for interval in ("1d", "1w", "1m", "max"):
        history = client.get_prices_history(token_yes, interval=interval, fidelity=60)
        console.print(f"[bold]interval={interval}[/bold]: {len(history)} points")
        if history:
            first = history[0]
            last = history[-1]
            first_dt = datetime.fromtimestamp(first["t"], tz=timezone.utc).isoformat()
            last_dt = datetime.fromtimestamp(last["t"], tz=timezone.utc).isoformat()
            console.print(f"  first: {first_dt} p={first['p']:.4f}")
            console.print(f"  last:  {last_dt} p={last['p']:.4f}")
        console.print()


if __name__ == "__main__":
    main()
