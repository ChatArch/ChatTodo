# ChatTodo

A **Python task-forest domain library** for planning and brainstorming. Human and model proposals share the same validated, atomically persisted node data.

<div class="grid cards" markdown>

- **Python integration**

    Use the [Python API](interface-tree.md) to create boards, mutate nodes and save views.

- **Data boundaries**

    The [capability map](capability-map.md) explains nodes, revisions, owners, idempotency and undo.

- **Real commands**

    The [CLI tree](cli-tree.md) lists registered root options. Business operations are Python APIs.

- **Complete Web workbench**

    [ChatSite Todo](https://arch.gh.wzhecnu.cn/ChatSite/en/todo-workbench/) provides login, multiple canvases, Markdown and model collaboration.

</div>

## Install

```bash
pip install "ChatTodo>=0.1.0,<0.2.0"
chattodo --version
chattodo --tree
```

| Goal | Interface |
|---|---|
| Brainstorm with titles alone | Leave node `body` empty |
| Persist tasks in a backend | `BoardStore` |
| Preview or validate mutations | `validate_nodes` / `apply_operations` |
| Browser and model collaboration | Install `ChatSite[todo]` |

ChatTodo does not own login, HTTP, model calls or external execution. Discussion is not evidence that a task has been implemented.
