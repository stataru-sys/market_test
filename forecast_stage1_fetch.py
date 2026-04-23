"""Stage 1 of Claude's forecasting self-test.

Pulls N binary Manifold markets that close in 2-14 days with decent volume,
saves FULL data (including current probability) to data/forecast_round1_full.json,
but prints ONLY redacted info (question, description, close date, url) to stdout
so Claude can make blind predictions before seeing market prices.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from manifold_client import ManifoldClient


DATA_DIR = Path(__file__).parent / "data"
HISTORY_PATH = DATA_DIR / "forecast_history.jsonl"


def already_predicted_ids() -> set[str]:
    if not HISTORY_PATH.exists():
        return set()
    seen: set[str] = set()
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        for p in entry.get("predictions", []):
            seen.add(p.get("market_id", ""))
    return seen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--count", type=int, default=10)
    parser.add_argument("-r", "--round", type=int, default=1)
    parser.add_argument("--min-volume", type=float, default=300)
    parser.add_argument("--min-days", type=int, default=2)
    parser.add_argument("--max-days", type=int, default=14)
    args = parser.parse_args()
    full_path = DATA_DIR / f"forecast_round{args.round}_full.json"
    seen_ids = already_predicted_ids()

    console = Console()
    client = ManifoldClient()
    now_ms = int(time.time() * 1000)
    min_close = now_ms + args.min_days * 86_400_000
    max_close = now_ms + args.max_days * 86_400_000

    console.print(f"[bold]Searching candidate markets...[/bold]")
    pool: list = []
    for sort in ("close-date", "score", "liquidity"):
        pool.extend(client.search_markets(sort=sort, filter="open", limit=100))

    seen = set()
    uniq = []
    for m in pool:
        if m.id in seen:
            continue
        seen.add(m.id)
        uniq.append(m)

    candidates = [
        m for m in uniq
        if m.outcome_type == "BINARY"
        and m.probability is not None
        and m.close_time is not None
        and min_close <= m.close_time <= max_close
        and m.volume >= args.min_volume
        and not m.is_resolved
        and m.id not in seen_ids
    ]
    candidates.sort(key=lambda m: m.volume, reverse=True)
    picked = candidates[: args.count]

    console.print(
        f"  pool={len(uniq)}  binary_eligible={len(candidates)}  "
        f"picked={len(picked)}  (excluded {len(seen_ids)} previously-seen)\n"
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    full = []
    redacted = []
    for m in picked:
        raw = m.raw
        full_row = {
            "id": m.id,
            "question": m.question,
            "slug": m.slug,
            "url": m.url,
            "probability": m.probability,
            "volume": m.volume,
            "volume_24h": m.volume_24h,
            "close_time_ms": m.close_time,
            "close_date_utc": datetime.fromtimestamp(m.close_time / 1000, tz=timezone.utc).isoformat() if m.close_time else None,
            "description_text": _extract_description(raw),
            "created_time_ms": raw.get("createdTime"),
            "last_updated_ms": raw.get("lastUpdatedTime"),
            "total_liquidity": raw.get("totalLiquidity"),
            "unique_bettor_count": raw.get("uniqueBettorCount"),
        }
        full.append(full_row)
        redacted.append({k: v for k, v in full_row.items() if k != "probability"})

    full_path.write_text(
        json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    console.print(f"[green]Saved full data (with probabilities) to {full_path}[/green]\n")

    console.print(
        Panel(
            "[bold]BLIND CANDIDATES[/bold]\nThe [red]probability is NOT shown below[/red] so Claude can predict without bias.",
            title="Forecast stage 1",
        )
    )
    for i, row in enumerate(redacted, 1):
        console.print(f"\n[bold cyan]#{i} ({row['id']})[/bold cyan]")
        console.print(f"  Q: {row['question']}")
        console.print(f"  URL: {row['url']}")
        console.print(f"  closes: {row['close_date_utc']}")
        console.print(
            f"  volume: M$ {row['volume']:,.0f}  (24h {row['volume_24h']:,.0f}, "
            f"bettors: {row['unique_bettor_count']})"
        )
        desc = (row["description_text"] or "").strip()
        if desc:
            if len(desc) > 400:
                desc = desc[:400] + " ..."
            console.print(f"  Desc: [dim]{desc}[/dim]")

    console.print(
        f"\n[bold]Next:[/bold] Claude writes predictions to "
        f"[cyan]data/forecast_round{args.round}_predictions.json[/cyan] "
        f"then runs forecast_stage2_review.py --round {args.round}"
    )


def _extract_description(raw: dict) -> str:
    """Manifold stores description as TipTap JSON or plain string."""
    desc = raw.get("description")
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return _walk_tiptap(desc)
    return ""


def _walk_tiptap(node) -> str:
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        content = node.get("content") or []
        return " ".join(_walk_tiptap(c) for c in content)
    if isinstance(node, list):
        return " ".join(_walk_tiptap(x) for x in node)
    return ""


if __name__ == "__main__":
    main()
