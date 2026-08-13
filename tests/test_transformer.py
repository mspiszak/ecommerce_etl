from __future__ import annotations

import pandas as pd
import pytest

from ecommerce_etl.transformer import DataTransformer


def test_init_raises_on_missing_columns():
    """Konstruktor rzuca ValueError, gdy w DataFrame brakuje wymaganych kolumn."""
    incomplete_df = pd.DataFrame({"order_id": [1], "total_amount": [100.0]})

    with pytest.raises(ValueError):
        DataTransformer(incomplete_df)


def test_init_copies_df_and_does_not_mutate_original(sample_orders_df):
    """__init__ kopiuje df - modyfikacje wewnętrzne nie wpływają na oryginał."""
    transformer = DataTransformer(sample_orders_df)
    transformer.df["total_amount"] = 0

    assert not (sample_orders_df["total_amount"] == 0).all()


def test_init_applies_country_filter(sample_orders_df):
    """country_filter ogranicza dane do wskazanych krajów."""
    transformer = DataTransformer(sample_orders_df, country_filter=["PL"])

    assert set(transformer.df["country"].unique()) == {"PL"}
    assert len(transformer.df) == 3


def test_validate_tags_invalid_status(sample_orders_df_with_unknown_status):
    """Nieznany status jest oznaczany jako INVALID w validation_status."""
    transformer = DataTransformer(sample_orders_df_with_unknown_status).validate_and_tag()

    first_row = transformer.df.iloc[0]
    assert first_row["status"] == "shipped_by_drone"
    assert first_row["validation_status"] == "INVALID"


def test_validate_tags_negative_amount_as_invalid(sample_orders_df):
    """Ujemna kwota total_amount powoduje oznaczenie wiersza jako INVALID."""
    transformer = DataTransformer(sample_orders_df).validate_and_tag()

    negative_row = transformer.df[transformer.df["order_id"] == 5].iloc[0]
    assert negative_row["total_amount"] < 0
    assert negative_row["validation_status"] == "INVALID"


def test_clean_amounts_fills_na_and_clips_negative(sample_orders_df):
    """clean_amounts uzupełnia NaN zerem i obcina wartości ujemne do 0."""
    transformer = DataTransformer(sample_orders_df).clean_amounts()

    assert transformer.df["total_amount"].isna().sum() == 0
    assert (transformer.df["total_amount"] >= 0).all()


def test_add_order_size_label_assigns_correct_buckets(sample_orders_df):
    """add_order_size_label poprawnie przypisuje XL/L/M/S wg progów kwotowych."""
    transformer = DataTransformer(sample_orders_df).clean_amounts().add_order_size_label()

    row_xl = transformer.df[transformer.df["order_id"] == 1].iloc[0]
    row_s = transformer.df[transformer.df["order_id"] == 2].iloc[0]

    assert row_xl["order_size_label"] == "XL"
    assert row_s["order_size_label"] == "S"


def test_enrich_adds_derived_columns(sample_orders_df):
    """enrich dodaje year, month, is_high_value, processed_at z poprawnymi wartościami."""
    transformer = DataTransformer(sample_orders_df).clean_amounts().enrich()

    assert {"year", "month", "is_high_value", "processed_at"} <= set(transformer.df.columns)

    row_1 = transformer.df[transformer.df["order_id"] == 1].iloc[0]
    assert row_1["year"] == 2026
    assert row_1["month"] == 5
    assert row_1["is_high_value"] == True

    row_2 = transformer.df[transformer.df["order_id"] == 2].iloc[0]
    assert row_2["is_high_value"] == False

    assert transformer.df["processed_at"].notna().all()


def test_filter_returns_completed_only(sample_orders_df):
    """filter_valid_completed zwraca tylko wiersze OK + status completed."""
    transformer = DataTransformer(sample_orders_df).clean_amounts().validate_and_tag()
    result = transformer.filter_valid_completed()

    assert (result["status"] == "completed").all()
    assert (result["validation_status"] == "OK").all()


def test_filter_valid_completed_requires_validate_and_tag_first(sample_orders_df):
    """filter_valid_completed rzuca ValueError, jeśli validate_and_tag nie było wywołane."""
    transformer = DataTransformer(sample_orders_df)

    with pytest.raises(ValueError):
        transformer.filter_valid_completed()


def test_get_summary_returns_expected_keys(sample_orders_df):
    """get_summary zwraca słownik z oczekiwanymi kluczami i poprawnym total_rows."""
    transformer = DataTransformer(sample_orders_df).clean_amounts().validate_and_tag()
    summary = transformer.get_summary()

    assert summary["total_rows"] == len(sample_orders_df)
    assert "total_revenue" in summary
    assert "countries" in summary
