from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR / 'records.db'}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    # WAL lets background workers write while the API reads; busy_timeout waits instead of erroring.
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate() -> None:
    """Create tables and add any columns introduced after the database was first created."""
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = column.type.compile(engine.dialect)
                default = ""
                if column.default is not None and not callable(column.default.arg):
                    arg = column.default.arg
                    default = f" DEFAULT {repr(arg) if isinstance(arg, str) else int(arg) if isinstance(arg, bool) else arg}"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {ddl}{default}'))
        # Records filed before grade scales existed: marks-based sheets are percentage scale.
        conn.execute(
            text("UPDATE records SET grade_scale = 'percentage' WHERE grade_scale IS NULL AND percentage IS NOT NULL")
        )
        conn.execute(text("UPDATE records SET engine_notes = '[]' WHERE engine_notes IS NULL OR engine_notes = ''"))
