from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class OrderExtractor:
    """
    Wyciąga dane zamówień/klientów z PostgreSQL do pandas DataFrame,
    korzystając z zapytań SQL.
    """

    def __init__(self, engine: Engine) -> None:
        """
        Parameters
        ----------
        engine : sqlalchemy.engine.Engine
            Aktywne połączenie/silnik SQLAlchemy do bazy PostgreSQL.
        """
        self.engine = engine
        logger.info("OrderExtractor zainicjalizowany (engine=%s)", engine.url.database)

    # ------------------------------------------------------------------
    # 1) Surowe zamówienia: JOIN customers + orders, ostatnie N dni
    # ------------------------------------------------------------------
    def extract_orders(self, days_back: int) -> pd.DataFrame:
        """
        Pobiera zamówienia z ostatnich `days_back` dni wraz z danymi klienta.

        Odpowiednik ręcznego JOIN-a customers + orders,
        rozszerzony o filtr czasowy. Parametr przekazywany jako bind
        param `:days` (make_interval), NIE przez f-string / string
        concatenation - chroni przed SQL injection.

        Parameters
        ----------
        days_back : int
            Liczba dni wstecz (licząc od dziś), z których pobierane są
            zamówienia.

        Returns
        -------
        pd.DataFrame
            Kolumny: order_id, customer_id, full_name, country,
            ordered_at, status, total_amount.
        """
        if days_back <= 0:
            raise ValueError("days_back musi być liczbą dodatnią")

        query = text(
            """
            SELECT
                o.order_id,
                o.customer_id,
                c.full_name,
                c.country,
                o.ordered_at,
                o.status,
                o.total_amount
            FROM orders o
            LEFT JOIN customers c ON c.customer_id = o.customer_id
            WHERE o.ordered_at >= CURRENT_DATE - make_interval(days => :days)
            ORDER BY o.ordered_at DESC
            """
        )

        logger.info("extract_orders: pobieranie zamówień z ostatnich %s dni", days_back)
        try:
            df = pd.read_sql(query, self.engine, params={"days": days_back})
        except Exception:
            logger.error("extract_orders: błąd podczas zapytania do bazy", exc_info=True)
            raise

        if df.empty:
            logger.warning("extract_orders: zapytanie zwróciło pusty DataFrame")
        else:
            logger.info("extract_orders: pobrano %d wierszy", len(df))

        return df

    # ------------------------------------------------------------------
    # 2) Przychód miesięczny + MoM growth
    # ------------------------------------------------------------------
    def extract_monthly_revenue(self) -> pd.DataFrame:
        """
        Miesięczny przychód (tylko zamówienia 'completed') wraz z
        procentowym wzrostem miesiąc-do-miesiąca (MoM).

        Bazuje na CTE `monthly_revenue` + window function `LAG()`.

        Returns
        -------
        pd.DataFrame
            Kolumny: month, revenue, orders, mom_growth_pct.
        """
        query = text(
            """
            WITH monthly_revenue AS (
                SELECT
                    DATE_TRUNC('month', ordered_at)::date AS month,
                    SUM(total_amount)                     AS revenue,
                    COUNT(order_id)                        AS orders
                FROM orders
                WHERE status = 'completed'
                GROUP BY 1
            ),
            growth AS (
                SELECT
                    month,
                    revenue,
                    orders,
                    LAG(revenue) OVER (ORDER BY month) AS prev_month_revenue
                FROM monthly_revenue
            )
            SELECT
                TO_CHAR(month, 'YYYY-MM') AS month,
                ROUND(revenue::numeric, 2) AS revenue,
                orders,
                ROUND(
                    (revenue - prev_month_revenue)
                    / NULLIF(prev_month_revenue, 0) * 100, 1
                ) AS mom_growth_pct
            FROM growth
            ORDER BY month
            """
        )

        logger.info("extract_monthly_revenue: pobieranie przychodu miesięcznego")
        try:
            df = pd.read_sql(query, self.engine)
        except Exception:
            logger.error("extract_monthly_revenue: błąd podczas zapytania do bazy", exc_info=True)
            raise

        if df.empty:
            logger.warning("extract_monthly_revenue: brak danych o przychodach (pusty wynik)")
        else:
            logger.info("extract_monthly_revenue: pobrano %d wierszy (miesięcy)", len(df))

        return df

    # ------------------------------------------------------------------
    # 3) Top klienci
    # ------------------------------------------------------------------
    def extract_top_customers(self, limit: int) -> pd.DataFrame:
        """
        Zwraca top N klientów wg łącznej wartości zamówień (CLV),
        z rankingiem obliczonym przez window function.

        Bazuje na CTE `vip_clients`,
        rozszerzonym o `RANK() OVER (ORDER BY SUM(total_amount) DESC)`.

        Parameters
        ----------
        limit : int
            Liczba najlepszych klientów do zwrócenia (TOP N wg rangi).

        Returns
        -------
        pd.DataFrame
            Kolumny: customer_id, full_name, country, liczba_zamowien,
            srednia_wartosc, laczna_kwota, customer_rank.
        """
        if limit <= 0:
            raise ValueError("limit musi być liczbą dodatnią")

        query = text(
            """
            WITH vip_clients AS (
                SELECT
                    c.customer_id,
                    c.full_name,
                    c.country,
                    COUNT(o.status)              AS liczba_zamowien,
                    ROUND(AVG(o.total_amount), 2) AS srednia_wartosc,
                    SUM(o.total_amount)           AS laczna_kwota,
                    RANK() OVER (
                        ORDER BY SUM(o.total_amount) DESC
                    ) AS customer_rank
                FROM customers c
                LEFT JOIN orders o ON c.customer_id = o.customer_id
                WHERE o.status = 'completed'
                GROUP BY c.customer_id
                HAVING COUNT(o.status) > 2
                   AND ROUND(AVG(o.total_amount), 2) > 500
            )
            SELECT *
            FROM vip_clients
            WHERE customer_rank <= :limit
            ORDER BY customer_rank ASC
            """
        )

        logger.info("extract_top_customers: pobieranie top %d klientów (CLV)", limit)
        try:
            df = pd.read_sql(query, self.engine, params={"limit": limit})
        except Exception:
            logger.error("extract_top_customers: błąd podczas zapytania do bazy", exc_info=True)
            raise

        if df.empty:
            logger.warning("extract_top_customers: brak klientów spełniających kryteria VIP")
        else:
            logger.info("extract_top_customers: pobrano %d wierszy", len(df))

        return df
