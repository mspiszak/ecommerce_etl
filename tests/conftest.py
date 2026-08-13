from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def sample_orders_df() -> pd.DataFrame:
    """Przykładowy DataFrame zamówień zgodny ze schematem OrderExtractor.extract_orders."""
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5],
            "customer_id": [10, 10, 11, 12, 13],
            "full_name": ["Jan Kowalski", "Jan Kowalski", "Anna Nowak", "Piotr Wiśniewski", "Ewa Zielińska"],
            "country": ["PL", "PL", "DE", "PL", "FR"],
            "ordered_at": pd.to_datetime(
                ["2026-05-01", "2026-05-15", "2026-06-01", "2026-06-10", "2026-07-01"]
            ),
            "status": ["completed", "completed", "pending", "cancelled", "completed"],
            "total_amount": [1200.0, 50.0, None, 300.0, -20.0],
        }
    )


@pytest.fixture
def sample_orders_df_with_unknown_status(sample_orders_df: pd.DataFrame) -> pd.DataFrame:
    """Wariant z nieznanym statusem, do testowania validate_and_tag."""
    df = sample_orders_df.copy()
    df.loc[0, "status"] = "shipped_by_drone"  # status spoza KNOWN_STATUSES
    return df


@pytest.fixture
def empty_orders_df() -> pd.DataFrame:
    """Pusty DataFrame z poprawnym schematem kolumn (0 wierszy)."""
    return pd.DataFrame(
        columns=[
            "order_id",
            "customer_id",
            "full_name",
            "country",
            "ordered_at",
            "status",
            "total_amount",
        ]
    )


@pytest.fixture
def mock_engine() -> MagicMock:
    """Mock SQLAlchemy Engine - nie łączy się z realną bazą danych."""
    engine = MagicMock()
    engine.url.database = "test_db"
    return engine


@pytest.fixture
def mock_boto3_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Podmienia boto3.client('s3', ...) na mocka, bez realnych wywołań AWS."""
    mock_client = MagicMock()
    monkeypatch.setattr("ecommerce_etl.loader.boto3.client", lambda *a, **kw: mock_client)
    return mock_client
