# Python API

```text
chattodo.board
├── BoardError          # code / message / status
├── validate_nodes      # Validate and normalize a forest
├── apply_operations    # Pure atomic-operation preview
└── BoardStore          # SQLite persistence
    ├── create / list / get
    ├── mutate / undo / history
    ├── save_view
    └── delete
```

## Minimal example

```python
from uuid import uuid4
from chatenv import get_paths
from chattodo.board import BoardStore

store = BoardStore(get_paths().home_dir / "chattodo" / "boards.sqlite3")
owner = "example-user"  # identity verified by the integrating service
board = store.create(owner, title="Project ideas")
root = board["nodes"][0]["id"]
result = store.mutate(board["id"], owner, board["revision"], uuid4().hex, [
    {"op": "create", "node": {"id": uuid4().hex, "parent_id": root,
     "title": "One direction", "body": "", "status": "pending", "order": 0}}
])
current = store.get(board["id"], owner)
current["view"]["pan"]["x"] = 24
store.save_view(current["id"], owner, current["view"],
                view_revision=current["view_revision"])
```

## Store methods

| Method | Parameters |
|---|---|
| `create` | `owner, title=<default title>, nodes=None` |
| `list` | `owner` |
| `get` / `history` | `board_id, owner` |
| `mutate` | `board_id, owner, revision, request_id, operations, *, actor="user", confirm_destructive=False` |
| `undo` | `board_id, owner, revision, request_id` |
| `save_view` | `board_id, owner, view, view_revision=None` |
| `delete` | `board_id, owner, revision, *, confirm=False` |

`mutate` and `undo` return the board and change receipt. `get` includes separate semantic and view revisions. The optional view version supports older in-process callers; concurrent clients must always supply the read version. Handle errors through `BoardError`'s structured fields.

Do not let untrusted browser input choose the owner or bypass validation through SQL.
