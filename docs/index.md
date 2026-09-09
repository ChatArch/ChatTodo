# ChatTodo

用于项目规划与思维发散的 **Python 任务树领域库**。人和模型可基于同一份节点数据提出变更，由领域层验证后原子保存。

<div class="grid cards" markdown>

- **Python 接入**

    从 [Python 接口树](interface-tree.md) 开始创建画布、修改节点和保存视图。

- **数据边界**

    [能力地图](capability-map.md) 说明节点、版本、owner、幂等和撤销。

- **真实命令**

    [CLI 树](cli-tree.md) 列出已注册的根选项。业务操作通过 Python API 使用。

- **完整网页**

    [ChatSite Todo](https://arch.gh.wzhecnu.cn/ChatSite/todo-workbench/) 提供登录、多画布、Markdown 与模型协作。

</div>

## 安装

```bash
pip install "ChatTodo>=0.1.0,<0.2.0"
chattodo --version
chattodo --tree
```

| 目标 | 接口 |
|---|---|
| 只写标题构思 | 节点 `body` 留空 |
| 后端管理任务 | `BoardStore` |
| 预览或校验变更 | `validate_nodes` / `apply_operations` |
| 浏览器与模型协作 | 安装 `ChatSite[todo]` |

ChatTodo 不负责登录、HTTP、模型调用或外部任务执行，不将讨论结果自动标记为已实施。
