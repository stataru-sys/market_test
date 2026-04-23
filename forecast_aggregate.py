"""Aggregate all rounds of Claude's forecasting self-test.

Reads forecast_history.jsonl and shows:
  - per-round mean |diff|, max |diff|, agreement rate
  - divergence distribution by stated confidence level
  - candidates for paper betting (largest |diff| with medium/high confidence)
  - Brier score (only computed for markets that have resolved)

Resolution check is optional — we re-query Manifold for each market id and
compute Brier when resolution is known.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table

from manifold_client import ManifoldClient

DATA_DIR = Path(__file__).parent / "data"
HISTORY_PATH = DATA_DIR / "forecast_history.jsonl"


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def per_round_stats(rows: list[dict]) -> None:
    console = Console()
    table = Table(title="Per-round statistics")
    table.add_column("Round", justify="right")
    table.add_column("N", justify="right")
    table.add_column("Mean |diff|", justify="right")
    table.add_column("Max |diff|", justify="right")
    table.add_column("Agree (<=5%)", justify="right")
    table.add_column("High-conf misses (>=10%, high)", justify="right")
    for r in rows:
        preds = r["predictions"]
        diffs = [abs(p["claude_prob"] - p["market_prob_at_predict"]) for p in preds]
        # confidence not captured in history file — skip that column for now
        table.add_row(
            str(r["round"]),
            str(len(preds)),
            f"{sum(diffs)/len(diffs):.1%}",
            f"{max(diffs):.1%}",
            f"{sum(1 for d in diffs if d <= 0.05)}/{len(diffs)}",
            "-",
        )
    console.print(table)


def aggregate_stats(rows: list[dict]) -> None:
    all_preds = [p for r in rows for p in r["predictions"]]
    diffs = [abs(p["claude_prob"] - p["market_prob_at_predict"]) for p in all_preds]
    console = Console()
    console.print(f"\n[bold]Across all rounds:[/bold] N={len(all_preds)}")
    console.print(f"  mean |diff|: {sum(diffs)/len(diffs):.1%}")
    console.print(f"  median |diff|: {sorted(diffs)[len(diffs)//2]:.1%}")
    console.print(f"  max |diff|: {max(diffs):.1%}")
    console.print(f"  agreement (<=5%): {sum(1 for d in diffs if d <= 0.05)}/{len(all_preds)}")
    console.print(f"  moderate (5-15%): {sum(1 for d in diffs if 0.05 < d <= 0.15)}/{len(all_preds)}")
    console.print(f"  big (>15%): {sum(1 for d in diffs if d > 0.15)}/{len(all_preds)}")


def show_biggest_divergences(rows: list[dict], n: int = 10) -> None:
    console = Console()
    all_preds = [p for r in rows for p in r["predictions"]]
    all_preds.sort(
        key=lambda p: abs(p["claude_prob"] - p["market_prob_at_predict"]),
        reverse=True,
    )
    table = Table(title=f"Top {n} largest divergences (potential edge or blind spot)")
    table.add_column("Q", style="cyan", max_width=50)
    table.add_column("Claude", justify="right", style="magenta")
    table.add_column("Market", justify="right", style="green")
    table.add_column("Diff", justify="right", style="yellow")
    table.add_column("Conf", style="dim")
    for p in all_preds[:n]:
        diff = p["claude_prob"] - p["market_prob_at_predict"]
        table.add_row(
            p["question"],
            f"{p['claude_prob']:.1%}",
            f"{p['market_prob_at_predict']:.1%}",
            f"{diff:+.1%}",
            p.get("confidence", ""),
        )
    console.print(table)


def brier_check(rows: list[dict]) -> None:
    """For each prediction, re-query Manifold to see if resolved, compute Brier."""
    console = Console()
    console.print("\n[bold]Checking resolutions on Manifold...[/bold]")
    client = ManifoldClient()
    resolved = []
    pending = 0
    for r in rows:
        for p in r["predictions"]:
            try:
                market = client.get_market(p["market_id"])
            except Exception:
                continue
            if not market.is_resolved:
                pending += 1
                continue
            if market.resolution == "YES":
                y = 1.0
            elif market.resolution == "NO":
                y = 0.0
            else:
                continue
            claude_brier = (p["claude_prob"] - y) ** 2
            market_brier = (p["market_prob_at_predict"] - y) ** 2
            resolved.append(
                {
                    "question": p["question"],
                    "y": y,
                    "claude": p["claude_prob"],
                    "market_at_predict": p["market_prob_at_predict"],
                    "claude_brier": claude_brier,
                    "market_brier": market_brier,
                }
            )

    console.print(f"  resolved: {len(resolved)}, pending: {pending}")
    if not resolved:
        return

    c_brier = sum(r["claude_brier"] for r in resolved) / len(resolved)
    m_brier = sum(r["market_brier"] for r in resolved) / len(resolved)
    console.print(f"\n[bold]Mean Brier score (lower is better):[/bold]")
    console.print(f"  Claude: {c_brier:.4f}")
    console.print(f"  Market (at prediction time): {m_brier:.4f}")
    delta = c_brier - m_brier
    verdict = "worse than market" if delta > 0 else "better than market"
    console.print(f"  Delta: {delta:+.4f}  (Claude is {verdict})")

    table = Table(title="Per-market outcomes")
    table.add_column("Q", style="cyan", max_width=48)
    table.add_column("Y", justify="center")
    table.add_column("Claude", justify="right")
    table.add_column("Mkt", justify="right")
    table.add_column("C Brier", justify="right", style="magenta")
    table.add_column("M Brier", justify="right", style="green")
    for r in resolved:
        table.add_row(
            r["question"],
            "Y" if r["y"] == 1 else "N",
            f"{r['claude']:.2f}",
            f"{r['market_at_predict']:.2f}",
            f"{r['claude_brier']:.3f}",
            f"{r['market_brier']:.3f}",
        )
    console.print(table)


def main() -> None:
    console = Console()
    rows = load_history()
    if not rows:
        console.print("[red]No history found[/red]")
        return
    per_round_stats(rows)
    aggregate_stats(rows)
    show_biggest_divergences(rows, n=10)
    brier_check(rows)


if __name__ == "__main__":
    main()
