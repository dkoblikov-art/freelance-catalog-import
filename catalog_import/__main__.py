"""Run with: python -m catalog_import products.csv."""

import argparse
import sys

import psycopg

from catalog_import.db import ConfigurationError, connection_parameters, save_products
from catalog_import.importer import CsvStructureError, ValidatedCsv, read_csv


def print_report(result: ValidatedCsv, saved: int) -> None:
    print(f"Всего строк: {result.total}")
    print(f"Сохранено: {saved}")
    print(f"Отклонено: {len(result.rejections)}")
    for rejection in result.rejections:
        print(f"Строка {rejection.line}: {'; '.join(rejection.reasons)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Импорт CSV в учебную БД cat001_learning.")
    parser.add_argument("csv_file", help="CSV: sku,name,price,stock; UTF-8; разделитель — запятая")
    args = parser.parse_args(argv)
    try:
        result = read_csv(args.csv_file)
    except CsvStructureError as error:
        print(f"Импорт отменён: {error} Запись в БД не начиналась.", file=sys.stderr)
        return 2
    except OSError:
        print("Не удалось прочитать CSV. Запись в БД не начиналась.", file=sys.stderr)
        return 2

    if not result.products:
        print_report(result, saved=0)
        return 1 if result.rejections else 0

    try:
        parameters = connection_parameters()
        with psycopg.connect(**parameters, autocommit=True) as connection:
            # Verify the actual target before any writes, not just its configuration.
            actual = connection.execute("SELECT current_database()").fetchone()[0]
            if actual != "cat001_learning":
                raise ConfigurationError("Сервер подключил к другой БД; импорт отменён.")
            saved = save_products(connection, result.products)
    except ConfigurationError as error:
        print_report(result, saved=0)
        print(f"Ошибка настройки: {error}", file=sys.stderr)
        return 2
    except psycopg.Error:
        print_report(result, saved=0)
        # Server/driver errors may contain credentials or submitted row values.
        print(
            "Ошибка PostgreSQL: сохранение не подтверждено. При ошибке внутри транзакции "
            "она откатывается. При потере связи во время COMMIT результат нужно проверить "
            "перед повтором импорта.",
            file=sys.stderr,
        )
        return 2
    print_report(result, saved)
    return 1 if result.rejections else 0


if __name__ == "__main__":
    raise SystemExit(main())
