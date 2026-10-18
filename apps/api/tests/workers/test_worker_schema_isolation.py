from app.db.base import Base
from sqlalchemy import inspect, text


def test_worker_engine_owns_all_application_tables(worker_engine):
    with worker_engine.connect() as connection:
        schema = connection.scalar(text("SELECT current_schema()"))
        search_path = connection.scalar(text("SELECT current_schemas(false)"))

        assert schema.startswith("worker_test_")
        assert "public" not in search_path
        tables = set(inspect(connection).get_table_names(schema=schema))
        assert {table.name for table in Base.metadata.tables.values()} <= tables
