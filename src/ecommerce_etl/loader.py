from __future__ import annotations

import logging
from datetime import date, datetime
from io import BytesIO

import boto3
import pandas as pd

logger = logging.getLogger(__name__)


class S3Loader:
    """
    Ładuje DataFrame do S3 Data Lake w formacie parquet, z
    partycjonowaniem Hive-style (year=YYYY/month=MM/day=DD).
    """

    def __init__(self, bucket: str, region: str = "eu-central-1") -> None:
        """
        Parameters
        ----------
        bucket : str
            Nazwa bucketu S3, do którego zapisywane są dane.
        region : str
            Region AWS (domyślnie eu-central-1).
        """
        self.bucket = bucket
        self.region = region
        self.client = boto3.client("s3", region_name=region)
        logger.info("S3Loader zainicjalizowany (bucket=%s, region=%s)", bucket, region)

    # ------------------------------------------------------------------
    def upload_dataframe(self, df: pd.DataFrame, key: str) -> bool:
        """
        Zapisuje DataFrame jako parquet pod wskazanym kluczem S3.

        Jeśli `df` jest pusty, upload jest pomijany (żadne wywołanie
        boto3 nie następuje) - tylko WARNING w logu.

        Parameters
        ----------
        df : pd.DataFrame
            Dane do zapisania.
        key : str
            Pełna ścieżka (klucz) obiektu w S3, np.
            "raw/orders/year=2026/month=07/day=29/data.parquet".

        Returns
        -------
        bool
            True jeśli upload się powiódł, False jeśli pominięty
            (pusty df) lub zakończył się błędem.
        """
        if df is None or df.empty:
            logger.warning("upload_dataframe: pusty DataFrame - pomijam upload do %s", key)
            return False

        buffer = BytesIO()
        try:
            df.to_parquet(buffer, index=False)
            buffer.seek(0)
            self.client.put_object(Bucket=self.bucket, Key=key, Body=buffer.getvalue())
        except Exception:
            logger.error("upload_dataframe: błąd podczas uploadu do s3://%s/%s", self.bucket, key, exc_info=True)
            raise

        logger.info(
            "upload_dataframe: zapisano %d wierszy do s3://%s/%s", len(df), self.bucket, key
        )
        return True

    # ------------------------------------------------------------------
    @staticmethod
    def build_partition_key(prefix: str, entity: str, partition_date: date) -> str:
        """
        Buduje klucz S3 w stylu Hive: <prefix>/<entity>/year=YYYY/month=MM/day=DD/data.parquet

        Parameters
        ----------
        prefix : str
            Prefiks katalogu głównego (np. "raw", "processed").
        entity : str
            Nazwa encji/tabeli (np. "orders").
        partition_date : date | datetime
            Data, wg której budowana jest partycja.

        Returns
        -------
        str
            Klucz S3, np. "raw/orders/year=2026/month=07/day=29/data.parquet".
        """
        return (
            f"{prefix.strip('/')}/{entity.strip('/')}/"
            f"year={partition_date.year:04d}/"
            f"month={partition_date.month:02d}/"
            f"day={partition_date.day:02d}/"
            f"data.parquet"
        )

    # ------------------------------------------------------------------
    def upload_monthly_snapshots(
        self,
        df: pd.DataFrame,
        entity: str,
        date_column: str = "ordered_at",
        prefix: str = "raw",
    ) -> list[str]:
        """
        Dzieli DataFrame po miesiącach (na podstawie `date_column`) i
        zapisuje każdy miesiąc jako osobny plik parquet, partycjonowany
        Hive-style (dzień = pierwszy dzień danego miesiąca).

        Parameters
        ----------
        df : pd.DataFrame
            Dane wejściowe zawierające kolumnę daty.
        entity : str
            Nazwa encji (np. "orders") użyta w kluczu partycji.
        date_column : str
            Nazwa kolumny z datą, wg której dzielimy na miesiące.
        prefix : str
            Prefiks katalogu głównego w S3.

        Returns
        -------
        list[str]
            Lista kluczy S3, pod którymi zapisano dane (tylko udane uploady).
        """
        if df is None or df.empty:
            logger.warning("upload_monthly_snapshots: pusty DataFrame - nic do zapisania")
            return []

        if date_column not in df.columns:
            logger.error("upload_monthly_snapshots: brak kolumny '%s' w DataFrame", date_column)
            raise ValueError(f"Brak kolumny '{date_column}' w DataFrame")

        df = df.copy()
        df[date_column] = pd.to_datetime(df[date_column])
        df["_year_month"] = df[date_column].dt.to_period("M")

        uploaded_keys: list[str] = []

        for period, group in df.groupby("_year_month"):
            group = group.drop(columns=["_year_month"])
            partition_date = date(period.year, period.month, 1)
            key = self.build_partition_key(prefix=prefix, entity=entity, partition_date=partition_date)

            success = self.upload_dataframe(group, key)
            if success:
                uploaded_keys.append(key)

        logger.info(
            "upload_monthly_snapshots: zapisano %d/%d miesięcznych snapshotów dla '%s'",
            len(uploaded_keys),
            df["_year_month"].nunique() if "_year_month" in df.columns else 0,
            entity,
        )
        return uploaded_keys
