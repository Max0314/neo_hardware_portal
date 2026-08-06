#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safely merge and remove confirmed suffix-less material-library aliases.

The script is intentionally conservative:

* running without ``--apply`` is read-only;
* only collisions using ``CONFIRMED_TYPE_SUFFIXES`` are ever considered;
* cleanup requires the plan digest printed by a prior dry-run;
* rows are locked and the digest is checked again immediately before mutation;
* a JSON backup is durably written before mutation;
* current material data, source metadata, prefixes, and user permissions are
  checked before a suffix-less library can be deleted;
* unique legacy history data versions are copied to the retained library.

The script does not call YiDa.  In particular, ``0805电阻(R)`` must already
have been restored by the normal YiDa synchronization before cleanup.

Examples::

    # Read-only inspection (default)
    python scripts/material_library_dedupe.py

    # Apply the exact plan printed by the preceding dry-run
    python scripts/material_library_dedupe.py \
        --apply --expected-plan-digest <sha256>

    # Preview a rollback from a cleanup backup
    python scripts/material_library_dedupe.py --restore /app/data/...json

    # Apply that exact rollback preview
    python scripts/material_library_dedupe.py \
        --restore /app/data/...json --apply \
        --expected-plan-digest <restore-plan-sha256>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCRIPT_VERSION = "1.0"
BACKUP_SCHEMA_VERSION = 1
REQUIRED_RESTORED_LIBRARY = "0805电阻(R)"

# This allowlist is deliberately explicit.  Do not derive deletion targets by
# stripping arbitrary suffixes: similarly named user-created libraries may be
# semantically different.
CONFIRMED_TYPE_SUFFIXES: Tuple[str, ...] = ("C", "R", "L", "FB", "ECA")

LIBRARY_COLUMNS: Tuple[str, ...] = (
    "id",
    "name",
    "prefix",
    "password_hash",
    "current_table_json",
    "history_tables_json",
    "created_at",
    "updated_at",
)
AUDIT_COLUMNS: Tuple[str, ...] = (
    "id",
    "user_id",
    "user_display",
    "action",
    "library_id",
    "library_name",
    "detail",
    "created_at",
)


class SafetyError(RuntimeError):
    """A failed cleanup/restore precondition."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _parse_json_field(value: Any, expected_type: type, label: str) -> Any:
    if isinstance(value, expected_type):
        return deepcopy(value)
    if value is None or value == "":
        if expected_type is list:
            return []
        raise SafetyError("invalid_json", f"{label} 为空")
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SafetyError("invalid_json", f"{label} 不是有效 JSON: {exc}") from exc
    if not isinstance(parsed, expected_type):
        raise SafetyError(
            "invalid_json_type",
            f"{label} 类型应为 {expected_type.__name__}，实际为 {type(parsed).__name__}",
        )
    return parsed


def _current_table_semantics(table: Mapping[str, Any]) -> Dict[str, Any]:
    """Return all current-table fields except the library-specific filename."""
    return {key: deepcopy(value) for key, value in table.items() if key != "fileName"}


def _validate_current_tables(
    legacy_row: Mapping[str, Any], retained_row: Mapping[str, Any]
) -> str:
    legacy_name = str(legacy_row.get("name") or "")
    retained_name = str(retained_row.get("name") or "")
    legacy = _parse_json_field(
        legacy_row.get("current_table_json"), dict, f"{legacy_name}.current_table_json"
    )
    retained = _parse_json_field(
        retained_row.get("current_table_json"), dict, f"{retained_name}.current_table_json"
    )
    legacy_data = legacy.get("data")
    retained_data = retained.get("data")
    if not isinstance(legacy_data, list) or not isinstance(retained_data, list):
        raise SafetyError(
            "invalid_current_data",
            f"{legacy_name} / {retained_name} 的 currentTable.data 必须都是数组",
        )
    if legacy_data != retained_data:
        raise SafetyError(
            "current_data_mismatch",
            f"{legacy_name} 与 {retained_name} 的当前表物料数据不完全一致",
            {
                "legacy_data_digest": _digest(legacy_data),
                "retained_data_digest": _digest(retained_data),
            },
        )
    if _current_table_semantics(legacy) != _current_table_semantics(retained):
        raise SafetyError(
            "current_metadata_mismatch",
            f"{legacy_name} 与 {retained_name} 除 fileName 外的当前表元数据不一致",
            {
                "legacy_semantics_digest": _digest(_current_table_semantics(legacy)),
                "retained_semantics_digest": _digest(_current_table_semantics(retained)),
            },
        )
    return _digest(legacy_data)


def _history_data_digest(item: Mapping[str, Any], label: str) -> str:
    if "data" not in item or not isinstance(item.get("data"), list):
        raise SafetyError(
            "invalid_history_data",
            f"{label} 缺少数组类型的 data；为避免丢失未知历史，已中止",
        )
    return _digest(item["data"])


def merge_unique_history(
    legacy_history: Sequence[Mapping[str, Any]],
    retained_history: Sequence[Mapping[str, Any]],
    retained_current: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Merge legacy-only data versions while preserving retained duplicates.

    Existing retained history is left intact.  A legacy entry is copied only
    when its exact ``data`` value does not already exist in the retained
    current table, retained history, or an earlier copied legacy entry.
    """
    retained_current_data = retained_current.get("data")
    if not isinstance(retained_current_data, list):
        raise SafetyError(
            "invalid_current_data",
            "保留库 currentTable.data 必须为数组",
        )

    merged: List[Dict[str, Any]] = []
    known = {_digest(retained_current_data)}
    for index, item in enumerate(retained_history):
        if not isinstance(item, Mapping):
            raise SafetyError(
                "invalid_history_entry",
                f"保留库历史第 {index + 1} 项不是对象",
            )
        known.add(_history_data_digest(item, f"保留库历史第 {index + 1} 项"))
        merged.append(deepcopy(dict(item)))

    copied: List[Dict[str, Any]] = []
    copied_digests: List[str] = []
    for index, item in enumerate(legacy_history):
        if not isinstance(item, Mapping):
            raise SafetyError(
                "invalid_history_entry",
                f"旧库历史第 {index + 1} 项不是对象",
            )
        data_digest = _history_data_digest(item, f"旧库历史第 {index + 1} 项")
        if data_digest in known:
            continue
        known.add(data_digest)
        copied.append(deepcopy(dict(item)))
        copied_digests.append(data_digest)

    # History is normally newest-first.  ISO/SQL timestamps both sort correctly
    # lexicographically; stable sorting preserves the original order on ties.
    merged.extend(copied)
    merged.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    return merged, copied_digests


