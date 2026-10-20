-- Preparation only: do not execute before checking the server and approval.
-- Connect to the administrative database of the verified existing server.
-- Run without a transaction. Existing databases are deliberately not modified.
-- The executing role becomes the owner; no roles or passwords are created.
CREATE DATABASE cat001_learning;
CREATE DATABASE cat001_test;
