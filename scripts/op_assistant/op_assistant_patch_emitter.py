"""V0.3 Phase 7 — patch emitter + AST guard.

Reads a ``sandbox_verified`` candidate, generates a surgical patch on
``wannavegtour/query_parser.py``, runs the AST guard to make sure the
patch is exactly one element appended to a module-level data list, and
commits the result to git. If the guard rejects the patch, the
candidate moves to ``patch_too_invasive`` instead.

Per ``docs/contracts/op_assistant_v0.3/sandbox_protocol_v0.md`` §How
Phase 6 talks to Phase 8 and the V0.3 design doc Phase 7 section:

* Allowed patch:single new element on a module-level
  ``Tuple`` / ``List`` assigned to ``_AVAILABILITY_KEYWORDS``.
* Forbidden:any change to control flow, any new ``Import`` /
  ``FunctionDef`` / ``ClassDef`` / ``If`` / ``For`` / ``While``,
  modifications to other module-level statements.
* V0.3 simple version restricts ``availability_regex`` candidates to
  ``patch_too_invasive`` because adding a new module-level list +
  wiring it into the dispatch path would change control flow.

Code is Rule:no LLM is invoked anywhere in this module. The whole
verification logic is ``ast.parse`` + node-equality checks.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_PATH = os.environ.get(
    "WANNAVEGTOUR_REPO_PATH",
    "/home/wannavegtour/Desktop/AI Native Company/Gary",
)
QUERY_PARSER_PATH = Path(REPO_PATH) / "wannavegtour" / "query_parser.py"

if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

from closed_loop_kernel.store import KernelStore, json_param  # noqa: E402


# ---------------------------------------------------------------------------
# Patch emission for availability_keyword
# ---------------------------------------------------------------------------

def emit_keyword_patch(source: str, keyword: str) -> str:
    """Return new source text with ``keyword`` appended to
    ``_AVAILABILITY_KEYWORDS``. Raises ``PatchTooInvasiveError`` if the
    target tuple isn't a literal we can extend.
    """
    tree = ast.parse(source)
    target_node = _find_keyword_tuple_assign(tree)
    if target_node is None:
        raise PatchTooInvasiveError(
            "_AVAILABILITY_KEYWORDS module-level assignment not found"
        )
    value = target_node.value
    if not isinstance(value, ast.Tuple):
        raise PatchTooInvasiveError(
            f"_AVAILABILITY_KEYWORDS must be a tuple literal; got {type(value).__name__}"
        )
    for elt in value.elts:
        if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
            raise PatchTooInvasiveError(
                "_AVAILABILITY_KEYWORDS contains non-string-constant element"
            )
        if elt.value == keyword:
            raise KeywordAlreadyPresentError(
                f"keyword {keyword!r} already in _AVAILABILITY_KEYWORDS"
            )

    # Locate the closing paren of the tuple in source text so we can edit
    # the file textually (ast.unparse would rewrite formatting / comments
    # and the AST guard below relies on a precise textual delta).
    lines = source.splitlines(keepends=True)
    insert_line, insert_col = _find_tuple_close(lines, value)
    if insert_line is None or insert_col is None:
        raise PatchTooInvasiveError("unable to locate tuple closing paren")

    target_line = lines[insert_line]
    # Insert just before the closing ')'. Preserve indentation of the
    # last keyword line if possible.
    before = target_line[:insert_col]
    after = target_line[insert_col:]
    # If the closing paren is on its own line, indent the new element to
    # match the prior element's indent; otherwise put it inline with a comma.
    stripped = before.rstrip()
    if stripped.endswith(","):
        new_before = stripped + f' "{keyword}",\n'
        # we need to keep the closing line untouched
        lines[insert_line] = new_before + after.lstrip()
    elif before.strip() == "":
        # Closing paren on its own line, no trailing comma on prev elem
        indent_match = _detect_indent(lines, insert_line, value)
        lines[insert_line] = indent_match + f'"{keyword}",\n' + before + after
    else:
        # Tuple closes on the same line as elements; inject before ')'
        lines[insert_line] = before + f', "{keyword}"' + after
    return "".join(lines)


def _find_keyword_tuple_assign(tree: ast.Module) -> ast.Assign | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if isinstance(tgt, ast.Name) and tgt.id == "_AVAILABILITY_KEYWORDS":
            return node
    return None


def _find_tuple_close(
    lines: list[str], value: ast.Tuple
) -> tuple[int | None, int | None]:
    """Find the line+column of the tuple's closing paren by scanning from
    the tuple's first line forward, balancing parens.
    """
    start = (value.lineno - 1)
    depth = 0
    for li in range(start, len(lines)):
        line = lines[li]
        col_start = value.col_offset if li == start else 0
        for col in range(col_start, len(line)):
            ch = line[col]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return li, col
    return None, None


def _detect_indent(lines: list[str], insert_line: int,
                    value: ast.Tuple) -> str:
    """Match the indent of an existing tuple element so the appended
    keyword lines up with peers.
    """
    # Try to read the last existing elt's lineno
    if value.elts:
        last = value.elts[-1]
        last_line = lines[last.lineno - 1]
        return last_line[: len(last_line) - len(last_line.lstrip())]
    return "    "


class PatchTooInvasiveError(Exception):
    """Raised when emit_keyword_patch can't make a surgical edit."""


