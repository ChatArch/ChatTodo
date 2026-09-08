"""Validated task forests and an owner-isolated persistent board API.

All public payloads are plain JSON-compatible dictionaries. Pure functions never
mutate caller-owned input. See the Python interface documentation for limits.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any
from uuid import uuid4

__all__ = ["BoardError", "BoardStore", "validate_nodes", "apply_operations"]

MAX_NODES = 2000
MAX_DEPTH = 64
MAX_OPERATIONS = 50
MAX_BODY_BYTES = 128 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_NODE_FIELDS = {"id", "parent_id", "title", "status", "body", "order"}
_EDIT_FIELDS = {"title", "status", "body", "order"}
_STATUSES = {"pending", "in_progress", "completed", "cancelled"}


class BoardError(Exception):
    """An adapter-safe domain failure with an HTTP-compatible status."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _invalid(message: str) -> None:
    raise BoardError("invalid_input", message)


def _limit(message: str) -> None:
    raise BoardError("limit_exceeded", message, 413)


def _object(value: Any, allowed: set[str], required: set[str]) -> dict:
    if type(value) is not dict:
        _invalid("Expected an object.")
    if not required <= value.keys() or not value.keys() <= allowed:
        _invalid("Missing required fields or unknown fields.")
    return value


def _identifier(value: Any) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        _invalid("IDs must be 1–128 ASCII letters, digits, underscores or hyphens, starting with a letter or digit.")
    return value


