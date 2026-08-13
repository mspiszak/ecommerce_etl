# ecommerce_etl

Automatyczny pipeline ETL, który każdego dnia eksportuje dane zamówień z PostgreSQL do S3 w formacie parquet, partycjonowane wg daty (rok/miesiąc/dzień). Pipeline jest modułowy (extract → transform → load), obserwowalny dzięki logowaniu do pliku i stdout, oraz w pełni testowalny (pytest, boto3/SQLAlchemy zmockowane w testach). Zapytania SQL wykorzystywane przez `OrderExtractor`.

## Architektura

```
[PostgreSQL (M1 schema)]
        │  SQLAlchemy — OrderExtractor
        ▼
[pandas DataFrame — surowe zamówienia]
        │  DataTransformer — walidacja, enrichment
        ▼
[Zwalidowany DataFrame]
        │  S3Loader — parquet + partitioning
        ▼
[S3 Data Lake: raw/orders/year=YYYY/month=MM/day=DD/]
```

## Struktura projektu

```
ecommerce_etl/
├── src/ecommerce_etl/
│   ├── __init__.py
│   ├── extractor.py    — OrderExtractor (SQL z M1)
│   ├── transformer.py  — DataTransformer
│   ├── loader.py        — S3Loader (boto3)
│   └── __main__.py      — CLI (argparse)
├── tests/
│   ├── conftest.py
│   ├── test_extractor.py
│   ├── test_transformer.py
│   └── test_loader.py
├── .env.example
├── requirements.txt
├── pyproject.toml
└── README.md
```

## Instalacja

```bash
cd ecommerce_etl

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install -e .                # instaluje pakiet ecommerce_etl w trybie edytowalnym

cp .env.example .env            # uzupełnij dane dostępowe do bazy i S3
```

Wymagane zmienne środowiskowe (`.env`) opisane są w `.env.example`:
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET`.

## Uruchomienie

```bash
# Pełne uruchomienie: eksport zamówień z 30 dni na środowisku prod
python -m ecommerce_etl --days 30 --env prod

# Bez zapisu do S3 (tylko walidacja + logi), z logowaniem DEBUG
python -m ecommerce_etl --days 7 --dry-run --log-level DEBUG

# Pomoc
python -m ecommerce_etl --help
```

Przykład outputu w terminalu (`--dry-run`, brak skonfigurowanego `.env`):
```bash
python -m ecommerce_etl --days 7 --dry-run
```
```
2026-07-29 01:42:30,533 | __main__ | INFO | Start pipeline'u ETL (days=7, env=dev, dry_run=True)
2026-07-29 01:42:30,534 | __main__ | ERROR | Brak wymaganej zmiennej środowiskowej: 'DB_USER'
```

Ten sam log trafia równolegle do pliku `etl.log` (format: `%(asctime)s | %(name)s | %(levelname)s | %(message)s`).

## Testy

```bash
pytest tests/ -v
```


