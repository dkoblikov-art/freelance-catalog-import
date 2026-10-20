from decimal import Decimal

import pytest

from catalog_import.importer import CsvStructureError, read_csv, validate_row


def row(**changes):
    return {"sku": "A", "name": "Товар", "price": "10.25", "stock": "0", **changes}


@pytest.mark.parametrize("field", ["sku", "name", "price", "stock"])
@pytest.mark.parametrize("value", ["", " \t "])
def test_required_fields(field, value):
    product, errors = validate_row(row(**{field: value}))
    assert product is None
    assert any(error.startswith(f"{field}:") for error in errors)


@pytest.mark.parametrize("price", [
    "0", "-0.01", "-1", "NaN", "sNaN", "Infinity", "-Infinity",
    "9999999999.999", "10000000000", "1.001", "1.230", "0.001",
    "text", "1,23", "1e2", "1_000", "١.٢", "1.2.3",
])
def test_invalid_price(price):
    product, errors = validate_row(row(price=price))
    assert product is None
    assert any(error.startswith("price:") for error in errors)


@pytest.mark.parametrize("price", ["0.01", "1", "1.2", "1.20", "+1.20", "9999999999.99"])
def test_valid_price_is_decimal(price):
    product, errors = validate_row(row(price=price))
    assert errors == ()
    assert isinstance(product.price, Decimal)
    assert product.price == Decimal(price)


@pytest.mark.parametrize("stock", [
    "-1", "1.0", "1.5", "NaN", "1e2", "+1", "1_000", "١", "2147483648", "9" * 5000,
])
def test_invalid_stock(stock):
    product, errors = validate_row(row(stock=stock))
    assert product is None
    assert any(error.startswith("stock:") for error in errors)


@pytest.mark.parametrize("stock, expected", [("0", 0), ("0001", 1), ("2147483647", 2147483647), ("0" * 5000, 0)])
def test_valid_stock(stock, expected):
    product, errors = validate_row(row(stock=stock))
    assert errors == ()
    assert product.stock == expected


@pytest.mark.parametrize("field", ["sku", "name", "price", "stock"])
def test_null_character_is_rejected(field):
    product, errors = validate_row(row(**{field: "a\x00b"}))
    assert product is None
    assert any("нулевой" in error for error in errors)


def test_trims_fields_and_keeps_case():
    product, errors = validate_row(row(sku=" AbC\t", name=" Товар ", price=" 1.20 ", stock=" 1 "))
    assert errors == ()
    assert (product.sku, product.name, product.price, product.stock) == ("AbC", "Товар", Decimal("1.20"), 1)


def test_multiple_errors_are_preserved():
    product, errors = validate_row(row(sku="", name="", price="0", stock="-1"))
    assert product is None
    assert len(errors) == 4


def write_csv(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "products.csv"
    path.write_text(text, encoding=encoding, newline="")
    return path


def test_first_valid_row_wins_and_invalid_does_not_reserve_sku(tmp_path):
    path = write_csv(tmp_path,
        "sku,name,price,stock\n"
        "A,Invalid,0,1\n"
        " A ,First,10,1\n"
        "A,Duplicate,20,2\n"
        "a,Lowercase,30,3\n"
        "A,Invalid again,NaN,1\n")
    result = read_csv(path)
    assert result.total == 5
    assert [(p.sku, p.name) for p in result.products] == [("A", "First"), ("a", "Lowercase")]
    assert [r.line for r in result.rejections] == [2, 4, 6]
    assert "дубликат корректной строки 3" in result.rejections[1].reasons[0]
    assert all("дубликат" not in reason for reason in result.rejections[2].reasons)


def test_bom_reordered_header_quotes_and_multiline_line_numbers(tmp_path):
    path = write_csv(tmp_path,
        'name,stock,sku,price\r\n"Товар,\r\nописание",0,A,1.20\r\nBad,-1,B,2\r\n',
        encoding="utf-8-sig")
    result = read_csv(path)
    assert result.total == 2
    assert result.products[0].name == "Товар,\r\nописание"
    assert result.rejections[0].line == 4


@pytest.mark.parametrize("text", [
    "", "sku,name,price\n", "sku,name,price,sku\n", "sku,name,price,stock,extra\n",
    "sku;name;price;stock\n", "sku,name,price,stock\nA,Item,1\n",
    "sku,name,price,stock\nA,Item,1,0,extra\n", 'sku,name,price,stock\nA,"unclosed,1,0\n',
    'sku,name,price,stock\nA,"bad"tail,1,0\n', "sku,name,price,stock\n\n",
])
def test_structure_errors_reject_whole_file(tmp_path, text):
    with pytest.raises(CsvStructureError):
        read_csv(write_csv(tmp_path, text))


def test_late_structure_error_discards_previously_valid_rows(tmp_path):
    path = write_csv(tmp_path, "sku,name,price,stock\nA,Item,1,0\nB,Item,2\n")
    with pytest.raises(CsvStructureError, match="Строка 3"):
        read_csv(path)


def test_invalid_utf8(tmp_path):
    path = tmp_path / "products.csv"
    path.write_bytes(b"sku,name,price,stock\nA,\xff,1,0\n")
    with pytest.raises(CsvStructureError, match="UTF-8"):
        read_csv(path)


def test_header_only_is_empty_import(tmp_path):
    result = read_csv(write_csv(tmp_path, "sku,name,price,stock\n"))
    assert (result.total, result.products, result.rejections) == (0, (), ())
