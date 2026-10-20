-- Run only against the approved cat001_learning database.
-- Tests use the same definition for a connection-local temporary table.
CREATE TABLE products (
    sku TEXT COLLATE "C" PRIMARY KEY CHECK (btrim(sku) <> ''),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    price NUMERIC(12, 2) NOT NULL
        CHECK (price > 0 AND price <> 'NaN'::numeric),
    stock INTEGER NOT NULL CHECK (stock >= 0)
);
