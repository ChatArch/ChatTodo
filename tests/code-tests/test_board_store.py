"""SQLite integration tests: real files, transactions and thread races."""

from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import stat
from threading import Barrier

import pytest

import chattodo.board as api


def node(identifier="root", parent_id=None, **fields):
    return {"id": identifier, "parent_id": parent_id, "title": identifier, **fields}


def edit(title):
    return [{"op": "update", "id": "root", "fields": {"title": title}}]


@pytest.fixture
def store(tmp_path):
    return api.BoardStore(tmp_path / "state" / "boards.sqlite3")


def test_store_api_exists():
    assert hasattr(api, "BoardStore"), "SQLite BoardStore is missing"


def test_default_create_reopen_summary_and_detached_results(store, tmp_path):
    board = store.create("owner-a")
    assert {"id", "title", "revision", "nodes", "view", "view_revision", "updated_at"} <= board.keys()
    assert board["title"] == "我的任务树"
    assert board["revision"] == board["view_revision"] == 0
    assert len(board["nodes"]) == 1
    assert board["nodes"][0]["title"] == "总目标"
    assert board["nodes"][0]["parent_id"] is None
    assert board["view"] == {"pan": {"x": 0, "y": 0}, "zoom": 1, "positions": {}, "collapsed": []}
    assert datetime.fromisoformat(board["updated_at"]).tzinfo is not None
    reopened = api.BoardStore(tmp_path / "state" / "boards.sqlite3")
    assert reopened.get(board["id"], "owner-a") == board
    summary = reopened.list("owner-a")[0]
    assert {"id", "title", "revision", "updated_at"} <= summary.keys()
    assert "nodes" not in summary and "view" not in summary
    assert summary["id"] == board["id"]
    board["nodes"][0]["title"] = "not persisted"
    assert reopened.get(board["id"], "owner-a")["nodes"][0]["title"] == "总目标"
    assert reopened.list("owner-b") == []


def test_explicit_empty_tree_and_input_isolation(store):
    assert store.create("owner", nodes=[])["nodes"] == []
    source = [node(body="# Goal\n\nMarkdown **content**")]
    before = copy.deepcopy(source)
    board = store.create("owner", title="Project", nodes=source)
    assert board["nodes"] == api.validate_nodes(source)
    assert source == before
    source[0]["body"] = "different"
    assert store.get(board["id"], "owner")["nodes"][0]["body"] != "different"


@pytest.mark.parametrize("owner", [None, "", " ", 1, [], "x" * 257])
def test_invalid_owner(store, owner):
    with pytest.raises(api.BoardError):
        store.create(owner)
    assert store.list("owner") == []


@pytest.mark.parametrize("title", [None, "", " ", 1, "x" * 201])
def test_invalid_board_title(store, title):
    with pytest.raises(api.BoardError):
        store.create("owner", title=title)
    assert store.list("owner") == []


def test_all_board_methods_hide_other_owner_and_missing_board(store):
    board = store.create("owner", nodes=[node()])
    calls = [
        lambda identifier, owner: store.get(identifier, owner),
        lambda identifier, owner: store.mutate(identifier, owner, 0, "edit", edit("x")),
        lambda identifier, owner: store.undo(identifier, owner, 0, "undo"),
        lambda identifier, owner: store.save_view(identifier, owner, {}),
        lambda identifier, owner: store.history(identifier, owner),
        lambda identifier, owner: store.delete(identifier, owner, 0, confirm=True),
    ]
    for call in calls:
        for identifier, owner in [(board["id"], "intruder"), ("missing", "owner")]:
            with pytest.raises(api.BoardError) as caught:
                call(identifier, owner)
            assert (caught.value.code, caught.value.status) == ("not_found", 404)
    assert store.get(board["id"], "owner") == board


def test_mutate_change_receipt_and_reopen(store, tmp_path):
    board = store.create("owner", nodes=[node()])
    result = store.mutate(board["id"], "owner", 0, "request-1", edit("Updated"), actor="model")
    assert set(result) == {"board", "change"}
    assert result["board"]["revision"] == 1
    assert result["board"]["nodes"][0]["title"] == "Updated"
    change = result["change"]
    assert {"id", "revision", "actor", "summary", "counts", "created_at"} <= change.keys()
    assert change["revision"] == 1 and change["actor"] == "model"
    assert change["summary"] and change["id"]
    assert change["counts"] == {"created": 0, "updated": 1, "deleted": 0}
    assert datetime.fromisoformat(change["created_at"]).tzinfo
    assert store.history(board["id"], "owner") == [change]
    reopened = api.BoardStore(tmp_path / "state" / "boards.sqlite3")
    assert reopened.get(board["id"], "owner") == result["board"]
    assert reopened.history(board["id"], "owner") == [change]


