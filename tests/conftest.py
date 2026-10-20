"""PostgreSQL access is opt-in and never uses the application's PG* settings."""

import os
from pathlib import Path

import psycopg
import pytest


def postgres_parameters(env):
    if env.get("CAT001_RUN_PG_TESTS") != "1":
        pytest.skip("PostgreSQL tests disabled: CAT001_RUN_PG_TESTS is not 1")
    if env.get("CAT001_TEST_DBNAME") != "cat001_test":
        pytest.fail("Integration tests require CAT001_TEST_DBNAME=cat001_test", pytrace=False)
    required = ("CAT001_TEST_HOST", "CAT001_TEST_PORT", "CAT001_TEST_USER", "CAT001_TEST_PASSWORD")
    if any(not env.get(key, "").strip() for key in required):
        pytest.fail("Set all CAT001_TEST_* connection variables explicitly", pytrace=False)
    port = env["CAT001_TEST_PORT"]
    if not port.isascii() or not port.isdigit() or len(port) > 5 or not 1 <= int(port) <= 65535:
        pytest.fail("Invalid CAT001_TEST_PORT", pytrace=False)
    return {
        "host": env["CAT001_TEST_HOST"], "port": int(port),
        "dbname": "cat001_test", "user": env["CAT001_TEST_USER"],
        "password": env["CAT001_TEST_PASSWORD"], "connect_timeout": 5,
        "options": "-c search_path=pg_temp,pg_catalog",
    }


@pytest.fixture
def pg_connection():
    parameters = postgres_parameters(os.environ)
    try:
        connection = psycopg.connect(**parameters, autocommit=True)
    except psycopg.Error:
        pytest.fail("Cannot connect to cat001_test (connection details hidden)", pytrace=False)
    with connection:
        # No table creation until the server has confirmed the actual database.
        try:
            actual = connection.execute("SELECT current_database()").fetchone()[0]
        except psycopg.Error:
            pytest.fail("Cannot verify test database (details hidden)", pytrace=False)
        if actual != "cat001_test":
            pytest.fail("Server connected to a database other than cat001_test", pytrace=False)
        schema = (Path(__file__).resolve().parents[1] / "sql" / "001_products.sql").read_text("utf-8")
        connection.execute(schema.replace("CREATE TABLE products", "CREATE TEMP TABLE products", 1))
        # Temporary table shadows public.products and vanishes when the connection closes.
        yield connection
