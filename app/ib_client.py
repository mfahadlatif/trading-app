from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import math

from ib_insync import IB, Index, Stock, Ticker, util

from .settings import get_settings

logger = logging.getLogger(__name__)


HISTORICAL_INTERVAL_CONFIG: Dict[str, Tuple[str, str]] = {
    "1s": ("600 S", "1 secs"),
    "5s": ("3600 S", "5 secs"),
    "10s": ("7200 S", "10 secs"),
    "15s": ("14400 S", "15 secs"),
    "30s": ("28800 S", "30 secs"),
    "1m": ("2 D", "1 min"),
    "2m": ("3 D", "2 mins"),
    "3m": ("3 D", "3 mins"),
    "5m": ("5 D", "5 mins"),
    "10m": ("2 W", "10 mins"),
    "15m": ("3 W", "15 mins"),
    "30m": ("1 M", "30 mins"),
    "1h": ("1 M", "1 hour"),
    "2h": ("2 M", "2 hours"),
    "3h": ("3 M", "3 hours"),
    "4h": ("3 M", "4 hours"),
    "1d": ("1 Y", "1 day"),
    "1w": ("2 Y", "1 week"),
    "1mo": ("5 Y", "1 month"),
    "3mo": ("10 Y", "1 month"),
}

HISTORICAL_INTERVAL_ALIAS: Dict[str, str] = {
    "1tick": "1s",
    "10ticks": "1s",
    "100ticks": "5s",
    "1000ticks": "10s",
    "45s": "30s",
    "45m": "30m",
}


