from __future__ import annotations

from geointx.settings import normalise_db_url


def test_postgres_urls_use_psycopg_and_drop_provider_params() -> None:
    url = "postgres://u:p@aws-1-x.pooler.supabase.com:6543/postgres?sslmode=require&supa=base-pooler.x"
    assert normalise_db_url(url) == (
        "postgresql+psycopg://u:p@aws-1-x.pooler.supabase.com:6543/postgres?sslmode=require"
    )
    assert normalise_db_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://u:p@h/db")


def test_non_postgres_urls_are_untouched() -> None:
    assert normalise_db_url("sqlite:///x.db") == "sqlite:///x.db"
