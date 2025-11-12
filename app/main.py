from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ib_client import client
from .schemas import HistoricalDataResponse, MarketSnapshot, MarketSnapshotList
from .settings import get_settings

settings = get_settings()

app = FastAPI(title="Local NQ Scanner Market Data API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.http_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    await client.connect()
    await client.ensure_subscriptions()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/market/overall", response_model=MarketSnapshot)
async def market_overall() -> MarketSnapshot:
    snapshot = await client.get_overall()
    if not snapshot:
        raise HTTPException(status_code=503, detail="No market data available for overall symbol")
    return MarketSnapshot(**snapshot)


@app.get("/market/components", response_model=MarketSnapshotList)
async def market_components() -> MarketSnapshotList:
    snapshots = await client.get_components()
    return MarketSnapshotList(data=[MarketSnapshot(**snap) for snap in snapshots])


@app.get("/market/symbol/{symbol}", response_model=MarketSnapshot)
async def market_symbol(symbol: str) -> MarketSnapshot:
    snapshot = await client.get_snapshot(symbol)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Symbol not subscribed")
    return MarketSnapshot(**snapshot)


@app.get("/market/history/{symbol}", response_model=HistoricalDataResponse)
async def market_history(
    symbol: str,
    interval: str = "5m",
    limit: Optional[int] = None,
    rth: Optional[bool] = None,
) -> HistoricalDataResponse:
    try:
        resolved_interval, bars = await client.get_historical(
            symbol=symbol,
            interval=interval,
            limit=limit or settings.historical_defaults["limit"],
            regular_trading_hours=rth if rth is not None else settings.historical_defaults["regular_trading_hours"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - IB errors
        raise HTTPException(status_code=502, detail="Failed to fetch historical data") from exc

    return HistoricalDataResponse(symbol=symbol.upper(), interval=resolved_interval, bars=bars)