def _text(value: Any, label: str, max_length: int | None = None) -> str:
    if type(value) is not str:
        _invalid(f"{label} must be a string.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _invalid(f"{label} must be valid Unicode.")
    if max_length is not None and (not value.strip() or len(value) > max_length):
        _invalid(f"{label} must be nonblank and at most {max_length} characters.")
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        _invalid("Confirmation must be a boolean.")
    return value


def _node(value: Any) -> dict:
    value = _object(value, _NODE_FIELDS, {"id", "title"})
    identifier = _identifier(value["id"])
    parent = value.get("parent_id")
    if parent is not None:
        parent = _identifier(parent)
    title = _text(value["title"], "Title", 200)
    status = value.get("status", "pending")
    if type(status) is not str or status not in _STATUSES:
        _invalid("Unknown node status.")
    body = _text(value.get("body", ""), "Body")
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        _limit("Node body exceeds 128 KiB of UTF-8.")
    order = value.get("order", 0)
    if type(order) is not int or order < 0:
        _invalid("Order must be a nonnegative integer.")
    return dict(id=identifier, parent_id=parent, title=title, status=status, body=body, order=order)


def validate_nodes(nodes: list[dict]) -> list[dict]:
    """Return detached, normalized nodes after validating the entire forest.

    Only id/title are required. Root depth is one; list order is preserved.
    Empty forests are valid. Cycles are checked in *every* component.
    """
    if type(nodes) is not list:
        _invalid("Nodes must be an array.")
    if len(nodes) > MAX_NODES:
        _limit("A board can contain at most 2000 nodes.")
    result = [_node(n) for n in nodes]
    index = {n["id"]: n for n in result}
    if len(index) != len(result):
        _invalid("Duplicate node ID.")
    for n in result:
        if n["parent_id"] is not None and n["parent_id"] not in index:
            _invalid("Node parent does not exist.")
        if n["parent_id"] == n["id"]:
            _invalid("A node cannot be its own parent.")
    depths: dict[str, int] = {}
    for identifier in index:
        trail: list[str] = []
        seen: set[str] = set()
        current = identifier
        while current is not None and current not in depths:
            if current in seen:
                _invalid("Task forest contains a cycle.")
            seen.add(current)
            trail.append(current)
            current = index[current]["parent_id"]
        depth = depths.get(current, 0)
        for current in reversed(trail):
            depth += 1
            if depth > MAX_DEPTH:
                _limit("Task forest exceeds 64 levels.")
            depths[current] = depth
    return result


def _counts(before: list[dict], after: list[dict]) -> dict[str, int]:
    old = {n["id"]: n for n in before}
    new = {n["id"]: n for n in after}
    return {
        "created": len(new.keys() - old.keys()),
        "updated": sum(old[key] != new[key] for key in old.keys() & new.keys()),
        "deleted": len(old.keys() - new.keys()),
    }


def apply_operations(
    nodes: list[dict], operations: list[dict], *, confirm_destructive: bool = False,
) -> tuple[list[dict], dict[str, int]]:
    """Apply up to 50 operations atomically to a detached copy of a forest.

    Operations execute in order. A create may refer to a parent created later in
    the same batch; structural validation occurs after the entire batch. Delete
    removes a branch and requires an explicit boolean confirmation.
    """
    _boolean(confirm_destructive)
    if type(operations) is not list:
        _invalid("Operations must be an array.")
    if len(operations) > MAX_OPERATIONS:
        _limit("A batch can contain at most 50 operations.")
    before = validate_nodes(nodes)
    working = {n["id"]: dict(n) for n in before}
    for operation in operations:
        if type(operation) is not dict or type(operation.get("op")) is not str:
            _invalid("An operation requires an op string.")
        op = operation["op"]
        if op == "create":
            _object(operation, {"op", "node"}, {"op", "node"})
            new = _node(operation["node"])
            if new["id"] in working:
                _invalid("Node ID already exists.")
            working[new["id"]] = new
            continue
        shapes = {
            "update": {"op", "id", "fields"},
            "move": {"op", "id", "parent_id", "order"},
            "delete": {"op", "id"},
        }
        if op not in shapes:
            _invalid("Unknown operation.")
        _object(operation, shapes[op], shapes[op])
        identifier = _identifier(operation["id"])
        if identifier not in working:
            _invalid("Operation target does not exist.")
        if op == "update":
            fields = _object(operation["fields"], _EDIT_FIELDS, set())
            working[identifier] = _node({**working[identifier], **fields})
        elif op == "move":
            working[identifier] = _node({
                **working[identifier], "parent_id": operation["parent_id"], "order": operation["order"],
            })
        else:
            if not confirm_destructive:
                raise BoardError("confirmation_required", "Branch deletion requires confirmation.")
            children: dict[str | None, list[str]] = {}
            for n in working.values():
                children.setdefault(n["parent_id"], []).append(n["id"])
            pending = [identifier]
            removed = set()
            while pending:
                current = pending.pop()
                if current not in removed:
                    removed.add(current)
                    pending.extend(children.get(current, []))
            for current in removed:
                del working[current]
    result = validate_nodes(list(working.values()))
    return result, _counts(before, result)


# Audit/receipt retention is independent of active undo snapshots. Pruning an
# audit event must never invalidate an edit that can still be undone.
RETENTION_LIMIT = 1000
MAX_COORDINATE = 1_000_000
_SIDECARS = ("", "-journal", "-wal", "-shm")
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS boards (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
        revision INTEGER NOT NULL, nodes TEXT NOT NULL, view TEXT NOT NULL,
        view_revision INTEGER NOT NULL, updated_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS boards_owner ON boards(owner, updated_at)",
    """CREATE TABLE IF NOT EXISTS changes (
        id TEXT PRIMARY KEY, board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, actor TEXT NOT NULL, summary TEXT NOT NULL,
        counts TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(board_id, revision))""",
    """CREATE TABLE IF NOT EXISTS undo_stack (
        board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
        revision INTEGER NOT NULL, nodes TEXT NOT NULL, PRIMARY KEY(board_id, revision))""",
    """CREATE TABLE IF NOT EXISTS requests (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        board_id TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
        request_id TEXT NOT NULL, input_hash TEXT NOT NULL, receipt TEXT NOT NULL,
        UNIQUE(board_id, request_id))""",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        _invalid("Payload must be finite JSON data.")


def _json_input(value: Any) -> None:
    """Reject Python-only shapes before hashing (e.g. tuples are not arrays)."""
    if type(value) is dict:
        for key, child in value.items():
            _text(key, "Object key")
            _json_input(child)
    elif type(value) is list:
        for child in value:
            _json_input(child)
    elif type(value) is str:
        _text(value, "Value")
    elif value is not None and type(value) not in (bool, int, float):
        _invalid("Payload must be JSON data.")


def _revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        _invalid("Revision must be a nonnegative integer.")
    return value


def _number(value: Any, low: float, high: float) -> int | float:
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        _invalid("View numbers must be finite and within the allowed range.")
    return value


def _point(value: Any) -> dict:
    value = _object(value, {"x", "y"}, {"x", "y"})
    return {key: _number(value[key], -MAX_COORDINATE, MAX_COORDINATE) for key in ("x", "y")}


def _view(value: Any, nodes: list[dict]) -> dict:
    value = _object(value, {"pan", "zoom", "positions", "collapsed"}, set())
    positions = value.get("positions", {})
    collapsed = value.get("collapsed", [])
    if type(positions) is not dict or type(collapsed) is not list:
        _invalid("Positions must be an object and collapsed must be an array.")
    if len(positions) > MAX_NODES or len(collapsed) > MAX_NODES:
        _limit("View exceeds the board node limit.")
    # Validate even unknown IDs/positions before discarding stale node entries.
    positions = {_identifier(key): _point(point) for key, point in positions.items()}
    collapsed = list(dict.fromkeys(_identifier(key) for key in collapsed))
    identifiers = {node["id"] for node in nodes}
    return {
        "pan": _point(value.get("pan", {"x": 0, "y": 0})),
        "zoom": _number(value.get("zoom", 1), 0.2, 2.5),
        "positions": {key: point for key, point in positions.items() if key in identifiers},
        "collapsed": [key for key in collapsed if key in identifiers],
    }


def _unsafe() -> None:
    raise BoardError("unsafe_storage", "Board storage must use private, regular, unlinked files and real directories.")


class BoardStore:
    """Owner-scoped SQLite boards; every call owns one immediate transaction.

    Use a dedicated private directory. Existing empty files are accepted only at
    construction; non-SQLite files, links and special files are never adopted.
    Audit events and idempotency receipts retain the latest 1000 entries per
    board. Active undo snapshots are separate and survive audit pruning.
    """

    def __init__(self, path: str | os.PathLike):
        try:
            raw = os.fsdecode(os.fspath(path))
            if not raw or "\x00" in raw or ".." in Path(raw).parts:
                _unsafe()
            self.path = Path(os.path.abspath(os.path.expanduser(raw)))
            if not self.path.name:
                _unsafe()
        except (TypeError, ValueError):
            _unsafe()
        with self._transaction(initialize=True) as connection:
            for statement in _SCHEMA:
                connection.execute(statement)

    def _parent_fd(self, create: bool = False) -> int:
        # Walk from / with O_NOFOLLOW rather than resolve(), which would hide a
        # symlink ancestor. dir_fd also prevents chmod/open following a swap.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(self.path.anchor, flags)
        try:
            for part in self.path.parent.parts[1:]:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _regular(metadata: os.stat_result) -> None:
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != os.geteuid():
            _unsafe()

    def _file_stats(self, parent: int) -> dict:
        found = {}
        for suffix in _SIDECARS:
            name = self.path.name + suffix
            try:
                metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            self._regular(metadata)
            found[name] = metadata
        return found

    def _prepare_files(self, parent: int, initialize: bool) -> int:
        # Inspect *all* names before changing any permissions, including an
        # existing journal symlink next to a not-yet-created database.
        self._file_stats(parent)
        descriptors = []
        try:
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
            if initialize:
                try:
                    database = os.open(self.path.name, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
                except FileExistsError:
                    database = os.open(self.path.name, flags, dir_fd=parent)
            else:
                database = os.open(self.path.name, flags, dir_fd=parent)
            descriptors.append(database)
            self._regular(os.fstat(database))
            header = os.pread(database, 16, 0)
            if header != b"SQLite format 3\x00" and not (initialize and os.fstat(database).st_size == 0):
                _unsafe()
            for suffix in _SIDECARS[1:]:
                try:
                    descriptor = os.open(self.path.name + suffix, flags, dir_fd=parent)
                except FileNotFoundError:  # SQLite can remove a journal concurrently.
                    continue
                descriptors.append(descriptor)
                self._regular(os.fstat(descriptor))
            os.fchmod(parent, 0o700)
            for descriptor in descriptors:
                os.fchmod(descriptor, 0o600)
            for descriptor in descriptors[1:]:
                os.close(descriptor)
            return database
        except BaseException:
            for descriptor in descriptors:
                os.close(descriptor)
            raise

    def _check_identity(self, parent: int, database: int) -> None:
        current = self._parent_fd()
        try:
            original = os.fstat(parent)
            actual = os.fstat(current)
            if (original.st_dev, original.st_ino) != (actual.st_dev, actual.st_ino):
                _unsafe()
            files = self._file_stats(current)
            original = os.fstat(database)
            actual = files.get(self.path.name)
            if actual is None or (original.st_dev, original.st_ino) != (actual.st_dev, actual.st_ino):
                _unsafe()
        finally:
            os.close(current)

    @contextmanager
    def _transaction(self, initialize: bool = False):
        parent = database = None
        connection = None
        try:
            parent = self._parent_fd(create=initialize)
            database = self._prepare_files(parent, initialize)
            self._check_identity(parent, database)
            # mode=rw: only _prepare_files may create a DB; sqlite must not
            # silently recreate it if a pathname disappears during an operation.
            connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=30, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            self._check_identity(parent, database)
            yield connection
            self._check_identity(parent, database)
            connection.commit()
        except OSError as error:
            raise BoardError("unsafe_storage", "Cannot safely access board storage.") from error
        except sqlite3.DatabaseError as error:
            if getattr(error, "sqlite_errorcode", None) in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
                raise BoardError("unsafe_storage", "Board storage is not a valid SQLite database.") from error
            raise BoardError("storage_unavailable", "Board storage is unavailable.", 503) from error
        finally:
            if connection is not None:
                try:
                    if connection.in_transaction:
                        connection.rollback()
                finally:
                    connection.close()
            if database is not None:
                os.close(database)
            if parent is not None:
                os.close(parent)

    @staticmethod
    def _board(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "title": row["title"], "revision": row["revision"],
            "nodes": json.loads(row["nodes"]), "view": json.loads(row["view"]),
            "view_revision": row["view_revision"], "updated_at": row["updated_at"],
        }

    def _get(self, connection, board_id: str, owner: str) -> dict:
        _text(owner, "Owner", 256)
        _identifier(board_id)
        row = connection.execute("SELECT * FROM boards WHERE id=? AND owner=?", (board_id, owner)).fetchone()
        if row is None:
            raise BoardError("not_found", "Board not found.", 404)
        return self._board(row)

    def create(self, owner: str, title: str = "我的任务树", nodes: list[dict] | None = None) -> dict:
        with self._transaction() as connection:
            _text(owner, "Owner", 256)
            _text(title, "Title", 200)
            nodes = validate_nodes([{"id": uuid4().hex, "title": "总目标"}] if nodes is None else nodes)
            board = dict(id=uuid4().hex, title=title, revision=0, nodes=nodes,
                         view=_view({}, nodes), view_revision=0, updated_at=_now())
            connection.execute("INSERT INTO boards VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                board["id"], owner, title, 0, _json(nodes), _json(board["view"]), 0, board["updated_at"],
            ))
            return board

    def list(self, owner: str) -> list[dict]:
        with self._transaction() as connection:
            _text(owner, "Owner", 256)
            rows = connection.execute(
                "SELECT id,title,revision,updated_at FROM boards WHERE owner=? ORDER BY updated_at DESC,id", (owner,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get(self, board_id: str, owner: str) -> dict:
        with self._transaction() as connection:
            return self._get(connection, board_id, owner)

    @staticmethod
    def _check_revision(board: dict, revision: int) -> None:
        if _revision(revision) != board["revision"]:
            raise BoardError("revision_conflict", "Board changed; reload before retrying.", 409)

    @staticmethod
    def _request(connection, board: dict, revision: int, request_id: str, *, method: str,
                 actor: str = "user", confirm: bool = False, operations: Any = None) -> tuple[str, dict | None]:
        _revision(revision)
        _identifier(request_id)
        _text(actor, "Actor", 64)
        _boolean(confirm)
        try:
            _json_input(operations)
        except RecursionError:
            _invalid("Payload is nested too deeply.")
        payload = dict(method=method, revision=revision, actor=actor, confirm=confirm, operations=operations)
        fingerprint = hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
        previous = connection.execute(
            "SELECT input_hash,receipt FROM requests WHERE board_id=? AND request_id=?", (board["id"], request_id),
        ).fetchone()
        if previous is not None:
            if previous["input_hash"] != fingerprint:
                raise BoardError("idempotency_conflict", "Request ID is already bound to different input.", 409)
            return fingerprint, json.loads(previous["receipt"])
        return fingerprint, None

    @staticmethod
    def _receipt(connection, board: dict, request_id: str, fingerprint: str, change: dict | None) -> dict:
        result = {"board": board, "change": change}
        connection.execute("INSERT INTO requests(board_id,request_id,input_hash,receipt) VALUES (?,?,?,?)",
                           (board["id"], request_id, fingerprint, _json(result)))
        connection.execute("""DELETE FROM requests WHERE board_id=? AND sequence NOT IN (
            SELECT sequence FROM requests WHERE board_id=? ORDER BY sequence DESC LIMIT ?)""",
                           (board["id"], board["id"], RETENTION_LIMIT))
        return result

    @staticmethod
    def _change(connection, board: dict, nodes: list[dict], actor: str, *, undo: bool = False) -> dict:
        counts = _counts(board["nodes"], nodes)
        board["nodes"] = nodes
        board["revision"] += 1
        board["updated_at"] = _now()
        view = _view(board["view"], nodes)
        if view != board["view"]:
            board["view"] = view
            board["view_revision"] += 1
        summary = ("撤销；" if undo else "") + "新增 {created}、更新 {updated}、删除 {deleted} 个节点".format(**counts)
        change = dict(id=uuid4().hex, revision=board["revision"], actor=actor, summary=summary,
                      counts=counts, created_at=board["updated_at"])
        connection.execute("""UPDATE boards SET revision=?,nodes=?,view=?,view_revision=?,updated_at=? WHERE id=?""",
                           (board["revision"], _json(nodes), _json(board["view"]), board["view_revision"],
                            board["updated_at"], board["id"]))
        connection.execute("INSERT INTO changes VALUES (?,?,?,?,?,?,?)",
                           (change["id"], board["id"], change["revision"], actor, summary, _json(counts), change["created_at"]))
        connection.execute("""DELETE FROM changes WHERE board_id=? AND revision NOT IN (
            SELECT revision FROM changes WHERE board_id=? ORDER BY revision DESC LIMIT ?)""",
                           (board["id"], board["id"], RETENTION_LIMIT))
        return change

    def mutate(self, board_id: str, owner: str, revision: int, request_id: str, operations: list[dict], *,
               actor: str = "user", confirm_destructive: bool = False) -> dict:
        with self._transaction() as connection:
            board = self._get(connection, board_id, owner)
            fingerprint, replay = self._request(connection, board, revision, request_id, method="mutate",
                                                actor=actor, confirm=confirm_destructive, operations=operations)
            if replay is not None:
                return replay
            self._check_revision(board, revision)
            nodes, counts = apply_operations(board["nodes"], operations, confirm_destructive=confirm_destructive)
            change = None
            if any(counts.values()):
                connection.execute("INSERT INTO undo_stack VALUES (?,?,?)", (board_id, revision, _json(board["nodes"])))
                change = self._change(connection, board, nodes, actor)
            return self._receipt(connection, board, request_id, fingerprint, change)

    def undo(self, board_id: str, owner: str, revision: int, request_id: str) -> dict:
        with self._transaction() as connection:
            board = self._get(connection, board_id, owner)
            fingerprint, replay = self._request(connection, board, revision, request_id, method="undo")
            if replay is not None:
                return replay
            self._check_revision(board, revision)
            target = connection.execute("SELECT revision,nodes FROM undo_stack WHERE board_id=? ORDER BY revision DESC LIMIT 1",
                                        (board_id,)).fetchone()
            if target is None:
                raise BoardError("nothing_to_undo", "No earlier edit to undo.", 409)
            # Pop an edit snapshot; never push the undo itself (which oscillates).
            connection.execute("DELETE FROM undo_stack WHERE board_id=? AND revision=?", (board_id, target["revision"]))
            change = self._change(connection, board, json.loads(target["nodes"]), "user", undo=True)
            return self._receipt(connection, board, request_id, fingerprint, change)

    def save_view(self, board_id: str, owner: str, view: dict, view_revision: int | None = None) -> dict:
        """Save presentation state, optionally using its independent CAS revision.

        ``view_revision`` stays optional for older direct Python callers.
        Concurrent client adapters should always provide it.
        """
        with self._transaction() as connection:
            board = self._get(connection, board_id, owner)
            if view_revision is not None and _revision(view_revision) != board["view_revision"]:
                raise BoardError("view_revision_conflict",
                                 "Board view changed; reload it before explicitly retrying.", 409)
            view = _view(view, board["nodes"])
            if view != board["view"]:
                board["view_revision"] += 1
                connection.execute("UPDATE boards SET view=?,view_revision=? WHERE id=?",
                                   (_json(view), board["view_revision"], board_id))
            return {"view": view, "view_revision": board["view_revision"]}

    def history(self, board_id: str, owner: str) -> list[dict]:
        with self._transaction() as connection:
            self._get(connection, board_id, owner)
            rows = connection.execute("SELECT id,revision,actor,summary,counts,created_at FROM changes WHERE board_id=? ORDER BY revision DESC",
                                      (board_id,)).fetchall()
            return [{**dict(row), "counts": json.loads(row["counts"])} for row in rows]

    def delete(self, board_id: str, owner: str, revision: int, *, confirm: bool = False) -> None:
        with self._transaction() as connection:
            board = self._get(connection, board_id, owner)
            _boolean(confirm)
            self._check_revision(board, revision)
            if not confirm:
                raise BoardError("confirmation_required", "Board deletion requires confirmation.")
            connection.execute("DELETE FROM boards WHERE id=?", (board_id,))
