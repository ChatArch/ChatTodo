# Capability Map

| Capability | Interface | Boundary |
|---|---|---|
| Ordered task forests | `validate_nodes` | Multiple roots, stable IDs, parent links and sibling order |
| Atomic semantic changes | `apply_operations` / `BoardStore.mutate` | create/update/move/delete, validated before commit |
| Persistence and ownership | `BoardStore` | Caller supplies a trusted owner; not a login system |
| Concurrency and replay | `revision` / `request_id` | Stale versions rejected; request ID binds complete input |
| Independent view state | `save_view` / `view_revision` | Concurrent clients supply the read version |
| Audit and recovery | `history` / `undo` | Actual receipts and node snapshots, no fabricated no-op changes |

## Node contract

`id / parent_id / title / status / body / order`. Roots have null parents. Markdown bodies may be empty. Status is `pending / in_progress / completed / cancelled`.

Limits: 2000 nodes, 64 levels, 50 operations per batch. Titles are non-empty and at most 200 characters; bodies at most 128 KiB. Unknown fields, duplicate IDs, cycles, orphans and invalid types are rejected.

## Safety and recovery

- Validation precedes commit; failures leave no partial updates. Deletion requires confirmation.
- Ambiguous network failure does not imply a failed write. Replay the same original request ID and complete input.
- Receipts and audit entries have bounded retention, not a permanent external ledger. Undo snapshots are separate.
- SQLite paths use private directories/files; use SQLite backup APIs for online databases.
- Integrations preserve board/node IDs and maintain their own external identity mappings.

ChatSite owns login, models, browser conversations and cross-database deletion cleanup. `BoardStore.delete` alone does not clean ChatSite's conversation database.
