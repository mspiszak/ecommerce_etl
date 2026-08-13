
from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine

from .extractor import OrderExtractor
from .transformer import DataTransformer
from .loader import S3Loader

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"


def setup_logging(log_level: str) -> None:
    """Konfiguruje logowanie do stdout oraz do pliku etl.log."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    file_handler = logging.FileHandler("etl.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parsuje argumenty CLI."""
    parser = argparse.ArgumentParser(
        prog="ecommerce_etl",
        description="ETL pipeline: PostgreSQL -> pandas -> S3 (parquet, partycjonowane wg daty).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Liczba dni wstecz, z których pobierane są zamówienia (domyślnie: 30).",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "staging", "prod"],
        default="dev",
        help="Środowisko uruchomieniowe (wpływa na .env / konfigurację bucketu S3).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Uruchamia pipeline bez faktycznego zapisu do S3 (tylko logi).",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Poziom logowania (domyślnie: INFO).",
    )
    return parser.parse_args(argv)


def build_engine():
    """Tworzy silnik SQLAlchemy na podstawie zmiennych środowiskowych."""
    load_dotenv()
    db_url = (
        f"postgresql+psycopg2://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
        f"@{os.environ['DB_HOST']}:{os.environ.get('DB_PORT', '5432')}/{os.environ['DB_NAME']}"
    )
    return create_engine(db_url)


def run(args: argparse.Namespace) -> int:
    """Główna logika pipeline'u. Zwraca exit code."""
    logger.info(
        "Start pipeline'u ETL (days=%d, env=%s, dry_run=%s)", args.days, args.env, args.dry_run
    )

    try:
        engine = build_engine()
    except KeyError as exc:
        logger.error("Brak wymaganej zmiennej środowiskowej: %s", exc)
        return 1

    extractor = OrderExtractor(engine)

    try:
        df_orders = extractor.extract_orders(days_back=args.days)
    except Exception:
        logger.error("Ekstrakcja zamówień nie powiodła się", exc_info=True)
        return 1

    if df_orders.empty:
        logger.warning("Brak zamówień do przetworzenia - kończę pipeline")
        return 0

    transformer = DataTransformer(df_orders)
    df_clean = (
        transformer.validate_and_tag()
        .clean_amounts()
        .add_order_size_label()
        .enrich()
        .filter_valid_completed()
    )
    summary = transformer.get_summary()
    logger.info("Podsumowanie transformacji: %s", summary)

    if df_clean.empty:
        logger.warning("Brak poprawnych, zakończonych zamówień po transformacji")
        return 0

    if args.dry_run:
        logger.info(
            "DRY-RUN: pominięto zapis do S3 (%d wierszy gotowych do wysyłki)", len(df_clean)
        )
        return 0

    bucket = os.environ.get("S3_BUCKET", f"ecommerce-etl-{args.env}")
    region = os.environ.get("AWS_REGION", "eu-central-1")
    loader = S3Loader(bucket=bucket, region=region)

    try:
        uploaded_keys = loader.upload_monthly_snapshots(df_clean, entity="orders")
    except Exception:
        logger.error("Upload do S3 nie powiódł się", exc_info=True)
        return 1

    logger.info("Pipeline zakończony sukcesem. Zapisano %d plików do S3.", len(uploaded_keys))
    return 0


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)
    exit_code = run(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
