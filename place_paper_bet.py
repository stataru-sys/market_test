"""Place a single paper bet on Manifold and log it for tracking.

Usage:
    python place_paper_bet.py --market-id <id> --outcome YES|NO --amount <mana>

Safety:
    - Prints market state before betting.
    - Writes the bet to data/paper_bets.jsonl for later PnL tracking.
    - Manifold is play-money only (mana, M$). Not real funds.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from manifold_client import ManifoldClient

DATA_DIR = Path(__file__).parent / "data"
BETS_PATH = DATA_DIR / "paper_bets.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--outcome", choices=["YES", "NO"], required=True)
    parser.add_argument("--amount", type=float, required=True, help="mana to bet")
    parser.add_argument("--note", default="", help="reasoning note")
    args = parser.parse_args()

    console = Console()
    client = ManifoldClient()

    me = client.me()
    console.print(f"[dim]account: @{me.username}  balance: M${me.balance:,.0f}[/dim]")
    if args.amount > me.balance:
        console.print(f"[red]Insufficient balance: need M${args.amount}, have M${me.balance}[/red]")
        return

    market = client.get_market(args.market_id)
    console.print(f"\n[bold]Market:[/bold] {market.question}")
    console.print(f"  URL: {market.url}")
    console.print(f"  Current probability: [magenta]{market.probability:.1%}[/magenta]")
    console.print(f"  Volume: M${market.volume:,.0f}, 24h M${market.volume_24h:,.0f}")
    console.print(
        f"\n[bold yellow]About to place:[/bold yellow] "
        f"M${args.amount} on [cyan]{args.outcome}[/cyan]"
    )

    console.print("\n[bold]Placing bet...[/bold]")
    result = client.place_bet(
        contract_id=args.market_id,
        amount=args.amount,
        outcome=args.outcome,
    )
    console.print(f"  [green]OK[/green]")

    bet_id = result.get("betId") or result.get("id")
    shares = result.get("shares")
    prob_before = result.get("probBefore")
    prob_after = result.get("probAfter")
    limit_prob = result.get("limitProb")

    console.print(f"\n[bold]Bet details:[/bold]")
    console.print(f"  bet_id: {bet_id}")
    if prob_before is not None and prob_after is not None:
        console.print(
            f"  prob moved: {prob_before:.1%} -> {prob_after:.1%}"
        )
    if shares:
        console.print(f"  shares acquired: {shares:.2f}")
    console.print(f"  amount staked: M${args.amount}")

    me_after = client.me()
    console.print(f"  balance after: M${me_after.balance:,.0f}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_row = {
        "placed_at": int(time.time()),
        "placed_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "market_id": args.market_id,
        "question": market.question,
        "url": market.url,
        "outcome_chosen": args.outcome,
        "amount": args.amount,
        "note": args.note,
        "market_prob_before": prob_before if prob_before is not None else market.probability,
        "market_prob_after": prob_after,
        "shares": shares,
        "bet_id": bet_id,
        "balance_after": me_after.balance,
        "raw_response": result,
    }
    with BETS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_row, ensure_ascii=False) + "\n")
    console.print(f"\n[green]Logged to {BETS_PATH}[/green]")


if __name__ == "__main__":
    main()
