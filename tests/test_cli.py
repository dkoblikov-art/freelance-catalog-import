from unittest.mock import MagicMock

import psycopg
import pytest

import catalog_import.__main__ as cli


@pytest.fixture
def connection_env(monkeypatch):
    for key, value in {"PGHOST": "127.0.0.1", "PGPORT": "5432", "PGDATABASE": "cat001_learning",
                       "PGUSER": "placeholder", "PGPASSWORD": "placeholder"}.items():
        monkeypatch.setenv(key, value)


def csv_path(tmp_path, rows):
    path = tmp_path / "input.csv"
    path.write_text("sku,name,price,stock\n" + rows, encoding="utf-8")
    return str(path)


def test_full_validation_happens_before_connect(tmp_path, monkeypatch, capsys):
    connect = MagicMock()
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\nB,Item,2\n")]) == 2
    connect.assert_not_called()
    assert "Строка 3" in capsys.readouterr().err


@pytest.mark.parametrize("rows, code", [("", 0), ("A,Item,0,-1\n", 1)])
def test_no_connection_when_nothing_to_save(tmp_path, monkeypatch, rows, code, capsys):
    connect = MagicMock()
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    assert cli.main([csv_path(tmp_path, rows)]) == code
    connect.assert_not_called()
    assert "Сохранено: 0" in capsys.readouterr().out


def test_missing_file(tmp_path, capsys):
    assert cli.main([str(tmp_path / "missing.csv")]) == 2
    assert "Не удалось прочитать CSV" in capsys.readouterr().err


def test_statistics_count_rows_not_reasons(tmp_path, monkeypatch, capsys, connection_env):
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = ("cat001_learning",)
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    save = MagicMock(return_value=1)
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "save_products", save)
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\nB,,0,-1\nA,Duplicate,2,0\n")]) == 1
    output = capsys.readouterr().out
    assert "Всего строк: 3\nСохранено: 1\nОтклонено: 2" in output
    assert "Строка 3" in output and "Строка 4" in output
    assert len(save.call_args.args[1]) == 1


def test_database_errors_do_not_leak_secrets(tmp_path, monkeypatch, capsys, connection_env):
    monkeypatch.setattr(cli.psycopg, "connect", MagicMock(side_effect=psycopg.OperationalError("private-detail")))
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\n")]) == 2
    output = capsys.readouterr()
    assert "private-detail" not in output.out + output.err
    assert "Сохранено: 0" in output.out


def test_all_valid_rows_report_success(tmp_path, monkeypatch, capsys, connection_env):
    connect = MagicMock()
    connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = ("cat001_learning",)
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "save_products", MagicMock(return_value=2))
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\na,Other,2,1\n")]) == 0
    assert "Всего строк: 2\nСохранено: 2\nОтклонено: 0" in capsys.readouterr().out


def test_failed_write_never_reports_success(tmp_path, monkeypatch, capsys, connection_env):
    connect = MagicMock()
    connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = ("cat001_learning",)
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "save_products", MagicMock(side_effect=psycopg.DatabaseError("private-row-data")))
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\n")]) == 2
    output = capsys.readouterr()
    assert "Всего строк: 1\nСохранено: 0\nОтклонено: 0" in output.out
    assert "Ошибка PostgreSQL" in output.err
    assert "private-row-data" not in output.out + output.err


def test_actual_database_is_checked_before_save(tmp_path, monkeypatch, capsys, connection_env):
    connect = MagicMock()
    connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = ("other_database",)
    save = MagicMock()
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    monkeypatch.setattr(cli, "save_products", save)
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\n")]) == 2
    save.assert_not_called()
    assert "Сервер подключил к другой БД" in capsys.readouterr().err


def test_missing_settings_do_not_connect(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PGDATABASE", raising=False)
    connect = MagicMock()
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    assert cli.main([csv_path(tmp_path, "A,Item,1,0\n")]) == 2
    connect.assert_not_called()
    assert "Ошибка настройки" in capsys.readouterr().err
