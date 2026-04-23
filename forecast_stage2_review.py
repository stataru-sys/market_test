"""Stage 2 of Claude's forecasting self-test.

Loads blind predictions + market data from stage 1 and shows the divergence
between Claude's predictions and Manifold market probabilities, sorted by
absolute disagreement. Also logs the round to data/forecast_history.jsonl for
later Brier scoring when markets resolve.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

DATA_DIR = Path(__file__).parent / "data"
HISTORY_PATH = DATA_DIR / "forecast_history.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--round", type=int, default=1)
    args = parser.parse_args()
    full_path = DATA_DIR / f"forecast_round{args.round}_full.json"
    pred_path = DATA_DIR / f"forecast_round{args.round}_predictions.json"

    console = Console()
    full = json.loads(full_path.read_text(encoding="utf-8"))
    preds = json.loads(pred_path.read_text(encoding="utf-8"))

    meta = preds.get("_meta", {})
    console.print(f"[bold]Forecaster:[/bold] {meta.get('forecaster', 'unknown')}")
    console.print(f"[bold]Predicted at:[/bold] {meta.get('predicted_at_utc')}")
    console.print(f"[bold]Method:[/bold] {meta.get('methodology', '')[:110]}...\n")

    rows = []
    for market in full:
        mid = market["id"]
        if mid not in preds:
            continue
        p_claude = preds[mid]["prob"]
        p_market = market["probability"]
        diff = p_claude - p_market
        rows.append(
            {
                "market": market,
                "claude_prob": p_claude,
                "market_prob": p_market,
                "diff": diff,
                "abs_diff": abs(diff),
                "confidence": preds[mid].get("confidence"),
                "rationale": preds[mid].get("rationale", ""),
            }
        )

    rows.sort(key=lambda r: r["abs_diff"], reverse=True)

    table = Table(
        title="Claude vs Manifold: blind predictions",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("Question", style="cyan", max_width=48)
    table.add_column("Claude", justify="right", style="magenta")
    table.add_column("Market", justify="right", style="green")
    table.add_column("Diff", justify="right", style="yellow")
    table.add_column("Conf", style="dim")
    table.add_column("Dir", justify="center")

    for i, r in enumerate(rows, 1):
        diff = r["diff"]
        sign = "+" if diff > 0 else ""
        direction = "YES edge" if diff > 0.05 else ("NO edge" if diff < -0.05 else "agree")
        table.add_row(
            str(i),
            r["market"]["question"],
            f"{r['claude_prob']:.1%}",
            f"{r['market_prob']:.1%}",
            f"{sign}{diff:+.1%}".replace("++", "+"),
            r["confidence"] or "",
            direction,
        )

    console.print(table)

    mean_abs = sum(r["abs_diff"] for r in rows) / len(rows) if rows else 0
    max_abs = max((r["abs_diff"] for r in rows), default=0)
    agree = sum(1 for r in rows if r["abs_diff"] <= 0.05)
    console.print(
        f"\n[bold]Summary:[/bold] {len(rows)} markets, "
        f"mean |diff|={mean_abs:.1%}, max |diff|={max_abs:.1%}, "
        f"agreement (<=5%): {agree}/{len(rows)}"
    )

    console.print("\n[bold]Top 3 divergences with Claude's reasoning:[/bold]")
    for r in rows[:3]:
        console.print(
            f"\n  [cyan]{r['market']['question']}[/cyan]"
            f"\n  Claude={r['claude_prob']:.1%}  Market={r['market_prob']:.1%}  "
            f"Diff={r['diff']:+.1%}  ({r['confidence']})"
        )
        console.print(f"  [dim]{r['rationale'][:250]}[/dim]")

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "round": args.round,
        "logged_at": int(time.time()),
        "logged_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "forecaster": meta.get("forecaster"),
        "predictions": [
            {
                "market_id": r["market"]["id"],
                "platform": "manifold",
                "question": r["market"]["question"],
                "url": r["market"]["url"],
                "close_time_ms": r["market"]["close_time_ms"],
                "claude_prob": r["claude_prob"],
                "market_prob_at_predict": r["market_prob"],
                "confidence": r["confidence"],
            }
            for r in rows
        ],
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    console.print(f"\n[green]Logged round to {HISTORY_PATH}[/green]")


if __name__ == "__main__":
    main()