def test_mutation_atomicity_and_retry_failed_request(store):
    board = store.create("owner", nodes=[node()])
    with pytest.raises(api.BoardError):
        store.mutate(board["id"], "owner", 0, "retry", edit("never") + [
            {"op": "create", "node": node("orphan", "missing")},
        ])
    assert store.get(board["id"], "owner") == board
    assert store.history(board["id"], "owner") == []
    assert store.mutate(board["id"], "owner", 0, "retry", edit("valid"))["board"]["revision"] == 1


def test_conflicts_and_request_id_bound_to_all_input(store):
    board = store.create("owner", nodes=[node()])
    first = store.mutate(board["id"], "owner", 0, "request", edit("first"))
    assert store.mutate(board["id"], "owner", 0, "request", edit("first")) == first
    mismatches = [
        lambda: store.mutate(board["id"], "owner", 0, "request", edit("other")),
        lambda: store.mutate(board["id"], "owner", 1, "request", edit("first")),
        lambda: store.mutate(board["id"], "owner", 0, "request", edit("first"), actor="model"),
        lambda: store.mutate(board["id"], "owner", 0, "request", edit("first"), confirm_destructive=True),
        lambda: store.undo(board["id"], "owner", 0, "request"),
    ]
    for mismatch in mismatches:
        with pytest.raises(api.BoardError) as caught:
            mismatch()
        assert caught.value.status == 409
        assert caught.value.code == "idempotency_conflict"
    with pytest.raises(api.BoardError) as caught:
        store.mutate(board["id"], "owner", 0, "stale", edit("stale"))
    assert caught.value.status == 409
    assert caught.value.code == "revision_conflict"
    store.mutate(board["id"], "owner", 1, "next", edit("second"))
    assert store.mutate(board["id"], "owner", 0, "request", edit("first")) == first
    assert store.get(board["id"], "owner")["nodes"][0]["title"] == "second"
    assert len(store.history(board["id"], "owner")) == 2


def test_request_identity_is_per_board_and_owner_cannot_replay(store):
    one = store.create("owner", nodes=[node()])
    two = store.create("owner", nodes=[node()])
    for board in [one, two]:
        store.mutate(board["id"], "owner", 0, "same-id", edit("changed"))
    with pytest.raises(api.BoardError) as caught:
        store.mutate(one["id"], "intruder", 0, "same-id", edit("changed"))
    assert caught.value.status == 404


@pytest.mark.parametrize("revision", [True, False, -1, 1.5, "0", None])
def test_revision_is_strict_integer(store, revision):
    board = store.create("owner", nodes=[node()])
    for call in [
        lambda: store.mutate(board["id"], "owner", revision, "req", edit("new")),
        lambda: store.undo(board["id"], "owner", revision, "undo"),
        lambda: store.delete(board["id"], "owner", revision, confirm=True),
    ]:
        with pytest.raises(api.BoardError) as caught:
            call()
        assert caught.value.status == 400
    assert store.get(board["id"], "owner") == board


@pytest.mark.parametrize("request_id", [None, "", "../bad", "x" * 129, True, {}])
def test_invalid_request_id_is_rejected(store, request_id):
    board = store.create("owner", nodes=[node()])
    with pytest.raises(api.BoardError):
        store.mutate(board["id"], "owner", 0, request_id, edit("changed"))
    assert store.get(board["id"], "owner") == board


@pytest.mark.parametrize("confirm", [None, "false", "true", 1, 0, [], {}])
def test_store_confirmation_is_strict_even_for_replays(store, confirm):
    board = store.create("owner", nodes=[node()])
    store.mutate(board["id"], "owner", 0, "request", edit("changed"))
    for call in [
        lambda: store.mutate(board["id"], "owner", 0, "request", edit("changed"), confirm_destructive=confirm),
        lambda: store.delete(board["id"], "owner", 1, confirm=confirm),
    ]:
        with pytest.raises(api.BoardError) as caught:
            call()
        assert caught.value.status == 400
    assert store.get(board["id"], "owner")["revision"] == 1


