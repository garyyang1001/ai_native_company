from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


DEFAULT_RUNNER_ROLE = "sandbox_runner"
SCHEMA_PREFIX = "sandbox_temp_"


@dataclass(frozen=True)
class SqlSandboxResult:
    status: str
    schema: str
    rows: list[Any] = field(default_factory=list)
    error_message: str | None = None


class SqlSandbox:
    """
    隔離 SQL replay 沙盒。

    每一次 replay 都會：
      1. 開一個 `sandbox_temp_<uuid>` schema（admin 連線、autocommit）；
      2. 由低權限角色 `sandbox_runner` 在該 schema 內以 `SET LOCAL ROLE` 切換身份執行候選 SQL；
      3. 不論成功失敗，最後一律 `DROP SCHEMA ... CASCADE` 清理。

    Spec note (event-flow-v0.md §3.1)：規格寫的是「獨立資料庫連線帳號」。
    Prototype 階段這裡走 `SET LOCAL ROLE`：privilege boundary 依然由 sandbox_runner
    的 GRANT/REVOKE 強制，事務結束自動恢復角色；省去本機 trust auth 配置。
    產線階段應升級為獨立 psycopg.connect(user=sandbox_runner, ...) 物理連線。
    """

    def __init__(self, admin_url: str, runner_role: str = DEFAULT_RUNNER_ROLE):
        self.admin_url = admin_url
        self.runner_role = runner_role

    def ensure_role(self) -> None:
        """
        建立 / 修補 sandbox_runner 角色，是 idempotent 的：
          - 不存在就 CREATE ROLE（NOLOGIN，避免被當外部登入用）；
          - 收回 public schema 的預設權限（USAGE/CREATE/表/序列/函式）；
          - 把 sandbox_runner 授予當前 admin user，讓 `SET ROLE` 能切過去。
        """
        psycopg, sql = _import_psycopg()
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (self.runner_role,))
                if cur.fetchone() is None:
                    cur.execute(
                        sql.SQL("CREATE ROLE {role} NOLOGIN NOINHERIT").format(
                            role=sql.Identifier(self.runner_role)
                        )
                    )
                role_ident = sql.Identifier(self.runner_role)
                cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {role}").format(role=role_ident))
                cur.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}").format(role=role_ident))
                cur.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}").format(role=role_ident))
                cur.execute(sql.SQL("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM {role}").format(role=role_ident))
                cur.execute("SELECT current_user")
                current_user = cur.fetchone()[0]
                cur.execute(
                    sql.SQL("GRANT {role} TO {grantee}").format(
                        role=role_ident,
                        grantee=sql.Identifier(current_user),
                    )
                )

    @contextmanager
    def temp_schema(self) -> Iterator[str]:
        """產生 `sandbox_temp_<12-hex>` schema，授予 runner USAGE+CREATE，離開時 CASCADE 刪除。"""
        psycopg, sql = _import_psycopg()
        schema_name = f"{SCHEMA_PREFIX}{uuid.uuid4().hex[:12]}"
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE SCHEMA {schema}").format(schema=sql.Identifier(schema_name)))
                cur.execute(
                    sql.SQL("GRANT USAGE, CREATE ON SCHEMA {schema} TO {role}").format(
                        schema=sql.Identifier(schema_name),
                        role=sql.Identifier(self.runner_role),
                    )
                )
        try:
            yield schema_name
        finally:
            with psycopg.connect(self.admin_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {schema} CASCADE").format(
                            schema=sql.Identifier(schema_name)
                        )
                    )

    def run_as_runner(self, sql_text: str, schema: str) -> SqlSandboxResult:
        """
        以 sandbox_runner 身份在 `schema` 內執行 SQL，回傳 rows 或 error_message。

        交易內順序：SET LOCAL search_path → SET LOCAL ROLE → execute。
        交易結束（COMMIT 或 ROLLBACK）後 SET LOCAL 自動失效，角色與 search_path 回到 admin。
        """
        psycopg, sql = _import_psycopg()
        rows: list[Any] = []
        try:
            with psycopg.connect(self.admin_url, autocommit=False) as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            sql.SQL("SET LOCAL search_path = {schema}, public").format(
                                schema=sql.Identifier(schema)
                            )
                        )
                        cur.execute(
                            sql.SQL("SET LOCAL ROLE {role}").format(role=sql.Identifier(self.runner_role))
                        )
                        cur.execute(sql_text)
                        try:
                            rows = list(cur.fetchall())
                        except psycopg.ProgrammingError:
                            # DDL / DML 沒有 result set；不算錯。
                            rows = []
            return SqlSandboxResult(status="success", schema=schema, rows=rows)
        except Exception as exc:
            return SqlSandboxResult(
                status="failed",
                schema=schema,
                rows=[],
                error_message=f"{type(exc).__name__}: {exc}",
            )


def _import_psycopg():
    try:
        import psycopg
        from psycopg import sql
    except ModuleNotFoundError as exc:
        raise RuntimeError("SqlSandbox requires the optional 'psycopg' package") from exc
    return psycopg, sql
