from decimal import Decimal
from unittest.mock import MagicMock

import psycopg
import pytest

from catalog_import.db import ConfigurationError, connection_parameters, save_products
from catalog_import.importer import Product
from conftest import postgres_parameters


def test_application_requires_explicit_learning_database():
    with pytest.raises(ConfigurationError):
        connection_parameters({})
    env = {"PGHOST": "127.0.0.1", "PGPORT": "5432", "PGDATABASE": "other_database",
           "PGUSER": "placeholder", "PGPASSWORD": "placeholder"}
    with pytest.raises(ConfigurationError, match="cat001_learning"):
        connection_parameters(env)


@pytest.mark.parametrize("port", ["0", "65536", "no", "1" * 5000, "٥٤٣٢"])
def test_invalid_connection_port(port):
    env = {"PGHOST": "127.0.0.1", "PGPORT": port, "PGDATABASE": "cat001_learning",
           "PGUSER": "placeholder", "PGPASSWORD": "placeholder"}
    with pytest.raises(ConfigurationError, match="PGPORT"):
        connection_parameters(env)


def test_tests_are_disabled_by_default_even_when_application_is_configured():
    with pytest.raises(pytest.skip.Exception):
        postgres_parameters({"PGDATABASE": "cat001_learning"})


@pytest.mark.parametrize("name", [None, "cat001_learning", "postgres", "cat001_test "])
def test_integration_guard_rejects_any_other_database(name):
    env = {"CAT001_RUN_PG_TESTS": "1"}
    if name is not None:
        env["CAT001_TEST_DBNAME"] = name
    with pytest.raises(pytest.fail.Exception):
        postgres_parameters(env)


def test_integration_guard_does_not_fall_back_to_application_settings():
    with pytest.raises(pytest.fail.Exception):
        postgres_parameters({"CAT001_RUN_PG_TESTS": "1", "CAT001_TEST_DBNAME": "cat001_test",
                             "PGHOST": "127.0.0.1", "PGUSER": "placeholder", "PGPASSWORD": "placeholder"})


def test_rejects_connection_inside_an_existing_transaction():
    connection = MagicMock(autocommit=True)
    connection.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
    with pytest.raises(ValueError, match="idle"):
        save_products(connection, [])
    connection.transaction.assert_not_called()


def test_requires_transaction_ownership():
    connection = MagicMock(autocommit=False)
    with pytest.raises(ValueError, match="autocommit"):
        save_products(connection, [])


@pytest.mark.integration
def test_insert_and_repeat_import_update(pg_connection):
    initial = Product("A", "Initial", Decimal("1.20"), 0)
    assert save_products(pg_connection, [initial]) == 1
    assert pg_connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    updated = Product("A", "Updated", Decimal("2.35"), 7)
    assert save_products(pg_connection, [updated]) == 1
    assert pg_connection.execute("SELECT sku, name, price, stock FROM products").fetchall() == [
        ("A", "Updated", Decimal("2.35"), 7)
    ]


@pytest.mark.integration
def test_case_sensitive_sku_and_parameterized_text(pg_connection):
    unusual = "x'); DROP TABLE products; --"
    assert save_products(pg_connection, [
        Product("A", "Upper", Decimal("1"), 0),
        Product("a", "Lower", Decimal("2"), 1),
        Product(unusual, "O'Reilly", Decimal("3"), 2),
    ]) == 3
    assert pg_connection.execute("SELECT name FROM products WHERE sku = %s", (unusual,)).fetchone() == ("O'Reilly",)
    assert pg_connection.execute("SELECT count(*) FROM products").fetchone()[0] == 3


@pytest.mark.integration
def test_failure_rolls_back_inserts_and_updates(pg_connection):
    save_products(pg_connection, [Product("A", "Original", Decimal("1"), 0)])
    with pytest.raises(psycopg.errors.CheckViolation):
        save_products(pg_connection, [
            Product("A", "Changed", Decimal("2"), 1),
            Product("B", "New", Decimal("3"), 0),
            Product("C", "Invalid", Decimal("4"), -1),
        ])
    assert pg_connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    assert pg_connection.execute("SELECT sku, name FROM products").fetchall() == [("A", "Original")]


@pytest.mark.integration
@pytest.mark.parametrize("bad_price", [Decimal("0"), Decimal("NaN"), Decimal("10000000000")])
def test_database_price_constraints(pg_connection, bad_price):
    with pytest.raises(psycopg.Error):
        save_products(pg_connection, [Product("A", "Invalid", bad_price, 0)])
    assert pg_connection.execute("SELECT count(*) FROM products").fetchone()[0] == 0


@pytest.mark.integration
def test_database_integer_range(pg_connection):
    with pytest.raises(psycopg.Error):
        save_products(pg_connection, [Product("A", "Invalid", Decimal("1"), 2147483648)])
    assert pg_connection.execute("SELECT count(*) FROM products").fetchone()[0] == 0