def _parse_library_roles(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in text.split(",") if item.strip()]


def _dict_rows(cursor: Any) -> List[Dict[str, Any]]:
    rows = cursor.fetchall() or []
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return [dict(row) for row in rows]
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _fetch_libraries(cursor: Any, *, for_update: bool = False) -> List[Dict[str, Any]]:
    # Collision discovery is data-driven, so inspect every library.  Mutation
    # remains limited to the controlled suffix allowlist and exact planned IDs.
    sql = (
        f"SELECT {', '.join(LIBRARY_COLUMNS)} "
        "FROM material_db_libraries ORDER BY name, id"
    )
    if for_update:
        sql += " FOR UPDATE"
    cursor.execute(sql)
    return _dict_rows(cursor)


def _fetch_users(cursor: Any, *, for_update: bool = False) -> List[Dict[str, Any]]:
    sql = "SELECT id, username, library_roles FROM users ORDER BY id"
    if for_update:
        sql += " FOR UPDATE"
    cursor.execute(sql)
    return _dict_rows(cursor)


def _index_unique_names(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("name") or ""), []).append(dict(row))
    duplicates = {name: len(items) for name, items in grouped.items() if len(items) != 1}
    if duplicates:
        raise SafetyError(
            "duplicate_exact_names",
            "数据库中存在同名物料库，无法唯一确定清理目标",
            duplicates,
        )
    return {name: items[0] for name, items in grouped.items()}


def _suffix_alias(name: str) -> Optional[str]:
    normalized = str(name or "").strip().replace("（", "(").replace("）", ")")
    for suffix in CONFIRMED_TYPE_SUFFIXES:
        marker = f"({suffix})"
        if normalized.endswith(marker):
            alias = normalized[: -len(marker)].strip()
            return alias or None
    return None


def discover_collision_pairs(
    rows: Iterable[Mapping[str, Any]],
) -> List[Tuple[str, str]]:
    """Discover current suffix-less/suffixed collisions from database names."""
    names = {
        str(row.get("name") or "").strip()
        for row in rows
        if str(row.get("name") or "").strip()
    }
    pairs = []
    for retained_name in sorted(names):
        alias = _suffix_alias(retained_name)
        if alias and alias in names:
            pairs.append((alias, retained_name))
    return pairs


def _logical_library_fingerprint(row: Mapping[str, Any]) -> str:
    # updated_at is intentionally excluded: cleanup changes it when history is
    # merged, while all content-bearing fields remain protected.
    return _digest(
        {
            key: row.get(key)
            for key in LIBRARY_COLUMNS
            if key != "updated_at"
        }
    )


def _raw_library_fingerprint(row: Mapping[str, Any]) -> str:
    return _digest({key: row.get(key) for key in LIBRARY_COLUMNS})