def test_delete_requires_confirmation_and_revision_then_cascades(store, tmp_path):
    board = store.create("owner", nodes=[node()])
    store.mutate(board["id"], "owner", 0, "edit", edit("new"))
    with pytest.raises(api.BoardError) as caught:
        store.delete(board["id"], "owner", 1)
    assert caught.value.code == "confirmation_required"
    with pytest.raises(api.BoardError) as caught:
        store.delete(board["id"], "owner", 0, confirm=True)
    assert caught.value.status == 409
    store.delete(board["id"], "owner", 1, confirm=True)
    assert store.list("owner") == []
    with pytest.raises(api.BoardError) as caught:
        store.get(board["id"], "owner")
    assert caught.value.status == 404
    with sqlite3.connect(tmp_path / "state" / "boards.sqlite3") as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_real_simultaneous_writers_only_one_wins(store):
    board = store.create("owner", nodes=[node()])
    barrier = Barrier(2)

    def write(index):
        barrier.wait(timeout=5)
        try:
            return store.mutate(board["id"], "owner", 0, f"writer-{index}", edit(str(index)))
        except api.BoardError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(write, range(2)))
    assert sum(isinstance(o, dict) for o in outcomes) == 1
    errors = [o for o in outcomes if isinstance(o, api.BoardError)]
    assert len(errors) == 1 and errors[0].status == 409
    assert store.get(board["id"], "owner")["revision"] == 1
    assert len(store.history(board["id"], "owner")) == 1


