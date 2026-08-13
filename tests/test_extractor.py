from __future__ import annotations

import pandas as pd
import pytest

from ecommerce_etl.extractor import OrderExtractor


def test_extract_orders_raises_on_invalid_days_back(mock_engine):
    """days_back <= 0 powinno rzucić ValueError, bez wywołania bazy."""
    extractor = OrderExtractor(mock_engine)

    with pytest.raises(ValueError):
        extractor.extract_orders(days_back=0)

    with pytest.raises(ValueError):
        extractor.extract_orders(days_back=-5)


def test_extract_orders_uses_bind_param_not_fstring(mock_engine, monkeypatch):
    """extract_orders musi przekazywać `days` jako bind param, nie przez f-string."""
    captured = {}

    def fake_read_sql(query, con, params=None):
        captured["query_text"] = str(query)
        captured["params"] = params
        return pd.DataFrame({"order_id": [1]})

    monkeypatch.setattr("ecommerce_etl.extractor.pd.read_sql", fake_read_sql)

    extractor = OrderExtractor(mock_engine)
    df = extractor.extract_orders(days_back=14)

    assert captured["params"] == {"days": 14}
    assert ":days" in captured["query_text"]
    assert "14" not in captured["query_text"]
    assert not df.empty


def test_extract_top_customers_raises_on_invalid_limit(mock_engine):
    """limit <= 0 powinno rzucić ValueError, bez wywołania bazy."""
    extractor = OrderExtractor(mock_engine)

    with pytest.raises(ValueError):
        extractor.extract_top_customers(limit=0)


def test_extract_monthly_revenue_returns_dataframe(mock_engine, monkeypatch):
    """extract_monthly_revenue zwraca DataFrame z wymaganymi kolumnami."""
    expected_df = pd.DataFrame(
        {
            "month": ["2026-06", "2026-07"],
            "revenue": [1000.0, 1500.0],
            "orders": [5, 8],
            "mom_growth_pct": [None, 50.0],
        }
    )
    monkeypatch.setattr("ecommerce_etl.extractor.pd.read_sql", lambda query, con: expected_df)

    extractor = OrderExtractor(mock_engine)
    df = extractor.extract_monthly_revenue()

    assert list(df.columns) == ["month", "revenue", "orders", "mom_growth_pct"]
    assert len(df) == 2


def test_extract_top_customers_uses_limit_bind_param(mock_engine, monkeypatch):
    """extract_top_customers przekazuje limit jako bind param `:limit`."""
    captured = {}

    def fake_read_sql(query, con, params=None):
        captured["query_text"] = str(query)
        captured["params"] = params
        return pd.DataFrame({"customer_id": [1], "customer_rank": [1]})

    monkeypatch.setattr("ecommerce_etl.extractor.pd.read_sql", fake_read_sql)

    extractor = OrderExtractor(mock_engine)
    extractor.extract_top_customers(limit=5)

    assert captured["params"] == {"limit": 5}
    assert "RANK()" in captured["query_text"] or "RANK ()" in captured["query_text"]