class KeywordAlreadyPresentError(Exception):
    """Raised when the candidate keyword is already in the parser."""


# ---------------------------------------------------------------------------
# AST guard — diff the two parses and make sure ONLY a single new
# element was appended to the right tuple.
# ---------------------------------------------------------------------------

def assert_patch_is_surgical(old_source: str, new_source: str,
                              expected_keyword: str) -> None:
    """Compare original vs patched ASTs. Anything but a single string-
    constant added to ``_AVAILABILITY_KEYWORDS`` raises
    ``PatchTooInvasiveError``.
    """
    old_tree = ast.parse(old_source)
    new_tree = ast.parse(new_source)

    if len(old_tree.body) != len(new_tree.body):
        raise PatchTooInvasiveError(
            f"module-level statement count changed "
            f"({len(old_tree.body)} → {len(new_tree.body)})"
        )

    target_index: int | None = None
    for i, (old_node, new_node) in enumerate(zip(old_tree.body, new_tree.body)):
        if _is_target_keyword_assign(old_node):
            if not _is_target_keyword_assign(new_node):
                raise PatchTooInvasiveError(
                    "_AVAILABILITY_KEYWORDS assignment was replaced"
                )
            target_index = i
        else:
            old_dump = ast.dump(old_node, annotate_fields=False)
            new_dump = ast.dump(new_node, annotate_fields=False)
            if old_dump != new_dump:
                raise PatchTooInvasiveError(
                    f"module-level statement #{i} changed unexpectedly"
                )

    if target_index is None:
        raise PatchTooInvasiveError(
            "_AVAILABILITY_KEYWORDS assignment not found in original"
        )

    old_tuple = old_tree.body[target_index].value
    new_tuple = new_tree.body[target_index].value
    if not isinstance(old_tuple, ast.Tuple) or not isinstance(new_tuple, ast.Tuple):
        raise PatchTooInvasiveError(
            "_AVAILABILITY_KEYWORDS value is not a tuple in one of the sources"
        )
    if len(new_tuple.elts) != len(old_tuple.elts) + 1:
        raise PatchTooInvasiveError(
            f"tuple length changed by {len(new_tuple.elts) - len(old_tuple.elts)},"
            f" expected +1"
        )
    # The first N elements of new_tuple must dump-equal the old elements
    # (in order). The extra one must be a string Constant matching keyword.
    for i, (o, n) in enumerate(zip(old_tuple.elts, new_tuple.elts)):
        if ast.dump(o, annotate_fields=False) != ast.dump(n, annotate_fields=False):
            raise PatchTooInvasiveError(
                f"existing tuple element #{i} changed"
            )
    added = new_tuple.elts[-1]
    if not isinstance(added, ast.Constant) or not isinstance(added.value, str):
        raise PatchTooInvasiveError(
            "added element is not a string constant"
        )
    if added.value != expected_keyword:
        raise PatchTooInvasiveError(
            f"added element {added.value!r} != expected {expected_keyword!r}"
        )


