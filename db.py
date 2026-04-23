"""SQLite storage for Polymarket data.

Schema:
  markets       one row per market (question, metadata, YES/NO token ids)
  prices        hourly price points keyed by (token_id, ts_unix)
  sync_log      bookkeeping: last time each token's history was refreshed
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

DB_PATH = Path(__file__).parent / "data" / "polymarket.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id              TEXT PRIMARY KEY,
    question        TEXT NOT NULL,
    slug            TEXT,
    category        TEXT,
    end_date        TEXT,
    active          INTEGER,
    closed          INTEGER,
    volume_24hr     REAL,
    volume_total    REAL,
    liquidity       REAL,
    outcomes_json   TEXT,
    token_yes       TEXT,
    token_no        TEXT,
    last_synced     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_markets_vol ON markets(volume_24hr DESC);
CREATE INDEX IF NOT EXISTS idx_markets_closed ON markets(closed, active);

CREATE TABLE IF NOT EXISTS prices (
    token_id   TEXT NOT NULL,
    ts_unix    INTEGER NOT NULL,
    price      REAL NOT NULL,
    PRIMARY KEY (token_id, ts_unix)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sync_log (
    token_id      TEXT PRIMARY KEY,
    last_synced   INTEGER NOT NULL,
    point_count   INTEGER NOT NULL
);
"""


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_market(conn: sqlite3.Connection, market) -> None:
    token_yes = market.clob_token_ids[0] if len(market.clob_token_ids) >= 1 else None
    token_no = market.clob_token_ids[1] if len(market.clob_token_ids) >= 2 else None
    conn.execute(
        """
        INSERT INTO markets (
            id, question, slug, category, end_date, active, closed,
            volume_24hr, volume_total, liquidity,
            outcomes_json, token_yes, token_no, last_synced
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            question=excluded.question,
            slug=excluded.slug,
            category=excluded.category,
            end_date=excluded.end_date,
            active=excluded.active,
            closed=excluded.closed,
            volume_24hr=excluded.volume_24hr,
            volume_total=excluded.volume_total,
            liquidity=excluded.liquidity,
            outcomes_json=excluded.outcomes_json,
            token_yes=excluded.token_yes,
            token_no=excluded.token_no,
            last_synced=excluded.last_synced
        """,
        (
            market.id,
            market.question,
            market.slug,
            market.category,
            market.end_date,
            int(market.active),
            int(market.closed),
            market.volume_24hr,
            market.volume_total,
            market.liquidity_num,
            json.dumps(market.outcomes),
            token_yes,
            token_no,
            int(time.time()),
        ),
    )


def upsert_prices(
    conn: sqlite3.Connection, token_id: str, points: Iterable[dict]
) -> int:
    rows = [(token_id, int(p["t"]), float(p["p"])) for p in points]
    if not rows:
        return 0
    conn.executemany(
        "INSERT OR REPLACE INTO prices (token_id, ts_unix, price) VALUES (?,?,?)",
        rows,
    )
    conn.execute(
        """
        INSERT INTO sync_log (token_id, last_synced, point_count)
        VALUES (?, ?, ?)
        ON CONFLICT(token_id) DO UPDATE SET
            last_synced=excluded.last_synced,
            point_count=excluded.point_count
        """,
        (token_id, int(time.time()), len(rows)),
    )
    return len(rows)


def market_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]


def price_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
