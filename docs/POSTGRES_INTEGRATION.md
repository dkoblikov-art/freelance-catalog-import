# CAT-001: выполнение интеграции из терминала PyCharm

По подтверждению пользователя, 7 интеграционных тестов, реальный импорт и UPSERT
успешно выполнены. Команды ниже предназначены для первоначальной подготовки
окружения; на уже настроенной БД не повторяйте создание таблицы из раздела 2.
Для воспроизведения на новом компьютере начните с [README](../README.md).
Запускайте блоки по порядку в одной сессии PowerShell из корня проекта.
При любой ошибке остановитесь. Используется только `cat001-db-1`; Docker volumes
и другие контейнеры команды не изменяют. Существующий `.env` не перезаписывайте.

## 1. Проверка контейнера и модульных тестов

```powershell
$ErrorActionPreference = 'Stop'
$inspection = docker container inspect cat001-db-1
if ($LASTEXITCODE -ne 0) { throw 'Docker inspection failed; stop.' }
$container = @($inspection | ConvertFrom-Json)[0]
$inspection = $null
if ($container.Name -ne '/cat001-db-1' -or
    $container.State.Status -ne 'running' -or
    $container.Config.Image -ne 'postgres:17-alpine' -or
    $container.Config.Labels.'com.docker.compose.project' -ne 'cat001' -or
    $container.Config.Labels.'com.docker.compose.service' -ne 'db') {
    throw 'Unexpected container identity; stop.'
}
$ports = @($container.NetworkSettings.Ports.'5432/tcp')
if ($ports.Count -ne 1 -or $ports[0].HostIp -ne '127.0.0.1' -or $ports[0].HostPort -ne '55433') {
    throw 'Unexpected PostgreSQL port binding; stop.'
}
$container = $null

function Invoke-Cat001Sql {
    param([string]$Database, [string]$Sql)
    if ($Database -notin @('cat001_learning', 'cat001_test')) {
        throw 'Database outside CAT-001 allowlist; stop.'
    }
    $Sql | docker exec -i cat001-db-1 psql -X -U cat001_local -d $Database -v ON_ERROR_STOP=1
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL command failed; stop.' }
}

Invoke-Cat001Sql cat001_learning @'
DO $$
BEGIN
    IF current_database() <> 'cat001_learning'
       OR current_user <> 'cat001_local'
       OR current_setting('server_version_num')::int NOT BETWEEN 170000 AND 179999 THEN
        RAISE EXCEPTION 'Unexpected database, role or server version';
    END IF;
END $$;
SELECT current_database(), current_user, current_setting('server_version');
SELECT n.nspname AS schema_name, c.relname, c.relkind
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relname = 'products' AND n.nspname NOT LIKE 'pg_%';
SELECT datname, pg_get_userbyid(datdba) AS owner
FROM pg_database WHERE datname = 'cat001_test';
'@

.\.venv\Scripts\python.exe -m pytest -m 'not integration' -q -p no:cacheprovider --basetemp=.\.pytest_tmp_cat001_unit
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed; stop.' }
```

Вывод `products` должен быть пустым. Существующую таблицу не удаляйте и не
заменяйте: следующий блок завершится ошибкой при конфликте. Если `cat001_test`
уже существует, проверьте её назначение и владельца; при сомнении остановитесь.

## 2. Создание таблицы и отсутствующей тестовой БД

`sql/000_create_databases.sql` не запускайте: он безусловно создаёт обе БД.
Вместо него используются следующие проверки и команды.

```powershell
$guard = @'
BEGIN;
SET LOCAL search_path = public, pg_catalog;
SET LOCAL lock_timeout = '5s';
DO $$
BEGIN
    IF current_database() <> 'cat001_learning' OR current_user <> 'cat001_local' THEN
        RAISE EXCEPTION 'Unexpected database or role';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'products' AND n.nspname NOT LIKE 'pg_%'
    ) THEN
        RAISE EXCEPTION 'Conflicting products object exists; no changes applied';
    END IF;
END $$;
'@
$schema = Get-Content -LiteralPath sql/001_products.sql -Raw -Encoding UTF8
Invoke-Cat001Sql cat001_learning ($guard + "`n" + $schema + "`nCOMMIT;")

Invoke-Cat001Sql cat001_learning @'
DO $$
BEGIN
    IF current_database() <> 'cat001_learning' OR current_user <> 'cat001_local' THEN
        RAISE EXCEPTION 'Unexpected database or role';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_database
        WHERE datname = 'cat001_test'
          AND (pg_get_userbyid(datdba) <> 'cat001_local' OR NOT datallowconn OR datistemplate)
    ) THEN
        RAISE EXCEPTION 'Existing test database has unexpected owner or flags';
    END IF;
END $$;
SELECT 'CREATE DATABASE cat001_test OWNER cat001_local TEMPLATE template0'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'cat001_test')
\gexec
'@

Invoke-Cat001Sql cat001_test @'
DO $$
BEGIN
    IF current_database() <> 'cat001_test' OR current_user <> 'cat001_local'
       OR current_setting('server_version_num')::int NOT BETWEEN 170000 AND 179999 THEN
        RAISE EXCEPTION 'Unexpected test database, role or server version';
    END IF;
END $$;
SELECT current_database(), current_user;
'@
```

