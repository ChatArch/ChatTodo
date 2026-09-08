# ChatTodo

ChatTodo 提供有序任务树、原子变更、SQLite 持久化、版本冲突检测和撤销能力，供 ChatSite 任务树工作台及其他 Python 程序调用。

> 当前分支为 `0.1.0.dev0` 开发构建。PyPI 的 `0.0.1` 是历史占位包，不包含此 API；部署时使用相应开发源码／构建制品，不把占位包当成可用领域层。

## Python API

```python
from chatenv import get_paths
from chattodo.board import BoardStore

store = BoardStore(get_paths().home_dir / "chattodo" / "boards.sqlite3")
board = store.create("example-user", title="项目计划")
root = board["nodes"][0]["id"]
result = store.mutate(
    board["id"], "example-user", board["revision"], "create-first-task",
    [{"op": "create", "node": {
        "id": "first-task", "parent_id": root,
        "title": "明确需求", "body": "## 目标\n明确交付范围。",
    }}],
)
print(result["change"]["counts"])
```

- `validate_nodes` / `apply_operations`：纯函数校验与变更，不修改调用者输入。
- `BoardStore.create/list/get/mutate/undo/save_view/history/delete`：持久化接口。
- 稳定节点 ID、四种任务状态、Markdown 正文、父子关系和兄弟排序。
- 修改批次原子应用；旧 revision 冲突；同一 request_id 幂等且绑定原始内容。
- 视图坐标／缩放／折叠状态与语义 revision 分离。
- SQLite 专用目录与文件私有，拒绝危险链接／特殊文件；owner 间隔离。

浏览器页面、登录、同源 API、模型调用与站点部署属于 **ChatSite**，不在 ChatTodo 中重复实现 Web 服务。模型配置不属于此领域包。

## 开发验证

```bash
python -m pytest -q
chattodo --version
chattodo --tree
chattodo --tree-brief
python -m build
```

当前 CLI 保留标准根选项；领域能力以 Python API 提供，不伪造尚不存在的业务命令。
