# AI Agents Memorandum

This document is maintained by AI agents to track the project status, tasks, and progress.

## Project Status

- **Last Updated:** 2025年9月21日
- **Current State:** Fixed Odoo view ParseError by migrating deprecated 'tree' to 'list'.
- **Next Steps:** Run Odoo server to validate views load, then proceed with further features.

## TODO List

- [ ] 启动 Odoo 并验证 `mcp_server` 模块视图加载无误
- [ ] 增加基础测试覆盖视图和动作

## Activity Log

- 2025年9月21日: 修复表单按钮 context 使用 `active_id` 导致“访问权限不匹配”，改为使用 `id`。
- 2025年9月21日: 迁移视图标签 `<tree>` -> `<list>`，并更新 `view_mode` 至 `list,form`，修复 `Invalid view type: 'tree'` 错误。
- 2025年9月21日: AI agent created this memorandum.