def build_cleanup_plan(
    library_rows: Sequence[Mapping[str, Any]],
    users: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    by_name = _index_unique_names(library_rows)
    collision_pairs = discover_collision_pairs(library_rows)
    required = by_name.get(REQUIRED_RESTORED_LIBRARY)
    errors: List[Dict[str, Any]] = []
    if not required:
        errors.append(
            {
                "code": "required_library_missing",
                "message": (
                    f"{REQUIRED_RESTORED_LIBRARY} 不存在；请先通过正常宜搭同步恢复，"
                    "本脚本不会调用宜搭"
                ),
            }
        )

    parsed_users = [
        {
            "id": user.get("id"),
            "username": user.get("username"),
            "roles": _parse_library_roles(user.get("library_roles")),
            "raw_roles": user.get("library_roles"),
        }
        for user in users
    ]
    pair_plans: List[Dict[str, Any]] = []

    retained_by_legacy: Dict[str, List[str]] = {}
    for legacy_name, retained_name in collision_pairs:
        retained_by_legacy.setdefault(legacy_name, []).append(retained_name)
    ambiguous = {
        legacy: retained_names
        for legacy, retained_names in retained_by_legacy.items()
        if len(retained_names) != 1
    }
    if ambiguous:
        errors.append(
            {
                "code": "ambiguous_suffix_collision",
                "message": "同一个无后缀库匹配到多个带后缀库，无法自动选择",
                "details": ambiguous,
            }
        )

    for legacy_name, retained_name in collision_pairs:
        legacy = by_name.get(legacy_name)
        retained = by_name.get(retained_name)
        pair: Dict[str, Any] = {
            "legacy_name": legacy_name,
            "retained_name": retained_name,
        }
        if not legacy and retained:
            pair["status"] = "already_clean"
            pair["retained_id"] = retained["id"]
            pair["retained_fingerprint"] = _raw_library_fingerprint(retained)
            pair_plans.append(pair)
            continue
        if not legacy and not retained:
            pair["status"] = "error"
            pair["error"] = "legacy_and_retained_missing"
            errors.append(
                {
                    "code": "pair_missing",
                    "message": f"{legacy_name} 与 {retained_name} 均不存在",
                }
            )
            pair_plans.append(pair)
            continue
        if legacy and not retained:
            pair["status"] = "error"
            pair["legacy_id"] = legacy["id"]
            pair["error"] = "retained_missing"
            errors.append(
                {
                    "code": "retained_missing",
                    "message": f"{legacy_name} 存在，但应保留的 {retained_name} 不存在",
                }
            )
            pair_plans.append(pair)
            continue

        assert legacy is not None and retained is not None
        pair.update(
            {
                "status": "pending_delete",
                "legacy_id": legacy["id"],
                "retained_id": retained["id"],
                "legacy_fingerprint": _raw_library_fingerprint(legacy),
                "retained_fingerprint": _raw_library_fingerprint(retained),
            }
        )
        pair_errors: List[Dict[str, Any]] = []

        if str(legacy.get("prefix") or "") != str(retained.get("prefix") or ""):
            pair_errors.append(
                {
                    "code": "prefix_mismatch",
                    "legacy_prefix": str(legacy.get("prefix") or ""),
                    "retained_prefix": str(retained.get("prefix") or ""),
                }
            )

        refs = []
        legacy_tokens = {str(legacy["id"]), legacy_name}
        for user in parsed_users:
            matched = sorted(legacy_tokens.intersection(user["roles"]))
            if matched:
                refs.append(
                    {
                        "user_id": user["id"],
                        "username": user["username"],
                        "matched": matched,
                    }
                )
        if refs:
            pair_errors.append({"code": "permission_references", "users": refs})

        try:
            pair["current_data_digest"] = _validate_current_tables(legacy, retained)
            legacy_history = _parse_json_field(
                legacy.get("history_tables_json"),
                list,
                f"{legacy_name}.history_tables_json",
            )
            retained_history = _parse_json_field(
                retained.get("history_tables_json"),
                list,
                f"{retained_name}.history_tables_json",
            )
            retained_current = _parse_json_field(
                retained.get("current_table_json"),
                dict,
                f"{retained_name}.current_table_json",
            )
            merged_history, copied_digests = merge_unique_history(
                legacy_history, retained_history, retained_current
            )
            pair.update(
                {
                    "legacy_history_count": len(legacy_history),
                    "retained_history_count_before": len(retained_history),
                    "retained_history_count_after": len(merged_history),
                    "copied_history_count": len(copied_digests),
                    "copied_history_data_digests": copied_digests,
                    "_merged_history": merged_history,
                }
            )
        except SafetyError as exc:
            pair_errors.append(
                {"code": exc.code, "message": exc.message, "details": exc.details}
            )

        if pair_errors:
            pair["status"] = "error"
            pair["errors"] = pair_errors
            errors.extend(
                {
                    "code": item["code"],
                    "message": f"{legacy_name} -> {retained_name}: "
                    + str(item.get("message") or item["code"]),
                    "details": item,
                }
                for item in pair_errors
            )
        pair_plans.append(pair)

    digest_input = {
        "script_version": SCRIPT_VERSION,
        "confirmed_type_suffixes": CONFIRMED_TYPE_SUFFIXES,
        "collision_pairs": collision_pairs,
        "required_library": (
            {
                "id": required.get("id"),
                "fingerprint": _raw_library_fingerprint(required),
            }
            if required
            else None
        ),
        "pairs": [
            {key: value for key, value in pair.items() if key != "_merged_history"}
            for pair in pair_plans
        ],
        "user_role_state": [
            {
                "id": user["id"],
                "roles_digest": _digest(user["raw_roles"]),
            }
            for user in parsed_users
        ],
    }
    return {
        "safe": not errors,
        "plan_digest": _digest(digest_input),
        "pairs": pair_plans,
        "errors": errors,
        "pending_delete_count": sum(
            pair.get("status") == "pending_delete" for pair in pair_plans
        ),
        "already_clean_count": sum(
            pair.get("status") == "already_clean" for pair in pair_plans
        ),
        "history_versions_to_copy": sum(
            int(pair.get("copied_history_count") or 0) for pair in pair_plans
        ),
        "collision_pairs": collision_pairs,
        "_state": digest_input,
    }


def _public_plan(plan: Mapping[str, Any]) -> Dict[str, Any]:
    pairs = []
    for pair in plan["pairs"]:
        pairs.append(
            {
                key: value
                for key, value in pair.items()
                if key
                not in {
                    "_merged_history",
                    "legacy_fingerprint",
                    "retained_fingerprint",
                }
            }
        )
    return {
        "safe": plan["safe"],
        "plan_digest": plan["plan_digest"],
        "pending_delete_count": plan["pending_delete_count"],
        "already_clean_count": plan["already_clean_count"],
        "history_versions_to_copy": plan["history_versions_to_copy"],
        "required_library": REQUIRED_RESTORED_LIBRARY,
        "confirmed_type_suffixes": list(CONFIRMED_TYPE_SUFFIXES),
        "collision_pairs": [list(pair) for pair in plan["collision_pairs"]],
        "pairs": pairs,
        "errors": plan["errors"],
    }


def _fetch_backup_audit(
    cursor: Any, affected_ids: Sequence[str], affected_names: Sequence[str]
) -> List[Dict[str, Any]]:
    if not affected_ids and not affected_names:
        return []
    id_placeholders = ",".join(["%s"] * len(affected_ids)) or "NULL"
    name_placeholders = ",".join(["%s"] * len(affected_names)) or "NULL"
    cursor.execute(
        f"SELECT {', '.join(AUDIT_COLUMNS)} FROM material_db_audit "
        f"WHERE library_id IN ({id_placeholders}) "
        f"OR library_name IN ({name_placeholders}) ORDER BY id",
        tuple(affected_ids) + tuple(affected_names),
    )
    return _dict_rows(cursor)


def _backup_document(
    *,
    kind: str,
    plan: Mapping[str, Any],
    library_rows: Sequence[Mapping[str, Any]],
    users: Sequence[Mapping[str, Any]],
    audit_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    collision_pairs = [tuple(pair) for pair in plan["collision_pairs"]]
    target_names = {name for pair in collision_pairs for name in pair}
    selected_libraries = [
        {column: row.get(column) for column in LIBRARY_COLUMNS}
        for row in library_rows
        if str(row.get("name") or "") in target_names
    ]

    expected_post_apply = []
    for pair in plan["pairs"]:
        if pair.get("status") != "pending_delete":
            continue
        retained = next(
            row for row in selected_libraries if row["id"] == pair["retained_id"]
        )
        post_row = dict(retained)
        post_row["history_tables_json"] = json.dumps(
            pair["_merged_history"], ensure_ascii=False, separators=(",", ":")
        )
        expected_post_apply.append(
            {
                "legacy_id": pair["legacy_id"],
                "legacy_name": pair["legacy_name"],
                "retained_id": pair["retained_id"],
                "retained_name": pair["retained_name"],
                "retained_logical_fingerprint": _logical_library_fingerprint(post_row),
            }
        )

    document: Dict[str, Any] = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "script_version": SCRIPT_VERSION,
        "kind": kind,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cleanup_plan_digest": plan["plan_digest"],
        "confirmed_type_suffixes": list(CONFIRMED_TYPE_SUFFIXES),
        "collision_pairs": [list(pair) for pair in collision_pairs],
        "required_restored_library": REQUIRED_RESTORED_LIBRARY,
        "snapshot": {
            "material_db_libraries": selected_libraries,
            "material_db_audit": [
                {column: row.get(column) for column in AUDIT_COLUMNS}
                for row in audit_rows
            ],
            "users_library_roles": [
                {
                    "id": row.get("id"),
                    "username": row.get("username"),
                    "library_roles": row.get("library_roles"),
                }
                for row in users
                if row.get("library_roles") not in (None, "")
            ],
        },
        "expected_post_apply": expected_post_apply,
        "restore_note": (
            "Restore replays only the affected material_db_libraries rows. "
            "Audit history is preserved and user permissions are not rewritten "
            "because cleanup refuses any legacy-library permission reference."
        ),
    }
    document["integrity"] = {
        "algorithm": "sha256",
        "sha256": _digest(document),
    }
    return document


def _default_backup_path(kind: str, plan_digest: str) -> Path:
    app_dir = Path(__file__).resolve().parent.parent
    backup_dir = Path(
        os.getenv(
            "MATERIAL_DEDUPE_BACKUP_DIR",
            str(app_dir / "data" / "material_library_dedupe_backups"),
        )
    )
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return backup_dir / f"{kind}-{timestamp}-{plan_digest[:12]}.json"


def _write_json_backup(document: Mapping[str, Any], path: Path) -> Path:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        default=_json_default,
    ) + "\n"

    # Write an exclusive temporary file, fsync, then atomically publish.  The
    # final path must not already exist so an earlier backup is never replaced.
    if path.exists():
        raise SafetyError("backup_exists", f"备份文件已存在，拒绝覆盖: {path}")
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # os.link gives exclusive publication on platforms that support it.
        try:
            os.link(temp_name, path)
            os.unlink(temp_name)
        except (AttributeError, OSError):
            if path.exists():
                raise SafetyError("backup_exists", f"备份文件已存在，拒绝覆盖: {path}")
            os.replace(temp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return path


def _load_backup(path: Path) -> Dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyError("backup_read_failed", f"无法读取备份 {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise SafetyError("invalid_backup", "备份根节点不是 JSON 对象")
    integrity = document.pop("integrity", None)
    if (
        not isinstance(integrity, dict)
        or integrity.get("algorithm") != "sha256"
        or integrity.get("sha256") != _digest(document)
    ):
        raise SafetyError("backup_integrity_failed", "备份完整性校验失败")
    document["integrity"] = integrity
    if document.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise SafetyError(
            "unsupported_backup_schema",
            f"不支持的备份版本: {document.get('schema_version')}",
        )
    if document.get("confirmed_type_suffixes") != list(CONFIRMED_TYPE_SUFFIXES):
        raise SafetyError(
            "backup_target_mismatch",
            "备份中的受控类型后缀与本脚本不一致",
        )
    backup_pairs = document.get("collision_pairs")
    if not isinstance(backup_pairs, list) or any(
        not isinstance(pair, list)
        or len(pair) != 2
        or _suffix_alias(str(pair[1])) != str(pair[0])
        for pair in backup_pairs
    ):
        raise SafetyError("backup_target_mismatch", "备份中的动态碰撞目标无效")
    return document


def _connect() -> Any:
    try:
        import pymysql
    except ImportError as exc:
        raise SafetyError(
            "driver_missing",
            "缺少 pymysql，请先安装 htmlsystm/requirements.txt",
        ) from exc
    password = os.getenv("MYSQL_PASSWORD", "")
    if not password:
        raise SafetyError("mysql_password_missing", "未设置 MYSQL_PASSWORD")
    try:
        return pymysql.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "htmlsystm_user"),
            password=password,
            database=os.getenv("MYSQL_DATABASE", "htmlsystm"),
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=30,
            write_timeout=30,
        )
    except Exception as exc:
        raise SafetyError("database_connection_failed", f"MySQL 连接失败: {exc}") from exc


