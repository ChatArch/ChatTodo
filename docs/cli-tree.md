# CLI 树

```text
chattodo
├── --help        # 查看帮助
├── --version     # 输出包版本
├── --tree        # 输出真实注册的命令树
└── --tree-brief  # 输出不含参数签名的命令树
```

当前没有任务管理子命令；不要将 Python 方法当成 CLI。任务数据操作使用 [Python 接口](interface-tree.md)，网页使用 ChatSite 的 `chatsite todo serve`。

```bash
chattodo --version
chattodo --tree
chattodo --tree-brief
```

ChatStyle 从实际 Click 注册表生成命令树。完整树保留参数签名，简版省略签名。
