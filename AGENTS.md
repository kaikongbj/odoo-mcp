# AI Agents Memorandum

This document is maintained by AI agents to track the project status, tasks, and progress.

## Project Status

- **Last Updated:** 2025年9月23日
- **Current State:** FastMCP upgraded to >=2.9 (installed 2.12.3) to support streamable-http; views and services
  previously migrated and passing static checks.
- **Next Steps:** Run Odoo server to validate views load, then proceed with further features.

## TODO List

- [ ] 启动 Odoo 并验证 `mcp_server` 模块视图加载无误
- [ ] 增加基础测试覆盖视图和动作
- [ ] 验证 API 端点基于 `X-Api-Key`/`Authorization: Bearer` 的鉴权逻辑（200/401）
- [ ] 通过 MCP GraphQL 工具查询 `servers/resources` 并返回预期字段
- [ ] 校验端口字段：范围限制、活跃服务器端口唯一、服务启动端口占用日志
- [ ] 实机验证 FastMCP streamable-http 启动并可在配置端口访问
- [ ] 验证 Odoo 启动时自动启动 MCP 服务器（auto_start=True 且 active=True）
- [ ] 生产环境（192.168.1.100）升级 fastmcp>=2.9 并安装 graphene>=3.3；或在保留 fastmcp==1.0 下验证 SSE 降级路径无误

## Activity Log

- 2025年9月23日: 修复自动启动误判与增强健康检查：
    - 健康检查判定“已运行”从仅依赖 listening 改为 listening 且 registered，避免在系统刚启动时出现“already active,
      skipping”而实际未启动的情况
    - start_server 的预检查与模块/模型级 auto-start 逻辑统一，若监听但未注册则警告端口冲突并跳过启动，避免重复占用
    - 日志从“checking N server(s)”改为“starting N server(s)”，并在已运行路径中输出 listening/registered 细节
    - 新增回归测试 tests/test_autostart.py 覆盖仅监听未注册的场景

- 2025年9月23日: 模块升级至 1.1.0；新增健康检查能力：
    - 服务侧新增 health_check 方法，基于端口探测确认监听状态
    - 控制器新增 GET `/api/mcp/server/{id}/health` 路由（需要 API Key）
    - 启动流程在获取到异步结果后执行健康检查，据此写回 state=active/inactive
    - 启动路由返回包含 health 字段的结果，便于前端判断
      建议：后续可增加主动 GraphQL/工具探测作为深度健康检查
- 2025年9月23日: 生产服务器（192.168.1.100, Python 3.10.12）检测到 fastmcp==1.0、uvicorn==0.36.0、graphene 未安装；因不支持
  `streamable-http`，启动时报错 `Unknown transport: streamable-http` 与 `FastMCP.run unexpected keyword 'host'`
  ；已在服务代码中加入传输与绑定的双重回退：
    - 若 `run(host/port)` 不支持则自动使用环境变量 `FASTMCP_HOST/PORT/BIND`
    - 若 `streamable-http` 不支持则自动降级为 `sse`
      建议：将生产 fastmcp 升级至 >=2.9 并安装 graphene>=3.3 以启用 GraphQL 工具与 streamable-http。
- 2025年9月23日: 修复生产环境报错（AttributeError: Environment.manage）：模块级 _register_hook 使用 Registry + cursor 创建
  Environment，去除 api.Environment.manage 依赖；仅保留模块级钩子以避免重复执行；为线程加上 advisory lock 保护与延时启动。
- 2025年9月23日: 文档清理：修复 DEPLOYMENT_GUIDE.md 的 MD040（代码块缺少语言）以通过静态检查；全面扫描
  controllers/models/services/views/graphql/tests 无语法/导入错误。
- 2025年9月21日: 升级 fastmcp 至 2.12.3（requirements 设为 >=2.9.0），以启用 streamable-http 传输并兼容 host/port
  或环境变量回退；已安装依赖并校验版本。
- 2025年9月23日: 实现 Odoo 启动自动启动 MCP 服务器：新增 `auto_start` 字段，表单/列表展示；在模块 `_register_hook` 中以线程异步启动
  `active & auto_start` 的服务器，使用 PostgreSQL advisory lock 保证单实例执行。
- 2025年9月21日: 新增 `port` 字段（默认10888），表单/列表展示；服务启动改用记录端口；控制器与GraphQL返回端口；演示数据为不同端口。
- 2025年9月21日: 表单页底部的消息/活动区域由 `<div class="oe_chatter">` 迁移为 `<chatter/>`，修复布局错位与兼容性问题。
- 2025年9月21日: 视图表单页头按钮由“激活/停用”改为“启动服务器/停止服务器”，并仅在激活状态下显示“停止服务器”。
- 2025年9月21日: 修复表单按钮 context 使用 `active_id` 导致“访问权限不匹配”，改为使用 `id`。
- 2025年9月21日: 迁移视图标签 `<tree>` -> `<list>`，并更新 `view_mode` 至 `list,form`，修复 `Invalid view type: 'tree'` 错误。
- 2025年9月21日: 控制器路由从 `auth='api_key'` 迁移为 `auth='public' + 自定义API Key检验`，统一支持 `X-Api-Key` 与
  `Authorization: Bearer`，并为路由加 `csrf=False`；补充 `fields` 导入以修复时间戳写入。
- 2025年9月21日: 引入 GraphQL（graphene），新增 `services/graphql_schema.py` 与 FastMCP `graphql` 工具；更新
  requirements；添加最小测试。
- 2025年9月21日: AI agent created this memorandum.
