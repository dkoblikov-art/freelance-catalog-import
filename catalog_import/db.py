"""Explicit connection configuration and atomic, parameterized upserts."""

import os
from collections.abc import Mapping, Sequence

import psycopg

from catalog_import.importer import Product

UPSERT = """
    INSERT INTO products (sku, name, price, stock)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (sku) DO UPDATE
    SET name = EXCLUDED.name, price = EXCLUDED.price, stock = EXCLUDED.stock
"""


class ConfigurationError(ValueError):
    """Report configuration problems without exposing environment values."""


def connection_parameters(environ: Mapping[str, str] | None = None) -> dict:
    env = os.environ if environ is None else environ
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    if any(not env.get(key, "").strip() for key in required):
        raise ConfigurationError("Задайте PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.")
    if env["PGDATABASE"] != "cat001_learning":
        raise ConfigurationError("Для импорта разрешена только учебная БД cat001_learning.")
    if not env["PGPORT"].isascii() or not env["PGPORT"].isdigit():
        raise ConfigurationError("PGPORT должен быть целым числом от 1 до 65535.")
    if len(env["PGPORT"]) > 5 or not 1 <= int(env["PGPORT"]) <= 65535:
        raise ConfigurationError("PGPORT должен быть целым числом от 1 до 65535.")
    # Explicit values prevent accidental use of a default database or search_path.
    return {
        "host": env["PGHOST"], "port": int(env["PGPORT"]),
        "dbname": env["PGDATABASE"], "user": env["PGUSER"],
        "password": env["PGPASSWORD"], "connect_timeout": 5,
        "options": "-c search_path=public,pg_catalog",
    }


def save_products(connection: psycopg.Connection, products: Sequence[Product]) -> int:
    """Require an idle autocommit connection so this block owns the transaction."""
    if not connection.autocommit:
        raise ValueError("save_products requires an autocommit connection")
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("save_products requires an idle connection")
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.executemany(UPSERT, [
                (p.sku, p.name, p.price, p.stock) for p in products
            ])
    return len(products)
