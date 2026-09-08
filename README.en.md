# ChatTodo

ChatTodo provides ordered task forests, validated atomic operations, SQLite persistence, optimistic revisions, idempotency and undo for the ChatSite task workbench and Python callers.

This branch is a **0.1.0.dev0 development build**. The historical PyPI 0.0.1 placeholder does not contain these APIs. Install the corresponding development source or built artifact when integrating this feature.

```python
from chatenv import get_paths
from chattodo.board import BoardStore

store = BoardStore(get_paths().home_dir / "chattodo" / "boards.sqlite3")
board = store.create("example-user", title="Project plan")
root = board["nodes"][0]["id"]
result = store.mutate(
    board["id"], "example-user", board["revision"], "first-task-request",
    [{"op": "create", "node": {
        "id": "first-task", "parent_id": root, "title": "Define the scope",
        "body": "## Goal\nAgree on the deliverable.",
    }}],
)
print(result["change"]["counts"])
```

`validate_nodes` and `apply_operations` are non-mutating pure functions. `BoardStore` exposes `create`, `list`, `get`, `mutate`, `undo`, `save_view`, `history`, and `delete`. Semantic revisions are independent from view state. Requests are bound to their idempotency keys; owner boundaries and private storage permissions are enforced.

Web pages, authentication, same-origin HTTP APIs and model orchestration belong to **ChatSite**, not this domain package. The current CLI retains standard version/tree options; it does not advertise unimplemented business commands.

Run `python -m pytest -q`, `chattodo --version`, `chattodo --tree`, `chattodo --tree-brief`, and `python -m build` for source validation.