def _is_target_keyword_assign(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    tgt = node.targets[0]
    return isinstance(tgt, ast.Name) and tgt.id == "_AVAILABILITY_KEYWORDS"


# ---------------------------------------------------------------------------
# Git commit emission
# ---------------------------------------------------------------------------

def commit_patch(file_relpath: str, message: str,
                  approver_actor: str) -> str:
    """``git add`` + ``git commit`` the patched file with a co-author
    line. Returns the new commit SHA.
    """
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "OP Assistant gemma4 proposer")
    env.setdefault("GIT_AUTHOR_EMAIL", "op-assistant@wannavegtour.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "OP Assistant gemma4 proposer")
    env.setdefault("GIT_COMMITTER_EMAIL", "op-assistant@wannavegtour.invalid")
    subprocess.run(
        ["git", "-C", REPO_PATH, "add", file_relpath],
        check=True, env=env,
    )
    body = message
    if "Co-Authored-By" not in body:
        body += f"\n\nApproved-By: {approver_actor}\n"
    subprocess.run(
        ["git", "-C", REPO_PATH, "commit", "-m", body],
        check=True, env=env,
    )
    out = subprocess.run(
        ["git", "-C", REPO_PATH, "rev-parse", "HEAD"],
        check=True, env=env, capture_output=True, text=True,
    )
    return out.stdout.strip()


# ---------------------------------------------------------------------------
# Candidate-driven entry point
# ---------------------------------------------------------------------------

def emit_for_candidate(store: KernelStore, candidate_id: str,
                        target_db_url: str | None = None) -> dict[str, Any]:
    """Read the candidate, emit the patch, run AST guard, commit. UPDATE
    the candidate status to either ``patch_emitted`` (success) or
    ``patch_too_invasive`` (rejected). Records a
    ``candidate_status_changed`` event each way.

    Returns a dict for caller logging.
    """
    cand = store.fetch_one(
        "SELECT id::text AS id, proposal_type, typed_payload, status "
        "FROM improvement_candidates WHERE id = ?",
        [candidate_id],
    )
    if cand is None:
        return {"status": "missing", "candidate_id": candidate_id}
    if cand["status"] != "sandbox_verified":
        return {
            "status": "wrong_state",
            "candidate_status": cand["status"],
            "candidate_id": candidate_id,
        }
    typed = cand["typed_payload"]
    if isinstance(typed, str):
        typed = json.loads(typed)
    value = typed.get("value", "")
    proposal_type = cand["proposal_type"]

    # V0.3 Phase 7 only patches keyword candidates; regex needs a new
    # module-level list + dispatch-flow change, which would fail the
    # AST guard. Mark the candidate as patch_too_invasive instead.
    if proposal_type != "availability_keyword":
        _mark_too_invasive(
            store, candidate_id,
            reason=f"V0.3 patch_emitter supports availability_keyword only; "
                   f"got {proposal_type}",
            approver_actor="system",
        )
        return {
            "status": "patch_too_invasive",
            "candidate_id": candidate_id,
            "reason": "non_keyword_proposal_type",
        }

    source = QUERY_PARSER_PATH.read_text(encoding="utf-8")
    try:
        new_source = emit_keyword_patch(source, value)
    except KeywordAlreadyPresentError:
        # Already there → no patch needed; treat as success with no commit.
        _mark_emitted(
            store, candidate_id, commit_sha="(no-op-already-present)",
            keyword=value, approver_actor="system",
        )
        return {
            "status": "no_op_already_present",
            "candidate_id": candidate_id,
        }
    except PatchTooInvasiveError as exc:
        _mark_too_invasive(
            store, candidate_id, reason=str(exc), approver_actor="system",
        )
        return {
            "status": "patch_too_invasive",
            "candidate_id": candidate_id,
            "reason": str(exc),
        }

    # AST guard — the final say.
    try:
        assert_patch_is_surgical(source, new_source, value)
    except PatchTooInvasiveError as exc:
        _mark_too_invasive(
            store, candidate_id, reason=f"AST guard: {exc}",
            approver_actor="system",
        )
        return {
            "status": "patch_too_invasive",
            "candidate_id": candidate_id,
            "reason": str(exc),
        }

    QUERY_PARSER_PATH.write_text(new_source, encoding="utf-8")

    # Find the approver from the latest approvals row for this candidate
    approver_row = store.fetch_one(
        "SELECT approved_by FROM approvals WHERE candidate_id = ? "
        "AND decision = 'approved' ORDER BY created_at DESC LIMIT 1",
        [candidate_id],
    )
    approver_actor = (approver_row or {}).get("approved_by") or "unknown"

    commit_message = (
        f"auto-patch(op-assistant): teach bot the keyword \"{value}\"\n\n"
        f"Generated by Phase 7 patch emitter from improvement_candidates row\n"
        f"{candidate_id}, after sandbox replay metrics passed. The keyword is\n"
        f"appended to wannavegtour/query_parser.py _AVAILABILITY_KEYWORDS so\n"
        f"the parser routes the message to availability_check next time.\n\n"
        f"Co-Authored-By: gemma4 proposer <ops@wannavegtour.invalid>\n"
    )
    try:
        sha = commit_patch(
            "wannavegtour/query_parser.py", commit_message, approver_actor,
        )
    except subprocess.CalledProcessError as exc:
        # Revert the source file change on commit failure so the working
        # tree stays clean for the next attempt.
        QUERY_PARSER_PATH.write_text(source, encoding="utf-8")
        _mark_too_invasive(
            store, candidate_id,
            reason=f"git commit failed: returncode={exc.returncode}",
            approver_actor=approver_actor,
        )
        return {
            "status": "patch_too_invasive",
            "candidate_id": candidate_id,
            "reason": "git_commit_failed",
        }

    _mark_emitted(
        store, candidate_id, commit_sha=sha, keyword=value,
        approver_actor=approver_actor,
    )
    return {
        "status": "patch_emitted",
        "candidate_id": candidate_id,
        "commit_sha": sha,
        "keyword": value,
    }


def _mark_emitted(store: KernelStore, candidate_id: str, *,
                   commit_sha: str, keyword: str,
                   approver_actor: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with store.transaction() as tx:
        tx.execute(
            "UPDATE improvement_candidates SET status = 'patch_emitted' "
            "WHERE id = ? AND status = 'sandbox_verified'",
            [candidate_id],
        )
        tx.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "candidate_status_changed",
                json_param({
                    "candidate_id": candidate_id,
                    "from_status": "sandbox_verified",
                    "to_status": "patch_emitted",
                    "by_phase": "phase_7_patch_emitter",
                    "by_actor": approver_actor,
                    "commit_sha": commit_sha,
                    "keyword": keyword,
                }),
                now_iso,
            ],
        )


