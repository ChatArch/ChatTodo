"""Public task-forest contract: pure functions, no database mocks."""

import copy
import importlib
import importlib.util

import pytest


def test_public_module_exists():
    assert importlib.util.find_spec("chattodo.board") is not None, "board API is missing"


@pytest.fixture
def api():
    return importlib.import_module("chattodo.board")


def node(identifier="root", parent_id=None, **fields):
    return {"id": identifier, "parent_id": parent_id, "title": identifier, **fields}


def test_error_contract(api):
    error = api.BoardError("invalid_nodes", "Bad nodes")
    assert (error.code, error.message, error.status) == ("invalid_nodes", "Bad nodes", 400)
    assert str(error) == "Bad nodes"
    assert api.BoardError("conflict", "Stale", 409).status == 409


def test_normalization_is_detached_and_does_not_change_inputs(api):
    source = [node(), node("child", "root", body="# PRD\n\n中文\x00")]
    before = copy.deepcopy(source)
    result = api.validate_nodes(source)
    assert result == [
        {"id": "root", "parent_id": None, "title": "root", "status": "pending", "body": "", "order": 0},
        {"id": "child", "parent_id": "root", "title": "child", "status": "pending", "body": "# PRD\n\n中文\x00", "order": 0},
    ]
    result[0]["title"] = "detached"
    assert source == before
    assert api.validate_nodes([]) == []
    assert len(api.validate_nodes([node("one"), node("two")])) == 2


@pytest.mark.parametrize("nodes", [
    None, {}, "[]", (), [None], [{}], [{"title": "missing-id"}], [{"id": "missing-title"}],
    [node(extra=True)], [node(id="../unsafe")], [node(id="a.b")], [node(id="")],
    [node(id=True)], [node(id="x" * 129)], [node(id="中文")], [node(parent_id=1)],
    [node(title="")], [node(title=" \n ")], [node(title="x" * 201)], [node(title=123)],
    [node(title="\ud800")], [node(status="done")], [node(status=None)], [node(status=[])],
    [node(body=None)], [node(body=[])], [node(body="\ud800")],
    [node(order=True)], [node(order=-1)], [node(order=1.2)], [node(order="0")],
    [node(), node()], [node("child", "absent")], [node("self", "self")],
    [node("a", "b"), node("b", "a")],
    [node(), node("a", "b"), node("b", "a")],
])
def test_invalid_nodes_fail_cleanly(api, nodes):
    before = copy.deepcopy(nodes)
    with pytest.raises(api.BoardError) as caught:
        api.validate_nodes(nodes)
    assert caught.value.status == 400
    assert caught.value.code
    assert nodes == before


