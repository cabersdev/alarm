-- Runs once on the first container start. Schema is created by the
-- application (SQLAlchemy models + create_all); here we only enable the
-- extension and set sane session defaults.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- UTC everywhere, less footgun than relying on the server locale.
ALTER DATABASE mcc SET timezone TO 'UTC';