def _mark_too_invasive(store: KernelStore, candidate_id: str, *,
                        reason: str, approver_actor: str) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with store.transaction() as tx:
        tx.execute(
            "UPDATE improvement_candidates SET status = 'patch_too_invasive' "
            "WHERE id = ? AND status = 'sandbox_verified'",
            [candidate_id],
        )
        tx.execute(
            "INSERT INTO events (id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            [
                str(uuid.uuid4()),
                "candidate_status_changed",
                json_param({
                    "candidate_id": candidate_id,
                    "from_status": "sandbox_verified",
                    "to_status": "patch_too_invasive",
                    "by_phase": "phase_7_patch_emitter",
                    "by_actor": approver_actor,
                    "reason": reason,
                }),
                now_iso,
            ],
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_env() -> None:
    profile = os.environ.get("HERMES_PROFILE", "op-assistant")
    for path in [
        Path.home() / ".hermes" / "profiles" / profile / ".env",
        Path.home() / ".hermes" / ".env",
    ]:
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(),
                                   val.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--target-db", default=None,
                         help="override KERNEL_DATABASE_URL")
    args = parser.parse_args()
    url = args.target_db or os.environ["KERNEL_DATABASE_URL"]
    store = KernelStore.from_url(url)
    try:
        result = emit_for_candidate(store, args.candidate_id, url)
    finally:
        store.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("patch_emitted", "no_op_already_present") else 1


if __name__ == "__main__":
    sys.exit(main())
