"""Find Manifold markets that mirror Polymarket events and show probabilities.

Manifold users create copies of popular Polymarket questions (often tagged
"[Polymarket]" in the title). Comparing the Manifold play-money probability
to the Polymarket real-money probability shows where informed capital
disagrees with the crowd-of-amateurs — or vice versa.

This script:
  1. Searches Manifold for markets with "Polymarket" in the title
  2. Prints Manifold prob, volume, close date, URL
  3. For markets where we can find a likely Polymarket match by slug keyword,
     tries to fetch the Polymarket counterpart and show both probs side-by-side
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from rich.console import Console
from rich.table import Table

from manifold_client import ManifoldClient
from polymarket_client import PolymarketClient


def strip_polymarket_tag(question: str) -> str:
    return re.sub(r"\s*\[Polymarket\]\s*", " ", question, flags=re.IGNORECASE).strip()


def key_terms(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9$]+", text.lower())
    stop = {
        "will", "the", "a", "an", "is", "are", "be", "in", "on", "by", "to",
        "of", "for", "and", "or", "at", "as", "with", "this", "that", "from",
    }
    return {w for w in words if len(w) >= 3 and w not in stop}


def similarity(a: str, b: str) -> float:
    a_t = key_terms(a)
    b_t = key_terms(b)
    if not a_t or not b_t:
        return 0.0
    jaccard = len(a_t & b_t) / len(a_t | b_t)
    seq = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return 0.6 * jaccard + 0.4 * seq


def find_polymarket_match(pm_markets: list, question: str, min_sim: float = 0.25):
    cleaned = strip_polymarket_tag(question)
    best = None
    best_score = 0.0
    for m in pm_markets:
        score = similarity(cleaned, m.question)
        if score > best_score:
            best_score = score
            best = m
    return (best, best_score) if best_score >= min_sim else (None, best_score)


def main() -> None:
    console = Console()
    manifold = ManifoldClient()
    poly = PolymarketClient()

    console.print("[bold]Searching Manifold for Polymarket mirrors...[/bold]")
    mirrors = manifold.search_markets(term="Polymarket", limit=50, filter="open")
    mirrors = [m for m in mirrors if "polymarket" in m.question.lower()]
    console.print(f"  found: {len(mirrors)} open Manifold markets mentioning Polymarket\n")

    console.print("[bold]Pulling top 500 active Polymarket markets for matching...[/bold]")
    pm_pool = []
    for offset in (0, 100, 200, 300, 400):
        pm_pool.extend(
            poly.list_markets(limit=100, offset=offset, active=True, closed=False)
        )
    console.print(f"  pool: {len(pm_pool)} markets\n")

    table = Table(
        title="Manifold mirrors <-> Polymarket (sorted by absolute prob divergence)",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("Question (cleaned)", style="cyan", max_width=52)
    table.add_column("MF%", justify="right", style="magenta")
    table.add_column("PM%", justify="right", style="green")
    table.add_column("Diff", justify="right", style="yellow")
    table.add_column("Sim", justify="right", style="dim")
    table.add_column("MF vol", justify="right")

    rows = []
    for m in mirrors:
        if m.probability is None:
            continue
        pm, score = find_polymarket_match(pm_pool, m.question)
        if not pm or not pm.outcome_prices or len(pm.outcome_prices) < 2:
            continue
        mf_prob = m.probability
        pm_prob = pm.outcome_prices[0]
        diff = mf_prob - pm_prob
        rows.append((abs(diff), m, pm, mf_prob, pm_prob, diff, score))

    rows.sort(key=lambda r: r[0], reverse=True)

    for i, (_, m, pm, mf_prob, pm_prob, diff, score) in enumerate(rows[:25], 1):
        cleaned = strip_polymarket_tag(m.question)
        sign = "+" if diff >= 0 else ""
        table.add_row(
            str(i),
            cleaned,
            f"{mf_prob:.1%}",
            f"{pm_prob:.1%}",
            f"{sign}{diff:+.1%}".replace("++", "+"),
            f"{score:.2f}",
            f"{m.volume_24h:,.0f}",
        )

    console.print(table)
    console.print(
        f"\n[dim]Matched {len(rows)} / {len(mirrors)} mirrors with sim>=0.25[/dim]"
    )


if __name__ == "__main__":
    main()