def test_concurrent_duplicate_request_returns_identical_receipt(store):
    board = store.create("owner", nodes=[node()])
    barrier = Barrier(2)

    def write(_):
        barrier.wait(timeout=5)
        return store.mutate(board["id"], "owner", 0, "same", edit("new"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    assert results[0] == results[1]
    assert len(store.history(board["id"], "owner")) == 1


def test_private_directory_database_and_reopen_permissions(tmp_path):
    parent = tmp_path / "state"
    parent.mkdir(mode=0o755)
    path = parent / "boards.sqlite3"
    path.touch(mode=0o644)
    store = api.BoardStore(path)
    store.create("owner")
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_bytes().startswith(b"SQLite format 3\x00")
    for sidecar in parent.iterdir():
        assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


@pytest.mark.parametrize("kind", ["file", "dangling", "directory", "ancestor", "hardlink", "fifo", "journal", "wal", "shm"])
def test_dangerous_files_and_symlinks_are_rejected_without_touching_target(tmp_path, kind):
    private = tmp_path / "state"
    private.mkdir(mode=0o700)
    target = tmp_path / "untouched"
    target.write_bytes(b"do not touch")
    target.chmod(0o644)
    path = private / "boards.sqlite3"
    if kind == "file":
        path.symlink_to(target)
    elif kind == "dangling":
        path.symlink_to(tmp_path / "missing")
    elif kind in ("directory", "ancestor"):
        real = tmp_path / "real"
        real.mkdir()
        alias = private / "alias"
        alias.symlink_to(real, target_is_directory=True)
        path = alias / "boards.sqlite3" if kind == "directory" else alias / "child" / "boards.sqlite3"
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        Path(str(path) + "-" + kind).symlink_to(target)
    with pytest.raises(api.BoardError) as caught:
        api.BoardStore(path)
    assert caught.value.code == "unsafe_storage"
    assert target.read_bytes() == b"do not touch"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_path_is_rechecked_for_each_operation(store, tmp_path):
    board = store.create("owner")
    path = tmp_path / "state" / "boards.sqlite3"
    original = path.with_suffix(".saved")
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(api.BoardError) as caught:
        store.get(board["id"], "owner")
    assert caught.value.code == "unsafe_storage"


def test_noop_is_receipted_without_history_or_revision(store):
    board = store.create("owner", nodes=[node()])
    operations = edit("temporary") + edit("root")
    receipt = store.mutate(board["id"], "owner", 0, "noop", operations)
    assert receipt == {"board": board, "change": None}
    assert store.mutate(board["id"], "owner", 0, "empty", []) == receipt
    assert store.history(board["id"], "owner") == []
    later = store.mutate(board["id"], "owner", 0, "edit", edit("later"))
    assert store.mutate(board["id"], "owner", 0, "noop", operations) == receipt
    assert store.get(board["id"], "owner") == later["board"]
    with pytest.raises(api.BoardError) as caught:
        store.mutate(board["id"], "owner", 0, "noop", [])
    assert caught.value.code == "idempotency_conflict"


def test_repeated_undo_replays_and_new_branch_never_oscillates(store, tmp_path):
    board = store.create("owner", nodes=[node()])
    identifier = board["id"]
    for title in ("A", "B", "C"):
        board = store.mutate(identifier, "owner", board["revision"], f"edit-{title}", edit(title))["board"]
    undone = store.undo(identifier, "owner", board["revision"], "undo-C")
    assert undone["board"]["nodes"][0]["title"] == "B"
    assert undone["board"]["revision"] == board["revision"] + 1
    reopened = api.BoardStore(tmp_path / "state" / "boards.sqlite3")
    assert reopened.undo(identifier, "owner", board["revision"], "undo-C") == undone
    board = reopened.mutate(identifier, "owner", undone["board"]["revision"], "branch-D", edit("D"))["board"]
    for title in ("B", "A", "root"):
        result = reopened.undo(identifier, "owner", board["revision"], f"back-{title}")
        assert result["board"]["nodes"][0]["title"] == title
        assert result["board"]["revision"] == board["revision"] + 1
        assert result["change"]["counts"] == {"created": 0, "updated": 1, "deleted": 0}
        board = result["board"]
    before = reopened.history(identifier, "owner")
    with pytest.raises(api.BoardError) as caught:
        reopened.undo(identifier, "owner", board["revision"], "exhausted")
    assert caught.value.code == "nothing_to_undo"
    assert reopened.get(identifier, "owner") == board
    assert reopened.history(identifier, "owner") == before


def test_undo_restores_deleted_subtree_and_all_node_fields(store):
    initial = store.create("owner", nodes=[
        node(body="# PRD", status="in_progress", order=2),
        node("child", "root", body="details", status="completed", order=4),
        node("leaf", "child", body="**leaf**"),
    ])
    changed = store.mutate(initial["id"], "owner", 0, "delete", [
        {"op": "delete", "id": "child"},
        {"op": "update", "id": "root", "fields": {"body": "changed", "status": "pending", "order": 0}},
    ], confirm_destructive=True)
    restored = store.undo(initial["id"], "owner", changed["board"]["revision"], "restore")
    assert restored["board"]["nodes"] == initial["nodes"]
    assert restored["change"]["counts"] == {"created": 2, "updated": 1, "deleted": 0}


def test_view_replacement_is_detached_persistent_and_not_semantic(store, tmp_path):
    board = store.create("owner", nodes=[node()])
    view = {"pan": {"x": 5, "y": -10}, "zoom": 2.5,
            "positions": {"root": {"x": 100, "y": 200}, "missing": {"x": 0, "y": 0}},
            "collapsed": ["root", "missing", "root"]}
    original = copy.deepcopy(view)
    result = store.save_view(board["id"], "owner", view)
    assert view == original
    expected = {**view, "positions": {"root": {"x": 100, "y": 200}}, "collapsed": ["root"]}
    assert result == {"view": expected, "view_revision": 1}
    assert store.save_view(board["id"], "owner", view) == result
    result["view"]["positions"]["root"]["x"] = -7
    reopened = api.BoardStore(tmp_path / "state" / "boards.sqlite3")
    current = reopened.get(board["id"], "owner")
    assert current["view"] == expected
    assert current["view_revision"] == 1
    assert current["revision"] == board["revision"]
    assert current["updated_at"] == board["updated_at"]
    assert reopened.history(board["id"], "owner") == []
    reset = reopened.save_view(board["id"], "owner", {"zoom": 0.2})
    assert reset == {"view": {**board["view"], "zoom": 0.2}, "view_revision": 2}


def test_invalid_views_are_atomic(store):
    board = store.create("owner", nodes=[node()])
    bad_views = [
        None, [], {"extra": True}, {"zoom": True}, {"zoom": "1"},
        {"zoom": float("nan")}, {"zoom": float("inf")}, {"zoom": 0.19}, {"zoom": 2.51},
        {"pan": []}, {"pan": {"x": 0}}, {"pan": {"x": 1_000_001, "y": 0}},
        {"positions": []}, {"positions": {"root": {"x": 0, "y": False}}},
        {"positions": {"missing": {"x": float("inf"), "y": 0}}},
        {"collapsed": {}}, {"collapsed": [True]},
    ]
    for view in bad_views:
        with pytest.raises(api.BoardError) as caught:
            store.save_view(board["id"], "owner", view)
        assert caught.value.status == 400
        assert store.get(board["id"], "owner") == board
    assert store.history(board["id"], "owner") == []


def test_retention_does_not_destroy_active_undo_snapshots(store, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "RETENTION_LIMIT", 3)
    board = store.create("owner", nodes=[node()])
    identifier = board["id"]
    for index in range(5):
        latest = store.mutate(identifier, "owner", board["revision"], f"edit-{index}", edit(str(index)))
        board = latest["board"]
    assert len(store.history(identifier, "owner")) == 3
    assert store.mutate(identifier, "owner", board["revision"] - 1, "edit-4", edit("4")) == latest
    with sqlite3.connect(tmp_path / "state" / "boards.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM undo_stack").fetchone()[0] == 5
    for index in reversed(range(5)):
        board = store.undo(identifier, "owner", board["revision"], f"undo-{index}")["board"]
    assert board["nodes"] == api.validate_nodes([node()])
    assert len(store.history(identifier, "owner")) == 3
    store.delete(identifier, "owner", board["revision"], confirm=True)
    with sqlite3.connect(tmp_path / "state" / "boards.sqlite3") as connection:
        for table in ("boards", "changes", "requests", "undo_stack"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