Таблица создаётся одной транзакцией. Существующая `cat001_test` не пересоздаётся;
команды не меняют её владельца, права или постоянные объекты.

## 3. Семь интеграционных тестов и проверка CSV

Пароль вводится скрыто и хранится только в окружении текущего процесса на время
проверки. Введите пароль роли `cat001_local` из локального `.env`.
Не включайте `--showlocals`, трассировку команд или вывод окружения.

```powershell
$testKeys = @('CAT001_RUN_PG_TESTS', 'CAT001_TEST_HOST', 'CAT001_TEST_PORT',
    'CAT001_TEST_DBNAME', 'CAT001_TEST_USER', 'CAT001_TEST_PASSWORD')
$previous = @{}
foreach ($key in $testKeys) {
    $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    $env:CAT001_RUN_PG_TESTS = '1'
    $env:CAT001_TEST_HOST = '127.0.0.1'
    $env:CAT001_TEST_PORT = '55433'
    $env:CAT001_TEST_DBNAME = 'cat001_test'
    $env:CAT001_TEST_USER = 'cat001_local'
    $password = Read-Host 'Password for cat001_local' -AsSecureString
    $env:CAT001_TEST_PASSWORD = [System.Net.NetworkCredential]::new('', $password).Password
    $password.Dispose()
    $password = $null

    .\.venv\Scripts\python.exe -m pytest -m integration -q --tb=no -o addopts=--strict-markers --basetemp=.\.pytest_tmp_cat001_local
    if ($LASTEXITCODE -ne 0) { throw 'Integration tests failed; stop.' }

    @'
import os
from pathlib import Path
import psycopg
from catalog_import.db import save_products
from catalog_import.importer import read_csv

def check_csv():
    result = read_csv('tests/fixtures/products.csv')
    if not result.products:
        raise RuntimeError('CSV has no valid products')
    with psycopg.connect(
        host=os.environ['CAT001_TEST_HOST'], port=int(os.environ['CAT001_TEST_PORT']),
        dbname='cat001_test', user=os.environ['CAT001_TEST_USER'],
        password=os.environ['CAT001_TEST_PASSWORD'], connect_timeout=5,
        options='-c search_path=pg_temp,pg_catalog', autocommit=True,
    ) as connection:
        if connection.execute('SELECT current_database(), current_user').fetchone() != ('cat001_test', 'cat001_local'):
            raise RuntimeError('Unexpected database or role')
        schema = Path('sql/001_products.sql').read_text(encoding='utf-8')
        if schema.count('CREATE TABLE products') != 1:
            raise RuntimeError('Unexpected schema definition')
        connection.execute(schema.replace('CREATE TABLE products', 'CREATE TEMP TABLE products', 1))
        expected = sorted((p.sku, p.name, p.price, p.stock) for p in result.products)
        for _ in range(2):
            if save_products(connection, result.products) != len(expected):
                raise RuntimeError('Unexpected saved count')
            actual = connection.execute('SELECT sku, name, price, stock FROM products').fetchall()
            if sorted(actual) != expected:
                raise RuntimeError('Unexpected imported rows')
    print('CSV import and repeat import: PASS (cat001_test, temporary table)')

try:
    check_csv()
except Exception:
    raise SystemExit('CSV check failed; details hidden to protect connection data.') from None
'@ | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -ne 0) { throw 'CSV check failed; stop.' }
}
finally {
    foreach ($key in $testKeys) {
        [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
    }
    if ($null -ne $password) { $password.Dispose() }
}
```

Ожидается `7 passed` для интеграционных тестов. Они проверяют обновление,
rollback вставок и обновлений, параметризацию и ограничения значений. Все записи
проверок выполняются во временных таблицах в `cat001_test`; после закрытия
соединений таблицы исчезают. CLI на `cat001_learning` здесь не запускается.

## 4. Настройка приложения в PyCharm

Создайте личную Run Configuration: Python из `.venv`, Module name
`catalog_import`, рабочая папка — корень проекта, Parameters — путь к CSV.
В Environment variables задайте:

```text
PGHOST=127.0.0.1
PGPORT=55433
PGDATABASE=cat001_learning
PGUSER=cat001_local
PGPASSWORD=<введите локально пароль роли>
```

Не включайте **Store as project file** и не публикуйте конфигурацию с секретами.
Python не загружает `.env` автоматически. Запуск этой конфигурации записывает
данные CSV в `cat001_learning`; для проверок выше он не требуется.

После выполнения сохраните только итоговые количества тестов и статусы команд,
без паролей, окружения и содержимого Docker inspect.
