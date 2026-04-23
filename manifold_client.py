"""Client for Manifold Markets REST API.

Docs: https://docs.manifold.markets/api
Base URL: https://api.manifold.markets/v0
Auth (for write ops): header "Authorization: Key <api_key>"
Rate limit: 500 req/min.

Manifold is play-money only since March 2025 — all bets use "mana" (M$),
which is not redeemable. Used here for safe paper-trading / calibration.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

MANIFOLD_API = "https://api.manifold.markets/v0"


@dataclass
class ManifoldUser:
    id: str
    username: str
    name: str
    balance: float
    total_deposits: float
    created_time: int
    profit_cached_all_time: float | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ManifoldUser:
        return cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            name=data.get("name", ""),
            balance=float(data.get("balance", 0)),
            total_deposits=float(data.get("totalDeposits", 0)),
            created_time=int(data.get("createdTime", 0)),
            profit_cached_all_time=(
                float(data["profitCached"]["allTime"])
                if "profitCached" in data and "allTime" in data["profitCached"]
                else None
            ),
            raw=data,
        )


@dataclass
class ManifoldMarket:
    id: str
    question: str
    slug: str
    url: str
    outcome_type: str
    probability: float | None
    volume: float
    volume_24h: float
    close_time: int | None
    is_resolved: bool
    resolution: str | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ManifoldMarket:
        return cls(
            id=data.get("id", ""),
            question=data.get("question", ""),
            slug=data.get("slug", ""),
            url=data.get("url", ""),
            outcome_type=data.get("outcomeType", ""),
            probability=(
                float(data["probability"]) if "probability" in data else None
            ),
            volume=float(data.get("volume", 0)),
            volume_24h=float(data.get("volume24Hours", 0)),
            close_time=int(data["closeTime"]) if data.get("closeTime") else None,
            is_resolved=bool(data.get("isResolved", False)),
            resolution=data.get("resolution"),
            raw=data,
        )


class ManifoldClient:
    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.environ.get("MANIFOLD_API_KEY")
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self, auth: bool = False) -> dict[str, str]:
        h = {"Accept": "application/json"}
        if auth:
            if not self.api_key:
                raise RuntimeError(
                    "MANIFOLD_API_KEY not set — put it in .env or pass api_key="
                )
            h["Authorization"] = f"Key {self.api_key}"
        return h

    def _get(self, path: str, auth: bool = False, **params: Any) -> Any:
        response = self.session.get(
            f"{MANIFOLD_API}{path}",
            params=params,
            headers=self._headers(auth=auth),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, json: dict[str, Any]) -> Any:
        response = self.session.post(
            f"{MANIFOLD_API}{path}",
            json=json,
            headers={**self._headers(auth=True), "Content-Type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # --- Read (no auth required) ---

    def me(self) -> ManifoldUser:
        """Current authenticated user."""
        data = self._get("/me", auth=True)
        return ManifoldUser.from_api(data)

    def user_by_username(self, username: str) -> ManifoldUser:
        return ManifoldUser.from_api(self._get(f"/user/{username}"))

    def list_markets(self, limit: int = 100, before: str | None = None) -> list[ManifoldMarket]:
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before
        data = self._get("/markets", **params)
        return [ManifoldMarket.from_api(m) for m in data]

    def search_markets(
        self,
        term: str = "",
        limit: int = 50,
        sort: str = "score",  # score, newest, liquidity, close-date, ...
        filter: str = "open",  # open, closed, resolved, all
    ) -> list[ManifoldMarket]:
        data = self._get(
            "/search-markets", term=term, limit=limit, sort=sort, filter=filter
        )
        return [ManifoldMarket.from_api(m) for m in data]

    def get_market(self, market_id: str) -> ManifoldMarket:
        return ManifoldMarket.from_api(self._get(f"/market/{market_id}"))

    # --- Write (auth required) ---

    def place_bet(
        self,
        contract_id: str,
        amount: float,
        outcome: str,  # "YES" or "NO"
        limit_prob: float | None = None,
    ) -> dict[str, Any]:
        """Place a bet. amount is in mana (M$). outcome: YES/NO."""
        payload: dict[str, Any] = {
            "contractId": contract_id,
            "amount": amount,
            "outcome": outcome,
        }
        if limit_prob is not None:
            payload["limitProb"] = limit_prob
        return self._post("/bet", payload)

    def cancel_bet(self, bet_id: str) -> dict[str, Any]:
        return self._post(f"/bet/cancel/{bet_id}", {})
