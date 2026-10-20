"""Read the complete CSV and validate it without accessing a database."""

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = ("sku", "name", "price", "stock")
MAX_PRICE = Decimal("9999999999.99")
MAX_STOCK = 2_147_483_647
PRICE_PATTERN = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")
STOCK_PATTERN = re.compile(r"[0-9]+\Z")


class CsvStructureError(ValueError):
    """The entire file must be rejected before any database access."""


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: Decimal
    stock: int


@dataclass(frozen=True)
class Rejection:
    line: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedCsv:
    total: int
    products: tuple[Product, ...]
    rejections: tuple[Rejection, ...]


def validate_row(row: dict[str, str]) -> tuple[Product | None, tuple[str, ...]]:
    values = {field: row.get(field, "").strip() for field in FIELDS}
    errors = []
    for field, value in values.items():
        if not value:
            errors.append(f"{field}: обязательное поле")
        elif "\x00" in value:
            errors.append(f"{field}: недопустимый нулевой символ")

    price = None
    raw_price = values["price"]
    if raw_price:
        try:
            price = Decimal(raw_price)
        except InvalidOperation:
            errors.append("price: ожидается десятичное число с точкой")
        else:
            if not price.is_finite():
                errors.append("price: цена должна быть конечной")
            elif not PRICE_PATTERN.fullmatch(raw_price):
                errors.append("price: ожидается обычная десятичная запись с точкой")
            else:
                if not 0 < price <= MAX_PRICE:
                    errors.append("price: допустим диапазон от 0.01 до 9999999999.99")
                if price.as_tuple().exponent < -2:
                    errors.append("price: максимум 2 знака после точки")

    stock = None
    raw_stock = values["stock"]
    if raw_stock:
        if not STOCK_PATTERN.fullmatch(raw_stock):
            errors.append("stock: ожидается неотрицательное целое число из цифр 0–9")
        else:
            # Check the length before int(): excessively long input must be a row error.
            significant = raw_stock.lstrip("0") or "0"
            if len(significant) > 10 or int(significant) > MAX_STOCK:
                errors.append("stock: максимум 2147483647")
            else:
                stock = int(significant)

    if errors:
        return None, tuple(errors)
    assert price is not None and stock is not None
    return Product(values["sku"], values["name"], price, stock), ()


def read_csv(path: str | Path) -> ValidatedCsv:
    products = []
    rejections = []
    seen: dict[str, int] = {}
    total = 0
    reader = None
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if header is None or len(header) != len(FIELDS) or set(header) != set(FIELDS):
                raise CsvStructureError(
                    "Заголовок должен содержать ровно sku,name,price,stock без повторений."
                )
            while True:
                line = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    break
                if len(row) != len(header):
                    raise CsvStructureError(f"Строка {line}: ожидается ровно 4 поля.")
                total += 1
                product, errors = validate_row(dict(zip(header, row, strict=True)))
                if errors:
                    rejections.append(Rejection(line, errors))
                elif product.sku in seen:
                    rejections.append(Rejection(line, (
                        f"sku: дубликат корректной строки {seen[product.sku]}",
                    )))
                else:
                    seen[product.sku] = line
                    products.append(product)
    except UnicodeError:
        raise CsvStructureError("Файл должен иметь кодировку UTF-8 (BOM допустим).") from None
    except csv.Error:
        line = reader.line_num if reader is not None else 1
        raise CsvStructureError(f"Нарушена структура CSV около строки {line}.") from None
    return ValidatedCsv(total, tuple(products), tuple(rejections))
