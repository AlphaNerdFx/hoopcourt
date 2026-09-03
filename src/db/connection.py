"""SQLite connection factory with the sqlite-vec extension loaded.

Salvaged from BUILD_SEQUENCE.md:65-93, with an added capability probe:
extension loading is a compile-time option in Python's sqlite3, and a clear
error here is worth far more than an opaque failure deeper in the pipeline.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

# vec0 metadata filtering (the anti-bleed mechanism) needs a modern sqlite-vec,
# but the host sqlite itself only needs to support virtual-table triggers.
MIN_SQLITE_VERSION = (3, 37, 0)


class VectorEngineUnavailable(RuntimeError):
    """Raised when this interpreter cannot load the sqlite-vec extension."""


def get_vector_db_connection(db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and foreign keys enforced."""
    conn = sqlite3.connect(str(db_path))

    if not hasattr(conn, "enable_load_extension"):
        conn.close()
        raise VectorEngineUnavailable(
            "This Python was built without SQLite extension support, so "
            "sqlite-vec cannot be loaded. Install a Python with "
            "--enable-loadable-sqlite-extensions, or `pip install pysqlite3-binary`."
        )

    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except (AttributeError, sqlite3.OperationalError) as exc:  # pragma: no cover
        conn.close()
        raise VectorEngineUnavailable(f"Could not load sqlite-vec: {exc}") from exc
    finally:
        # Re-disable regardless of outcome: an open extension loader is an
        # arbitrary-code-execution surface (SECURITY.md sec.1.3).
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def engine_versions(conn: sqlite3.Connection) -> dict[str, str]:
    """Report both version numbers, for diagnostics and the /health endpoint."""
    return {
        "sqlite": sqlite3.sqlite_version,
        "sqlite_vec": conn.execute("SELECT vec_version()").fetchone()[0],
    }
