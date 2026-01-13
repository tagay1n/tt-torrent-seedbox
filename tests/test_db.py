import sqlite3

from ttseed.db import init_db


def test_init_db_creates_tables():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "torrents" in tables
    assert "runs" in tables
