from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Kolumny wymagane na wejściu
REQUIRED_COLUMNS = {
    "order_id",
    "customer_id",
    "full_name",
    "country",
    "ordered_at",
    "status",
    "total_amount",
}

# Statusy uznawane za poprawne
KNOWN_STATUSES = {"completed", "pending", "cancelled", "refunded"}

# Progi wartości zamówienia (waluta) do etykietowania rozmiaru
SIZE_THRESHOLDS = {
    "XL": 1000.0,
    "L": 500.0,
    "M": 100.0,
}

# Próg od którego zamówienie jest uznawane za "wysokiej wartości"
HIGH_VALUE_THRESHOLD = 500.0


class DataTransformer:
    """
    Waliduje, czyści i wzbogaca DataFrame z zamówieniami.
    """

    def __init__(self, df: pd.DataFrame, country_filter: list[str] | None = None) -> None:
        """
        Parameters
        ----------
        df : pd.DataFrame
            Surowy DataFrame (np. z `OrderExtractor.extract_orders`).
            Kopiowany wewnętrznie - oryginał nie jest modyfikowany.
        country_filter : list[str] | None
            Opcjonalna lista krajów, do których ograniczamy dane
            (np. ["PL", "DE"]). Jeśli None - brak filtrowania.

        Raises
        ------
        ValueError
            Gdy w `df` brakuje wymaganych kolumn.
        """
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            logger.error("DataTransformer.__init__: brak wymaganych kolumn: %s", missing)
            raise ValueError(f"Brak wymaganych kolumn w DataFrame: {sorted(missing)}")

        self.df: pd.DataFrame = df.copy()
        self.country_filter = country_filter

        if country_filter:
            before = len(self.df)
            self.df = self.df[self.df["country"].isin(country_filter)].copy()
            logger.info(
                "DataTransformer.__init__: filtr krajów %s zredukował dane z %d do %d wierszy",
                country_filter,
                before,
                len(self.df),
            )

        logger.info("DataTransformer zainicjalizowany (%d wierszy)", len(self.df))

    # ------------------------------------------------------------------
    def validate_and_tag(self) -> "DataTransformer":
        """
        Dodaje kolumnę `validation_status` (OK / INVALID) na podstawie
        prostych reguł biznesowych sprawdzanych if/elif per wiersz:
        - status musi należeć do zbioru znanych statusów,
        - total_amount nie może być NaN ani ujemny,
        - customer_id / full_name nie mogą być puste.

        Returns
        -------
        DataTransformer
            self (do łączenia w łańcuch).
        """

        def _tag(row: pd.Series) -> str:
            if pd.isna(row.get("customer_id")) or not row.get("full_name"):
                return "INVALID"
            elif row.get("status") not in KNOWN_STATUSES:
                return "INVALID"
            elif pd.isna(row.get("total_amount")) or row.get("total_amount") < 0:
                return "INVALID"
            else:
                return "OK"

        self.df["validation_status"] = self.df.apply(_tag, axis=1)

        n_invalid = int((self.df["validation_status"] == "INVALID").sum())
        if n_invalid:
            logger.warning("validate_and_tag: oznaczono %d wierszy jako INVALID", n_invalid)
        else:
            logger.info("validate_and_tag: wszystkie %d wierszy poprawne (OK)", len(self.df))

        return self

    # ------------------------------------------------------------------
    def clean_amounts(self) -> "DataTransformer":
        """
        Czyści kolumnę `total_amount`:
        - braki (NaN) -> 0,
        - wartości ujemne -> obcięte do 0 (clip).

        Returns
        -------
        DataTransformer
            self (do łączenia w łańcuch).
        """
        n_missing = int(self.df["total_amount"].isna().sum())
        self.df["total_amount"] = self.df["total_amount"].fillna(0)
        self.df["total_amount"] = self.df["total_amount"].clip(lower=0)

        if n_missing:
            logger.warning("clean_amounts: uzupełniono %d brakujących wartości total_amount", n_missing)
        else:
            logger.info("clean_amounts: brak braków w total_amount")

        return self

    # ------------------------------------------------------------------
    def add_order_size_label(self) -> "DataTransformer":
        """
        Dodaje kolumnę `order_size_label` (XL/L/M/S) na podstawie progów
        kwotowych, obliczaną wektorowo przez `np.select`.

        Returns
        -------
        DataTransformer
            self (do łączenia w łańcuch).
        """
        conditions = [
            self.df["total_amount"] >= SIZE_THRESHOLDS["XL"],
            self.df["total_amount"] >= SIZE_THRESHOLDS["L"],
            self.df["total_amount"] >= SIZE_THRESHOLDS["M"],
        ]
        choices = ["XL", "L", "M"]

        self.df["order_size_label"] = np.select(conditions, choices, default="S")

        logger.info(
            "add_order_size_label: rozkład etykiet -> %s",
            self.df["order_size_label"].value_counts().to_dict(),
        )
        return self

    # ------------------------------------------------------------------
    def enrich(self) -> "DataTransformer":
        """
        Dodaje kolumny pochodne:
        - year, month (z `ordered_at`),
        - is_high_value (total_amount > HIGH_VALUE_THRESHOLD),
        - processed_at (znacznik czasu przetworzenia, UTC).

        Returns
        -------
        DataTransformer
            self (do łączenia w łańcuch).
        """
        ordered_at = pd.to_datetime(self.df["ordered_at"])
        self.df["year"] = ordered_at.dt.year
        self.df["month"] = ordered_at.dt.month
        self.df["is_high_value"] = self.df["total_amount"] > HIGH_VALUE_THRESHOLD
        self.df["processed_at"] = datetime.now(timezone.utc)

        logger.info("enrich: dodano kolumny year, month, is_high_value, processed_at")
        return self

    # ------------------------------------------------------------------
    def filter_valid_completed(self) -> pd.DataFrame:
        """
        Zwraca tylko wiersze z `validation_status == 'OK'` oraz
        `status == 'completed'`.

        Wymaga wcześniejszego wywołania `validate_and_tag()`.

        Returns
        -------
        pd.DataFrame
            Przefiltrowany DataFrame (kopia).
        """
        if "validation_status" not in self.df.columns:
            logger.error("filter_valid_completed: brak kolumny validation_status - wywołaj najpierw validate_and_tag()")
            raise ValueError("Najpierw wywołaj validate_and_tag() przed filter_valid_completed()")

        mask = (self.df["validation_status"] == "OK") & (self.df["status"] == "completed")
        result = self.df[mask].copy()

        logger.info(
            "filter_valid_completed: %d / %d wierszy przeszło filtr (OK + completed)",
            len(result),
            len(self.df),
        )
        if result.empty:
            logger.warning("filter_valid_completed: wynik jest pusty")

        return result

    # ------------------------------------------------------------------
    def get_summary(self) -> dict:
        """
        Zwraca podsumowanie bieżącego stanu DataFrame - przydatne do
        logowania / raportowania po zakończeniu pipeline'u.

        Returns
        -------
        dict
            Klucze: total_rows, total_revenue, valid_rows, invalid_rows,
            countries, date_range.
        """
        total_rows = len(self.df)
        total_revenue = float(self.df["total_amount"].sum()) if total_rows else 0.0

        valid_rows = (
            int((self.df["validation_status"] == "OK").sum())
            if "validation_status" in self.df.columns
            else None
        )
        invalid_rows = (
            int((self.df["validation_status"] == "INVALID").sum())
            if "validation_status" in self.df.columns
            else None
        )

        summary = {
            "total_rows": total_rows,
            "total_revenue": round(total_revenue, 2),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "countries": sorted(self.df["country"].dropna().unique().tolist()) if total_rows else [],
            "date_range": (
                [str(self.df["ordered_at"].min()), str(self.df["ordered_at"].max())]
                if total_rows
                else []
            ),
        }

        logger.info("get_summary: %s", summary)
        return summary
