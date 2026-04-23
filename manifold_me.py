"""Verify Manifold API key: fetch current user profile and show balance + top markets."""
from __future__ import annotations

from datetime import datetime, timezone

from manifold_client import ManifoldClient
from rich.console import Console
from rich.table import Table


def main() -> None:
    console = Console()
    client = ManifoldClient()

    console.print("[bold]Fetching authenticated user...[/bold]")
    try:
        me = client.me()
    except Exception as e:
        console.print(f"[red]Auth failed: {e}[/red]")
        return

    created = datetime.fromtimestamp(me.created_time / 1000, tz=timezone.utc)
    profit = f"{me.profit_cached_all_time:+,.0f}" if me.profit_cached_all_time is not None else "-"

    console.print(f"  [green]OK[/green]")
    console.print(f"  username    : [cyan]@{me.username}[/cyan]")
    console.print(f"  name        : {me.name}")
    console.print(f"  id          : {me.id}")
    console.print(f"  balance     : [green]M${me.balance:,.0f}[/green]")
    console.print(f"  deposits    : M${me.total_deposits:,.0f}")
    console.print(f"  profit(all) : {profit}")
    console.print(f"  joined      : {created.strftime('%Y-%m-%d')}")

    console.print("\n[bold]Top 10 open markets by recent activity:[/bold]")
    markets = client.search_markets(sort="score", filter="open", limit=10)
    table = Table(show_lines=False)
    table.add_column("Question", style="cyan", max_width=55)
    table.add_column("Prob", justify="right", style="magenta")
    table.add_column("Vol 24h", justify="right", style="green")
    table.add_column("Type", style="dim")
    for m in markets:
        prob = f"{m.probability:.2%}" if m.probability is not None else "-"
        table.add_row(m.question, prob, f"{m.volume_24h:,.0f}", m.outcome_type)
    console.print(table)


if __name__ == "__main__":
    main()
