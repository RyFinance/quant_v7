"""Unified market data schema for quant_v7.

Extends the quant_v6 roadmap's `MarketTick` pattern (ticker/timestamp/OHLCV/
asset_class) with an explicit `source` field, per the v7 spec's requirement
that every bar be traceable to its data provider (needed once survivorship-
bias-adjusted history is stitched together from multiple sources).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AssetClass(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"


class DataSource(str, Enum):
    YFINANCE = "yfinance"
    WIKIPEDIA = "wikipedia"
    SYNTHETIC = "synthetic"  # test fixtures only, never real ingestion


class OHLCVBar(BaseModel):
    """A single daily OHLCV bar for one ticker."""

    ticker: str
    timestamp: datetime
    open: float = Field(gt=0)
    low: float = Field(gt=0)
    high: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    asset_class: AssetClass = AssetClass.EQUITY
    source: DataSource = DataSource.YFINANCE

    @field_validator("high")
    @classmethod
    def high_is_max(cls, v, info):
        # `low` must be declared before `high` above -- pydantic only populates
        # info.data with fields already validated in declaration order.
        lo = info.data.get("low")
        if lo is not None and v < lo:
            raise ValueError(f"high ({v}) < low ({lo})")
        return v

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, v: str) -> str:
        return v.strip().upper()


class UniverseMember(BaseModel):
    """One historical membership record: ticker was in the universe over [start, end]."""

    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    start_date: datetime
    end_date: Optional[datetime] = None  # None == still a member as of source fetch time

    @field_validator("ticker")
    @classmethod
    def ticker_upper(cls, v: str) -> str:
        return v.strip().upper()
