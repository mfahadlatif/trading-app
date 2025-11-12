from functools import lru_cache
from typing import Dict, List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    ib_host: str = Field("127.0.0.1", description="Hostname or IP of the IB Gateway/TWS instance")
    ib_port: int = Field(4001, description="Socket port configured in IB Gateway/TWS")
    ib_client_id: int = Field(111, description="Client ID used for the API session")
    ib_connect_timeout: float = Field(5.0, description="Timeout in seconds for initial IB connection")
    ib_market_data_type: int = Field(
        3,
        description="Market data type (1=real-time, 2=frozen, 3=delayed, 4=delayed-frozen)",
    )

    nq_overall_symbol: str = Field("NDX", description="Symbol used to represent the NASDAQ-100 index")
    nq_component_symbols: List[str] = Field(
        default_factory=lambda: [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST", "NFLX",
            "ADBE", "PEP", "CSCO", "CMCSA", "TMUS", "INTC", "AMD", "INTU", "TXN", "QCOM",
            "AMGN", "HON", "AMAT", "SBUX", "PYPL", "BKNG", "ISRG", "ADI", "GILD", "MDLZ",
            "VRTX", "ADP", "REGN", "LRCX", "PANW", "MU", "SNPS", "CDNS", "KLAC", "ASML",
            "MELI", "ABNB", "MAR", "CRWD", "CSX", "ORLY", "CHTR", "NXPI", "WDAY", "ADSK",
        ],
        description="List of NASDAQ-100 component symbols to subscribe to",
    )

    http_cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8081",
            "http://127.0.0.1:8081",
        ],
        description="Allowed CORS origins",
    )

    historical_defaults: Dict[str, object] = Field(
        default_factory=lambda: {
            "limit": 300,
            "regular_trading_hours": False,
        },
        description="Default parameters for historical data requests",
    )

    historical_timeout_seconds: float = Field(
        10.0,
        description="Maximum seconds to wait for an IB historical data response",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
