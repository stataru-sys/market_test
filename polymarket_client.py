"""Read-only client for Polymarket Gamma API.

Docs: https://docs.polymarket.com/api-reference/introduction
No authentication required for public read endpoints.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import requests

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def _parse_list(val: Any) -> list:
    if val is None:
        return []
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return []
    return list(val)


@dataclass
class Market:
    id: str
    question: str
    slug: str
    category: str | None
    volume_24hr: float
    volume_total: float
    liquidity_num: float
    end_date: str | None
    active: bool
    closed: bool
    outcomes: list[str]
    outcome_prices: list[float]
    clob_token_ids: list[str]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Market:
        prices = _parse_list(data.get("outcomePrices"))
        outcomes = _parse_list(data.get("outcomes"))
        tokens = _parse_list(data.get("clobTokenIds"))

        return cls(
            id=str(data.get("id", "")),
            question=str(data.get("question", "")),
            slug=str(data.get("slug", "")),
            category=data.get("category"),
            volume_24hr=float(data.get("volume24hr") or 0),
            volume_total=float(data.get("volume") or 0),
            liquidity_num=float(data.get("liquidityNum") or data.get("liquidity") or 0),
            end_date=data.get("endDate"),
            active=bool(data.get("active", False)),
            closed=bool(data.get("closed", False)),
            outcomes=[str(o) for o in outcomes],
            outcome_prices=[float(p) for p in prices],
            clob_token_ids=[str(t) for t in tokens],
            raw=data,
        )


class PolymarketClient:
    def __init__(self, timeout: float = 10.0):
        self.session = requests.Session()
        self.timeout = timeout

    def _get(self, path: str, **params: Any) -> Any:
        response = self.session.get(
            f"{GAMMA_API}{path}", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def list_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> list[Market]:
        data = self._get(
            "/markets",
            limit=limit,
            offset=offset,
            active=str(active).lower(),
            closed=str(closed).lower(),
            order=order,
            ascending=str(ascending).lower(),
        )
        return [Market.from_api(m) for m in data]

    def get_market(self, market_id: str) -> Market:
        data = self._get(f"/markets/{market_id}")
        return Market.from_api(data)

    def get_prices_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
        start_ts: int | None = None,
        end_ts: int | None = None,
    ) -> list[dict[str, float]]:
        """Fetch historical price points for a single CLOB token (YES or NO leg).

        interval: one of 1h, 6h, 1d, 1w, 1m, max. Ignored if start_ts/end_ts set.
        fidelity: resolution in minutes (e.g. 60 = hourly points).
        Returns list of {t: unix_seconds, p: price} dicts.
        """
        params: dict[str, Any] = {"market": token_id, "fidelity": fidelity}
        if start_ts is not None and end_ts is not None:
            params["startTs"] = start_ts
            params["endTs"] = end_ts
        else:
            params["interval"] = interval

        response = self.session.get(
            f"{CLOB_API}/prices-history", params=params, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()
        return data.get("history", [])
