"""PostgreSQL 連線 helper(psycopg v3)。"""
from __future__ import annotations

import psycopg

from config import load_db_config


def get_conn() -> psycopg.Connection:
    return psycopg.connect(**load_db_config())


def start_run(conn, stage: str, version: str, input_count: int = 0) -> int:
    row = conn.execute(
        "INSERT INTO pipeline_runs (stage, pipeline_version, input_count) "
        "VALUES (%s, %s, %s) RETURNING id",
        (stage, version, input_count),
    ).fetchone()
    conn.commit()
    return row[0]


def finish_run(conn, run_id: int, output_count: int, status: str = "done", notes: str = "") -> None:
    conn.execute(
        "UPDATE pipeline_runs SET finished_at=now(), output_count=%s, status=%s, notes=%s WHERE id=%s",
        (output_count, status, notes, run_id),
    )
    conn.commit()
