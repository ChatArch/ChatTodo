# CLI Tree

```text
chattodo
├── --help        # Show help
├── --version     # Print package version
├── --tree        # Print the registered command tree
└── --tree-brief  # Print the tree without parameter signatures
```

There are no task-management subcommands. Use the [Python API](interface-tree.md) for task data, or ChatSite's `chatsite todo serve` for the Web workbench.

```bash
chattodo --version
chattodo --tree
chattodo --tree-brief
```

ChatStyle renders the actual Click registry. The full tree includes parameter signatures; the brief tree omits them.
