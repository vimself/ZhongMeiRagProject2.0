# 2026-05-15 · 管理端知识库权限抽屉修复

## 背景

`/admin/knowledge-bases` 的权限设置抽屉存在两个问题：

- 前端没有直接使用后端提供的 `/api/v2/admin/knowledge-bases/{id}/permission-candidates` 候选用户接口，而是绕到 `/api/v2/admin/users` 自行取一页启用用户。
- 抽屉显式抬高到 `z-index=3000` 后，内部 `ElSelect` 下拉仍走默认 Teleport 到 `body`，下拉层级可能落在抽屉之下，表现为点击“选择用户”或“所有者/编辑者/查看者”后看不到任何选项。

## 调整

- 管理端权限抽屉改为直接调用 `adminListPermissionCandidates(kbId)`，与后端权限模块的真实契约保持一致。
- 每次打开新的知识库权限抽屉时，先清空 `permissions`、`permForm`、`allUsers`，避免不同知识库之间残留旧状态。
- 权限信息和候选用户列表并行加载，已有权限成员继续合并回候选池，保证已有授权用户始终可见。
- 抽屉中的“选择用户”和“角色”两个 `ElSelect` 均改为 `:teleported="false"`，让下拉面板在抽屉内部渲染，避免被高层级抽屉遮挡。

## 验证

- `npm run build`
