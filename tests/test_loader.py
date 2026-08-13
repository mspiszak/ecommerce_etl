from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ecommerce_etl.loader import S3Loader


def test_upload_skips_empty_df(mock_boto3_client):
    """upload_dataframe nie wywołuje boto3 (put_object), gdy df jest pusty."""
    loader = S3Loader(bucket="test-bucket", region="eu-central-1")
    empty_df = pd.DataFrame(columns=["order_id", "total_amount"])

    result = loader.upload_dataframe(empty_df, key="raw/orders/data.parquet")

    assert result is False
    mock_boto3_client.put_object.assert_not_called()


def test_build_partition_key_format():
    """build_partition_key generuje poprawny Hive-style klucz S3 (bez AWS!)."""
    key = S3Loader.build_partition_key(
        prefix="raw", entity="orders", partition_date=date(2026, 7, 29)
    )

    assert key == "raw/orders/year=2026/month=07/day=29/data.parquet"


def test_build_partition_key_strips_slashes():
    """build_partition_key normalizuje prefix/entity z wiodącymi/końcowymi slashami."""
    key = S3Loader.build_partition_key(
        prefix="/raw/", entity="/orders/", partition_date=date(2025, 1, 5)
    )

    assert key == "raw/orders/year=2025/month=01/day=05/data.parquet"


def test_upload_dataframe_calls_put_object_with_correct_bucket_and_key(mock_boto3_client):
    """upload_dataframe wywołuje put_object z poprawnym bucketem i kluczem (mock boto3)."""
    loader = S3Loader(bucket="test-bucket", region="eu-central-1")
    df = pd.DataFrame({"order_id": [1, 2], "total_amount": [100.0, 200.0]})

    result = loader.upload_dataframe(df, key="raw/orders/year=2026/month=07/day=29/data.parquet")

    assert result is True
    mock_boto3_client.put_object.assert_called_once()
    _, kwargs = mock_boto3_client.put_object.call_args
    assert kwargs["Bucket"] == "test-bucket"
    assert kwargs["Key"] == "raw/orders/year=2026/month=07/day=29/data.parquet"


def test_upload_monthly_snapshots_splits_by_month(mock_boto3_client, sample_orders_df):
    """upload_monthly_snapshots dzieli dane po miesiącach i uploaduje każdy osobno."""
    loader = S3Loader(bucket="test-bucket", region="eu-central-1")

    keys = loader.upload_monthly_snapshots(sample_orders_df, entity="orders")

    # sample_orders_df zawiera daty z maja, czerwca i lipca 2026 -> 3 miesiące
    assert len(keys) == 3
    assert mock_boto3_client.put_object.call_count == 3
    assert all("year=2026" in key for key in keys)


def test_upload_monthly_snapshots_returns_empty_list_for_empty_df(mock_boto3_client, empty_orders_df):
    """upload_monthly_snapshots zwraca pustą listę i nie wywołuje boto3 dla pustego df."""
    loader = S3Loader(bucket="test-bucket", region="eu-central-1")

    keys = loader.upload_monthly_snapshots(empty_orders_df, entity="orders")

    assert keys == []
    mock_boto3_client.put_object.assert_not_called()