def _read_state(
    connection: Any, *, for_update: bool = False
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    with connection.cursor() as cursor:
        libraries = _fetch_libraries(cursor, for_update=for_update)
        users = _fetch_users(cursor, for_update=for_update)
    return libraries, users


def _insert_audit(
    cursor: Any,
    *,
    action: str,
    library_id: str,
    library_name: str,
    detail: Mapping[str, Any],
) -> None:
    cursor.execute(
        """
        INSERT INTO material_db_audit
        (user_id, user_display, action, library_id, library_name, detail)
        VALUES (NULL, %s, %s, %s, %s, %s)
        """,
        (
            "系统物料库去重",
            action,
            library_id,
            library_name,
            json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
        ),
    )


def inspect_cleanup(
    connection: Any,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    libraries, users = _read_state(connection)
    connection.rollback()
    return build_cleanup_plan(libraries, users), libraries, users


def apply_cleanup(
    connection: Any,
    *,
    expected_digest: str,
    backup_file: Optional[Path],
) -> Dict[str, Any]:
    initial_plan, initial_libraries, initial_users = inspect_cleanup(connection)
    if not initial_plan["safe"]:
        raise SafetyError(
            "unsafe_plan",
            "清理前置校验失败",
            _public_plan(initial_plan)["errors"],
        )
    if not expected_digest:
        raise SafetyError(
            "expected_digest_required",
            "--apply 必须同时提供 dry-run 输出的 --expected-plan-digest",
        )
    if expected_digest != initial_plan["plan_digest"]:
        raise SafetyError(
            "plan_digest_mismatch",
            "数据库状态与 dry-run 指纹不一致，请重新 dry-run",
            {
                "expected": expected_digest,
                "actual": initial_plan["plan_digest"],
            },
        )
    if initial_plan["pending_delete_count"] == 0:
        return {
            "mode": "apply_cleanup",
            "ok": True,
            "plan_digest": expected_digest,
            "no_changes": True,
            "backup_file": None,
            "deleted_count": 0,
            "history_versions_copied": 0,
            "deleted": [],
            "yida_sync_called": False,
        }

    affected_names = [
        name for pair in initial_plan["collision_pairs"] for name in pair
    ]
    affected_name_set = set(affected_names)
    affected_ids = [
        str(row["id"])
        for row in initial_libraries
        if row.get("name") in affected_name_set
    ]
    with connection.cursor() as cursor:
        audit_rows = _fetch_backup_audit(cursor, affected_ids, affected_names)
    connection.rollback()
    backup_document = _backup_document(
        kind="material-library-dedupe-cleanup",
        plan=initial_plan,
        library_rows=initial_libraries,
        users=initial_users,
        audit_rows=audit_rows,
    )
    backup_path = backup_file or _default_backup_path(
        "material-library-dedupe-cleanup", initial_plan["plan_digest"]
    )
    written_backup = _write_json_backup(backup_document, backup_path)

    try:
        locked_libraries, locked_users = _read_state(connection, for_update=True)
        locked_plan = build_cleanup_plan(locked_libraries, locked_users)
        if not locked_plan["safe"] or locked_plan["plan_digest"] != expected_digest:
            raise SafetyError(
                "locked_plan_changed",
                "写入备份后目标发生变化，事务已回滚；请重新 dry-run",
                {
                    "expected": expected_digest,
                    "actual": locked_plan["plan_digest"],
                    "errors": _public_plan(locked_plan)["errors"],
                },
            )

        deleted: List[Dict[str, Any]] = []
        with connection.cursor() as cursor:
            for pair in locked_plan["pairs"]:
                if pair.get("status") != "pending_delete":
                    continue
                cursor.execute(
                    """
                    UPDATE material_db_libraries
                    SET history_tables_json = %s, updated_at = NOW()
                    WHERE id = %s AND name = %s
                    """,
                    (
                        json.dumps(
                            pair["_merged_history"],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        pair["retained_id"],
                        pair["retained_name"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise SafetyError(
                        "retained_update_failed",
                        f"更新保留库失败: {pair['retained_name']}",
                    )
                cursor.execute(
                    "DELETE FROM material_db_libraries WHERE id = %s AND name = %s",
                    (pair["legacy_id"], pair["legacy_name"]),
                )
                if cursor.rowcount != 1:
                    raise SafetyError(
                        "legacy_delete_failed",
                        f"删除旧库失败: {pair['legacy_name']}",
                    )
                detail = {
                    "source": "material_library_dedupe.py",
                    "retained_library_id": pair["retained_id"],
                    "retained_library_name": pair["retained_name"],
                    "copied_history_count": pair["copied_history_count"],
                    "backup_integrity_sha256": backup_document["integrity"]["sha256"],
                }
                _insert_audit(
                    cursor,
                    action="delete_library",
                    library_id=pair["legacy_id"],
                    library_name=pair["legacy_name"],
                    detail=detail,
                )
                deleted.append(
                    {
                        "legacy_name": pair["legacy_name"],
                        "legacy_id": pair["legacy_id"],
                        "retained_name": pair["retained_name"],
                        "retained_id": pair["retained_id"],
                        "copied_history_count": pair["copied_history_count"],
                    }
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "mode": "apply_cleanup",
        "ok": True,
        "plan_digest": expected_digest,
        "backup_file": str(written_backup),
        "backup_integrity_sha256": backup_document["integrity"]["sha256"],
        "deleted_count": len(deleted),
        "history_versions_copied": sum(
            item["copied_history_count"] for item in deleted
        ),
        "deleted": deleted,
        "yida_sync_called": False,
    }


def _restore_state_rows(document: Mapping[str, Any]) -> List[Dict[str, Any]]:
    snapshot = document.get("snapshot")
    if not isinstance(snapshot, dict):
        raise SafetyError("invalid_backup", "备份缺少 snapshot")
    rows = snapshot.get("material_db_libraries")
    if not isinstance(rows, list) or not rows:
        raise SafetyError("invalid_backup", "备份没有物料库快照")
    backup_pairs = document.get("collision_pairs") or []
    allowed_names = {name for pair in backup_pairs for name in pair}
    output = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SafetyError("invalid_backup", f"物料库快照第 {index + 1} 项无效")
        missing = [column for column in LIBRARY_COLUMNS if column not in row]
        if missing:
            raise SafetyError(
                "invalid_backup",
                f"物料库快照第 {index + 1} 项缺少字段",
                missing,
            )
        if row.get("name") not in allowed_names:
            raise SafetyError(
                "backup_target_mismatch",
                f"备份包含非确认目标: {row.get('name')}",
            )
        output.append(dict(row))
    return output


def build_restore_plan(
    document: Mapping[str, Any],
    current_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    snapshot_rows = _restore_state_rows(document)
    by_name = _index_unique_names(current_rows)
    errors: List[Dict[str, Any]] = []
    expected_post = document.get("expected_post_apply")
    if not isinstance(expected_post, list):
        raise SafetyError("invalid_backup", "备份缺少 expected_post_apply")

    checks = []
    for item in expected_post:
        if not isinstance(item, dict):
            raise SafetyError("invalid_backup", "expected_post_apply 项无效")
        legacy_name = item.get("legacy_name")
        retained_name = item.get("retained_name")
        legacy = by_name.get(str(legacy_name))
        retained = by_name.get(str(retained_name))
        check = {
            "legacy_name": legacy_name,
            "retained_name": retained_name,
            "legacy_absent": legacy is None,
            "retained_present": retained is not None,
        }
        if legacy is not None:
            errors.append(
                {
                    "code": "legacy_already_present",
                    "message": f"{legacy_name} 已存在，拒绝覆盖恢复",
                }
            )
        if retained is None:
            errors.append(
                {
                    "code": "retained_missing",
                    "message": f"{retained_name} 不存在，无法安全恢复",
                }
            )
        elif (
            _logical_library_fingerprint(retained)
            != item.get("retained_logical_fingerprint")
        ):
            errors.append(
                {
                    "code": "retained_changed_after_cleanup",
                    "message": f"{retained_name} 清理后已变化，拒绝回滚覆盖新数据",
                }
            )
        checks.append(check)

    digest_input = {
        "backup_integrity_sha256": document["integrity"]["sha256"],
        "current_rows": [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "fingerprint": _raw_library_fingerprint(row),
            }
            for row in sorted(
                current_rows,
                key=lambda row: (str(row.get("name") or ""), str(row.get("id") or "")),
            )
        ],
        "checks": checks,
    }
    return {
        "safe": not errors,
        "plan_digest": _digest(digest_input),
        "errors": errors,
        "checks": checks,
        "restore_library_count": len(snapshot_rows),
        "_snapshot_rows": snapshot_rows,
    }


def inspect_restore(
    connection: Any, document: Mapping[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows, users = _read_state(connection)
    connection.rollback()
    return build_restore_plan(document, rows), rows, users


def apply_restore(
    connection: Any,
    *,
    document: Mapping[str, Any],
    expected_digest: str,
    backup_file: Optional[Path],
) -> Dict[str, Any]:
    restore_plan, current_rows, users = inspect_restore(connection, document)
    if not restore_plan["safe"]:
        raise SafetyError("unsafe_restore", "恢复前置校验失败", restore_plan["errors"])
    if not expected_digest:
        raise SafetyError(
            "expected_digest_required",
            "恢复 --apply 必须提供恢复预演输出的 --expected-plan-digest",
        )
    if expected_digest != restore_plan["plan_digest"]:
        raise SafetyError(
            "plan_digest_mismatch",
            "数据库状态与恢复预演指纹不一致，请重新预演",
            {"expected": expected_digest, "actual": restore_plan["plan_digest"]},
        )

    # A pre-restore backup protects the current cleaned state.  It is not a
    # cleanup-format restore source, but is complete enough for manual recovery.
    with connection.cursor() as cursor:
        affected_names = [
            name
            for pair in (document.get("collision_pairs") or [])
            for name in pair
        ]
        affected_name_set = set(affected_names)
        affected_ids = [
            str(row["id"])
            for row in current_rows
            if row.get("name") in affected_name_set
        ]
        audit_rows = _fetch_backup_audit(cursor, affected_ids, affected_names)
    connection.rollback()
    pre_restore_document: Dict[str, Any] = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "script_version": SCRIPT_VERSION,
        "kind": "material-library-dedupe-pre-restore",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "restore_plan_digest": restore_plan["plan_digest"],
        "confirmed_type_suffixes": list(CONFIRMED_TYPE_SUFFIXES),
        "collision_pairs": document.get("collision_pairs") or [],
        "required_restored_library": REQUIRED_RESTORED_LIBRARY,
        "snapshot": {
            "material_db_libraries": [
                {column: row.get(column) for column in LIBRARY_COLUMNS}
                for row in current_rows
                if row.get("name")
                in {
                    name
                    for pair in (document.get("collision_pairs") or [])
                    for name in pair
                }
            ],
            "material_db_audit": [
                {column: row.get(column) for column in AUDIT_COLUMNS}
                for row in audit_rows
            ],
            "users_library_roles": [
                {
                    "id": row.get("id"),
                    "username": row.get("username"),
                    "library_roles": row.get("library_roles"),
                }
                for row in users
                if row.get("library_roles") not in (None, "")
            ],
        },
        "source_backup_integrity_sha256": document["integrity"]["sha256"],
    }
    pre_restore_document["integrity"] = {
        "algorithm": "sha256",
        "sha256": _digest(pre_restore_document),
    }
    path = backup_file or _default_backup_path(
        "material-library-dedupe-pre-restore", restore_plan["plan_digest"]
    )
    written_backup = _write_json_backup(pre_restore_document, path)

    try:
        locked_rows, _ = _read_state(connection, for_update=True)
        locked_plan = build_restore_plan(document, locked_rows)
        if not locked_plan["safe"] or locked_plan["plan_digest"] != expected_digest:
            raise SafetyError(
                "locked_plan_changed",
                "写入恢复前备份后目标发生变化，事务已回滚；请重新预演",
                {
                    "expected": expected_digest,
                    "actual": locked_plan["plan_digest"],
                    "errors": locked_plan["errors"],
                },
            )
        with connection.cursor() as cursor:
            for row in locked_plan["_snapshot_rows"]:
                placeholders = ",".join(["%s"] * len(LIBRARY_COLUMNS))
                assignments = ",".join(
                    f"{column}=VALUES({column})" for column in LIBRARY_COLUMNS[1:]
                )
                cursor.execute(
                    f"INSERT INTO material_db_libraries "
                    f"({', '.join(LIBRARY_COLUMNS)}) VALUES ({placeholders}) "
                    f"ON DUPLICATE KEY UPDATE {assignments}",
                    tuple(row[column] for column in LIBRARY_COLUMNS),
                )
                _insert_audit(
                    cursor,
                    action="update_library",
                    library_id=str(row["id"]),
                    library_name=str(row["name"]),
                    detail={
                        "source": "material_library_dedupe.py restore",
                        "source_backup_integrity_sha256": document["integrity"]["sha256"],
                    },
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return {
        "mode": "apply_restore",
        "ok": True,
        "plan_digest": expected_digest,
        "pre_restore_backup_file": str(written_backup),
        "pre_restore_backup_integrity_sha256": pre_restore_document["integrity"]["sha256"],
        "source_backup_integrity_sha256": document["integrity"]["sha256"],
        "restored_library_count": locked_plan["restore_library_count"],
        "yida_sync_called": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="安全合并并删除已确认的无后缀重复物料库（默认只读预演）"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行变更；必须同时提供 --expected-plan-digest",
    )
    parser.add_argument(
        "--expected-plan-digest",
        default="",
        help="前一次 dry-run/恢复预演输出的 plan_digest",
    )
    parser.add_argument(
        "--backup-file",
        type=Path,
        help="执行前 JSON 备份路径；默认写入 data/material_library_dedupe_backups",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        help="从本脚本生成的 cleanup JSON 备份预演/恢复",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    connection = None
    try:
        connection = _connect()
        if args.restore:
            document = _load_backup(args.restore.expanduser().resolve())
            if document.get("kind") != "material-library-dedupe-cleanup":
                raise SafetyError(
                    "invalid_restore_backup",
                    "仅 cleanup 备份可用于自动恢复",
                )
            if args.apply:
                result = apply_restore(
                    connection,
                    document=document,
                    expected_digest=args.expected_plan_digest,
                    backup_file=args.backup_file,
                )
            else:
                plan, _, _ = inspect_restore(connection, document)
                result = {
                    "mode": "dry_run_restore",
                    "ok": bool(plan["safe"]),
                    "apply_required": True,
                    "plan_digest": plan["plan_digest"],
                    "restore_library_count": plan["restore_library_count"],
                    "checks": plan["checks"],
                    "errors": plan["errors"],
                    "source_backup_integrity_sha256": document["integrity"]["sha256"],
                    "yida_sync_called": False,
                }
        elif args.apply:
            result = apply_cleanup(
                connection,
                expected_digest=args.expected_plan_digest,
                backup_file=args.backup_file,
            )
        else:
            plan, _, _ = inspect_cleanup(connection)
            result = {
                "mode": "dry_run_cleanup",
                "ok": bool(plan["safe"]),
                "apply_required": True,
                **_public_plan(plan),
                "yida_sync_called": False,
            }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        return 0 if result.get("ok") else 2
    except SafetyError as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": exc.code,
                        "message": exc.message,
                        "details": exc.details,
                    },
                    "yida_sync_called": False,
                },
                ensure_ascii=False,
                indent=2,
                default=_json_default,
            )
        )
        return 2
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    sys.exit(main())
