# 能力地图

| 领域能力 | 接口 | 边界 |
|---|---|---|
| 有序任务森林 | `validate_nodes` | 多根、稳定 ID、父子关系、同级顺序 |
| 原子语义变更 | `apply_operations` / `BoardStore.mutate` | create/update/move/delete，整批验证后保存 |
| 持久化与身份隔离 | `BoardStore` | 调用者传入可信 owner，不是登录系统 |
| 并发与幂等 | `revision` / `request_id` | 旧版本拒绝，同一 ID 绑定同一完整输入 |
| 独立视图状态 | `save_view` / `view_revision` | 并发客户端传读取时版本，防止静默覆盖 |
| 审计与恢复 | `history` / `undo` | 实际变更回执和节点快照，无变化不伪造变更 |

## 节点契约

`id / parent_id / title / status / body / order`。根的 `parent_id` 为 null，正文为可留空的 Markdown。状态为 `pending / in_progress / completed / cancelled`。

最多 2000 节点、64 层、每批 50 操作；标题非空且最多 200 字符，正文最多 128 KiB。拒绝未知字段、重复 ID、环、孤儿和非法类型。

## 安全与恢复

- 验证后提交，失败不留下部分更新；删除需明确确认。
- 未知网络结果不代表写入失败；重放必须保留原请求 ID 和完整输入。
- 幂等回执及审计记录有保留窗口，不是永久外部账本；撤销快照与该窗口分开维护。
- SQLite 使用私有目录／文件；在线备份使用 SQLite backup API。
- 接入方保留画布和节点 ID，并维护自己的外部身份映射。

登录、模型、浏览器对话及跨数据库删除清理由 ChatSite 管理。直接调用 `BoardStore.delete` 不会清理 ChatSite 的会话数据库。