def test_resource_boundaries(api):
    assert len(api.validate_nodes([node(str(i)) for i in range(2000)])) == 2000
    chain = [node(str(i), str(i - 1) if i else None) for i in range(64)]
    assert len(api.validate_nodes(chain)) == 64
    for too_large in [
        [node(str(i)) for i in range(2001)],
        chain + [node("64", "63")],
        [node(body="x" * (128 * 1024 + 1))],
        [node(body="中" * (128 * 1024 // 3 + 1))],
    ]:
        with pytest.raises(api.BoardError) as caught:
            api.validate_nodes(too_large)
        assert caught.value.status == 413
    assert api.validate_nodes([node(body="x" * (128 * 1024))])[0]["body"]


def test_create_future_parent_update_move_and_actual_diff_counts(api):
    source = [node(), node("old", "root")]
    operations = [
        {"op": "create", "node": node("leaf", "later")},
        {"op": "create", "node": node("later", "root")},
        {"op": "update", "id": "leaf", "fields": {"body": "# Details"}},
        {"op": "update", "id": "old", "fields": {"title": "edited"}},
        {"op": "update", "id": "old", "fields": {"status": "in_progress"}},
        {"op": "move", "id": "old", "parent_id": "later", "order": 2},
    ]
    before = copy.deepcopy((source, operations))
    result, counts = api.apply_operations(source, operations)
    assert counts == {"created": 2, "updated": 1, "deleted": 0}
    assert result[1]["parent_id"] == "later"
    assert result[1]["order"] == 2
    assert result[2]["body"] == "# Details"
    assert (source, operations) == before


def test_only_final_forest_must_be_valid(api):
    source = [node("a"), node("b", "a")]
    result, counts = api.apply_operations(source, [
        {"op": "move", "id": "a", "parent_id": "b", "order": 0},
        {"op": "move", "id": "b", "parent_id": None, "order": 0},
    ])
    assert result[1]["parent_id"] is None
    assert counts == {"created": 0, "updated": 2, "deleted": 0}


def test_noop_and_create_then_delete_have_zero_diff(api):
    source = [node()]
    result, counts = api.apply_operations(source, [
        {"op": "update", "id": "root", "fields": {"title": "temporary"}},
        {"op": "update", "id": "root", "fields": {"title": "root"}},
        {"op": "create", "node": node("temporary", "root")},
        {"op": "delete", "id": "temporary"},
    ], confirm_destructive=True)
    assert result == api.validate_nodes(source)
    assert counts == {"created": 0, "updated": 0, "deleted": 0}


def test_delete_whole_branch_is_explicit_and_counts_nodes(api):
    source = [node(), node("child", "root"), node("leaf", "child"), node("other")]
    operations = [{"op": "delete", "id": "root"}]
    with pytest.raises(api.BoardError) as caught:
        api.apply_operations(source, operations)
    assert caught.value.code == "confirmation_required"
    result, counts = api.apply_operations(source, operations, confirm_destructive=True)
    assert [n["id"] for n in result] == ["other"]
    assert counts == {"created": 0, "updated": 0, "deleted": 3}
    assert api.apply_operations([node()], operations, confirm_destructive=True)[0] == []


@pytest.mark.parametrize("value", [None, "true", "false", 0, 1, [], {}])
def test_confirmation_is_strict_boolean_even_without_delete(api, value):
    with pytest.raises(api.BoardError):
        api.apply_operations([node()], [], confirm_destructive=value)


@pytest.mark.parametrize("operations", [
    None, {}, (), [None], [{}], [{"op": "unknown"}],
    [{"op": []}], [{"op": "create", "node": node(), "unknown": 1}],
    [{"op": "create", "node": node()}],
    [{"op": "update", "id": "missing", "fields": {"title": "edit"}}],
    [{"op": "update", "id": "root", "fields": {"id": "other"}}],
    [{"op": "update", "id": "root", "fields": {"parent_id": None}}],
    [{"op": "update", "id": "root", "fields": None}],
    [{"op": "update", "id": "root", "fields": {"title": ""}}],
    [{"op": "move", "id": "root", "parent_id": None}],
    [{"op": "move", "id": "root", "parent_id": None, "order": True}],
    [{"op": "move", "id": "root", "parent_id": "absent", "order": 0}],
    [{"op": "move", "id": "root", "parent_id": "root", "order": 0}],
    [{"op": "delete", "id": "absent"}],
    [{"op": "delete", "id": "root", "confirm_destructive": True}],
])
def test_operations_are_strict_and_atomic(api, operations):
    source = [node()]
    original = copy.deepcopy(source)
    with pytest.raises(api.BoardError):
        api.apply_operations(source, operations, confirm_destructive=True)
    assert source == original


def test_late_failure_keeps_inputs_and_cannot_hide_bad_fields(api):
    source = [node()]
    operations = [
        {"op": "update", "id": "root", "fields": {"title": "valid"}},
        {"op": "create", "node": node("bad", "missing")},
    ]
    original = copy.deepcopy((source, operations))
    with pytest.raises(api.BoardError):
        api.apply_operations(source, operations)
    assert (source, operations) == original
    with pytest.raises(api.BoardError):
        api.apply_operations(source, [
            {"op": "update", "id": "root", "fields": {"order": True}},
            {"op": "update", "id": "root", "fields": {"order": 0}},
        ])


def test_operation_count_limit(api):
    operation = {"op": "update", "id": "root", "fields": {}}
    assert api.apply_operations([node()], [operation] * 50)[1]["updated"] == 0
    with pytest.raises(api.BoardError) as caught:
        api.apply_operations([node()], [operation] * 51)
    assert caught.value.status == 413