class MarketDataCache:
    """Thread-safe store for latest market data snapshots."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, object]] = {}

    def update(self, symbol: str, payload: Dict[str, object]) -> None:
        self._data[symbol] = payload

    def get(self, symbol: str) -> Optional[Dict[str, object]]:
        return self._data.get(symbol)

    def list_symbols(self, symbols: List[str]) -> List[Dict[str, object]]:
        return [self._data[s] for s in symbols if s in self._data]


class IBMarketDataClient:
    """Manage connection to IB Gateway and aggregate market data."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.ib = IB()
        self.cache = MarketDataCache()
        self._contracts = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _normalize_value(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            if value == -1.0:
                return None
            if isinstance(value, float) and (math.isnan(value) or not math.isfinite(value)):
                return None
        return value

    async def connect(self) -> None:
        if self.ib.isConnected():
            return

        logger.info(
            "Connecting to IB Gateway at %s:%s (clientId=%s)",
            self.settings.ib_host,
            self.settings.ib_port,
            self.settings.ib_client_id,
        )

        try:
            await asyncio.wait_for(
                self.ib.connectAsync(
                    host=self.settings.ib_host,
                    port=self.settings.ib_port,
                    clientId=self.settings.ib_client_id,
                ),
                timeout=self.settings.ib_connect_timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.exception("IB connection timed out")
            raise ConnectionError("Timed out connecting to IB Gateway") from exc

        logger.info("Connected to IB Gateway")
        self.ib.pendingTickersEvent += self._on_tickers
        self.ib.reqMarketDataType(self.settings.ib_market_data_type)
        logger.info("Requested market data type %s", self.settings.ib_market_data_type)

    async def ensure_subscriptions(self) -> None:
        """Qualify and subscribe to index + components."""

        async with self._lock:
            if self._contracts:
                return

            logger.info("Qualifying NASDAQ contracts")

            index_contract = Index(
                symbol=self.settings.nq_overall_symbol,
                exchange="NASDAQ",
                currency="USD",
            )
            await self.ib.qualifyContractsAsync(index_contract)
            self._contracts[self.settings.nq_overall_symbol] = index_contract
            self.ib.reqMktData(index_contract, "", False, False)

            for symbol in self.settings.nq_component_symbols:
                contract = Stock(symbol, exchange="SMART", currency="USD")
                try:
                    await self.ib.qualifyContractsAsync(contract)
                except Exception:
                    logger.exception("Failed to qualify contract for %s", symbol)
                    continue
                self._contracts[symbol] = contract
                self.ib.reqMktData(contract, "", False, False)

            logger.info("Subscribed to %d contracts", len(self._contracts))

    def _on_tickers(self, tickers: List[Ticker]) -> None:
        for ticker in tickers:
            symbol = ticker.contract.symbol
            if symbol not in self._contracts:
                continue

            volume = ticker.volume
            if isinstance(volume, float) and (math.isnan(volume) or not math.isfinite(volume)):
                volume = None

            snapshot = {
                "symbol": symbol,
                "price": self._normalize_value(ticker.marketPrice()),
                "bid": self._normalize_value(ticker.bid),
                "ask": self._normalize_value(ticker.ask),
                "open": self._normalize_value(ticker.open),
                "high": self._normalize_value(ticker.high),
                "low": self._normalize_value(ticker.low),
                "close": self._normalize_value(ticker.close),
                "volume": int(volume) if isinstance(volume, (int, float)) and volume is not None else None,
                "timestamp": (ticker.time or datetime.now(timezone.utc)).isoformat(),
            }
            self.cache.update(symbol, snapshot)

    async def get_overall(self) -> Optional[Dict[str, object]]:
        await self.connect()
        await self.ensure_subscriptions()
        return self.cache.get(self.settings.nq_overall_symbol)

    async def get_components(self) -> List[Dict[str, object]]:
        await self.connect()
        await self.ensure_subscriptions()
        return self.cache.list_symbols(self.settings.nq_component_symbols)

    async def get_snapshot(self, symbol: str) -> Optional[Dict[str, object]]:
        await self.connect()
        await self.ensure_subscriptions()
        normalized = symbol.upper()

        if normalized == self.settings.nq_overall_symbol.upper():
            return self.cache.get(self.settings.nq_overall_symbol)

        if normalized not in self.settings.nq_component_symbols:
            return None

        return self.cache.get(normalized)

    def is_tracked_symbol(self, symbol: str) -> bool:
        normalized = symbol.upper()
        if normalized == "Q-50":
            normalized = self.settings.nq_overall_symbol.upper()

        if normalized == self.settings.nq_overall_symbol.upper():
            return True

        return normalized in self.settings.nq_component_symbols

    @staticmethod
    def _resolve_interval(interval: str) -> str:
        normalized = interval.lower()
        normalized = HISTORICAL_INTERVAL_ALIAS.get(normalized, normalized)
        if normalized not in HISTORICAL_INTERVAL_CONFIG:
            raise ValueError(f"Unsupported interval '{interval}' for historical data")
        return normalized

    async def get_historical(
        self,
        symbol: str,
        interval: str,
        limit: int = 300,
        regular_trading_hours: bool = False,
    ) -> Tuple[str, List[Dict[str, object]]]:
        if limit <= 0:
            raise ValueError("limit must be positive")

        resolved_interval = self._resolve_interval(interval)

        if not self.is_tracked_symbol(symbol):
            raise ValueError(f"Symbol '{symbol}' is not configured for tracking")

        await self.connect()
        await self.ensure_subscriptions()

        normalized_symbol = symbol.upper()
        if normalized_symbol == "Q-50":
            normalized_symbol = self.settings.nq_overall_symbol.upper()

        contract = self._contracts.get(normalized_symbol)
        if contract is None:
            raise ValueError(f"Symbol '{symbol}' is not subscribed")

        duration_str, bar_size = HISTORICAL_INTERVAL_CONFIG[resolved_interval]

        what_to_show = "MIDPOINT" if getattr(contract, "secType", "").upper() == "IND" else "TRADES"

        try:
            bars = await asyncio.wait_for(
                self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=duration_str,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=regular_trading_hours,
                    formatDate=2,
                    keepUpToDate=False,
                ),
                timeout=self.settings.historical_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            logger.error(
                "Timed out waiting for historical data for symbol %s (interval=%s, duration=%s)",
                symbol,
                resolved_interval,
                duration_str,
            )
            raise TimeoutError("Timed out waiting for historical data from IB Gateway") from exc
        except Exception as exc:  # pragma: no cover - IB errors
            logger.exception("Failed to load historical data for %s", symbol)
            raise

        sliced = list(bars[-limit:])

        normalized_bars: List[Dict[str, object]] = []
        for bar in sliced:
            raw_timestamp = bar.date
            if isinstance(raw_timestamp, datetime):
                timestamp = raw_timestamp if raw_timestamp.tzinfo else raw_timestamp.replace(tzinfo=timezone.utc)
            else:
                parsed = util.parseIBDatetime(raw_timestamp)
                timestamp = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

            normalized_bars.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume) if bar.volume is not None else None,
                }
            )

        return resolved_interval, normalized_bars


client = IBMarketDataClient()
