from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class MarketSnapshot(BaseModel):
    symbol: str
    price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    timestamp: Optional[str] = None


class MarketSnapshotList(BaseModel):
    data: List[MarketSnapshot]


class HistoricalBar(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None


class HistoricalDataResponse(BaseModel):
    symbol: str
    interval: str
    bars: List[HistoricalBar]
