# MCP 服务器 API 使用文档

本文档面向开发者与自动化脚本，系统性介绍 MCP 模块在 Odoo 中提供的 HTTP/JSON 接口与 GraphQL 能力，涵盖认证、端点说明、请求示例（PowerShell/curl）、以及常见问题与排错建议。

## 0. 基础说明

- **版本与环境**：Odoo 18，模块 `mcp_server`
- **认证方式**（符合 MCP 规范）：
    - **REST 路由**：使用接口参数 `api_key` 进行授权（不使用 Header）
    - GET：通过查询参数传递，例如 `...?api_key=<YOUR_API_KEY>`
    - POST：通过 JSON 请求体传递，例如 `{ "api_key": "<YOUR_API_KEY>", ... }`
    - **MCP 工具**：使用 `serverAuthToken` 标准认证（**重要更新**）
        - 客户端通过 `Authorization: Bearer <token>` HTTP header 传递认证令牌
        - 支持自定义 `serverAuthTokenHeader` 字段
        - 不再使用环境变量或工具参数中的 `api_key`
- **多数据库环境**：建议在 URL 上带 `?db=<数据库名>`，例如 `...?db=kaikong18`
- **默认主机**：`http://127.0.0.1:8069`（REST API），`http://127.0.0.1:10888`（MCP 服务）

**⚠️ 重要变更**：从 v1.1+ 开始，MCP 工具认证已迁移至 `serverAuthToken` 标准，提供更好的安全性和标准兼容性。

---

## 1) 服务器与资源 REST API

这些路由统一位于 `/api/mcp/...` 前缀下，返回 JSON。它们在控制器 `mcp_server/controllers/main.py` 中实现。

### 1.1 获取服务器列表

- 路由：`GET /api/mcp/servers`
- 说明：返回当前激活的 MCP 服务器列表
- 认证方式：通过 `api_key` 接口参数（Query 或 JSON 体）。不使用 HTTP Header。
- 响应数据：`[{id,name,server_url,port,state,last_connection}, ...]`

PowerShell 示例（远端执行 curl）

```pwsh
ssh 192.168.1.100 "curl -s -X GET 'http://127.0.0.1:8069/api/mcp/servers?db=<DB>&api_key=<YOUR_API_KEY>'"
```

### 1.2 获取资源列表

- 路由：`GET /api/mcp/resources`
- 可选参数：`server_id`（按服务器过滤）
- 响应数据：`[{id,name,resource_uri,resource_type,server_id,server_name,last_fetch}, ...]`

```pwsh
ssh 192.168.1.100 "curl -s -X GET 'http://127.0.0.1:8069/api/mcp/resources?db=<DB>&api_key=<YOUR_API_KEY>'"
```

### 1.3 获取单个资源内容

- 路由：`GET /api/mcp/resource/<resource_id>`
- 响应数据：`{id,name,content,resource_uri,server_id,server_name,resource_type,last_fetch}`

```pwsh
ssh 192.168.1.100 "curl -s -X GET 'http://127.0.0.1:8069/api/mcp/resource/1?db=<DB>&api_key=<YOUR_API_KEY>'"
```

### 1.4 FastMCP 代理（占位）

- 路由：`GET|POST /api/mcp/server/<server_id>/fastmcp`
- 说明：返回"服务器就绪"的简单 JSON（占位实现），用于连通性与权限校验。

```pwsh
ssh 192.168.1.100 "curl -s 'http://127.0.0.1:8069/api/mcp/server/1/fastmcp?db=<DB>&api_key=<YOUR_API_KEY>'"
```

### 1.5 启动/停止服务器与健康检查

- 启动：`POST /api/mcp/server/<server_id>/start`
- 停止：`POST /api/mcp/server/<server_id>/stop`
- 健康：`GET  /api/mcp/server/<server_id>/health`

```pwsh
# 启动
ssh 192.168.1.100 "curl -s -X POST 'http://127.0.0.1:8069/api/mcp/server/1/start?db=<DB>&api_key=<YOUR_API_KEY>'"
# 健康
ssh 192.168.1.100 "curl -s 'http://127.0.0.1:8069/api/mcp/server/1/health?db=<DB>&api_key=<YOUR_API_KEY>'"
```

---

## 2) GraphQL（直连 Odoo 数据）

GraphQL 接口暴露于两个路由，功能一致：

- JSON 首选：`POST /api/mcp/graphql`
- HTTP 兜底（便于某些代理/客户端）：`POST /api/mcp/graphql/http`

两者请求体统一为 JSON，字段：

- `api_key`: 授权所需的密钥（必填）
- `query`: GraphQL 查询/变更字符串
- `variables`: 变量对象（可选）

示例 Header：

- `Content-Type: application/json`

注意：

- 若客户端按 JSON-RPC 发送包裹体（`{"jsonrpc":"2.0","params":{...}}`），也会被兼容解析。
- 可通过查询串传入 `?db=<数据库>` 选择数据库。

### 2.1 入门：查询模型列表

```pwsh
ssh 192.168.1.100 "curl -s -X POST \
  -H 'Content-Type: application/json' \
  --data '{"api_key":"<YOUR_API_KEY>","query":"query { models }"}' \
  'http://127.0.0.1:8069/api/mcp/graphql?db=<DB>'"
```

返回示例（节选）：

```json
{
  "status": "success",
  "data": { "models": ["res.partner", "sale.order", "mcp.server", "..." ] }
}
```

### 2.2 读取记录列表（fields/domain/分页/排序）

Query：

```graphql
query {
  odooRecords(
    model: "res.partner",
    domain: "[]",
    fields: ["name", "email", "parent_id"],
    limit: 5,
    offset: 0,
    order: "name asc"
  )
}
```

说明：

- domain 传入 JSON 字符串；如不确定可传 "[]"（空条件）
- many2one 字段会被规范化为 `{"id": 1, "name": "..."}`

---

## 3) MCP 工具签名与调用示例（重要更新）

**🔐 serverAuthToken 标准认证**

从 v1.1+ 开始，MCP 工具使用标准的 `serverAuthToken` 认证机制，符合 MCP 规范并提供更好的安全性。

### 3.1 认证方式

**✅ 推荐方式：Authorization Bearer Token**
```
Authorization: Bearer <your_api_key>
```

**✅ 自定义 Header（可选）**
```
X-API-Key: <your_api_key>
Custom-Auth-Header: <your_api_key>
```

### 3.2 客户端实现

TypeScript 客户端示例：

```typescript
// 默认方式（推荐）
const headers = {
  ...descHeaders,
  Authorization: `Bearer ${serverAuthToken}`
};

// 自定义 header 方式
const headers = {
  ...descHeaders,
  [serverAuthTokenHeader]: serverAuthToken
};
```

### 3.3 认证流程

1. **客户端发送请求** - 在 HTTP headers 中包含 `Authorization: Bearer <token>`
2. **服务器提取令牌** - 从 `ctx.get_http_request().headers` 中获取认证信息
3. **令牌验证** - 与 `mcp.server` 记录中的 `api_key` 字段匹配
4. **授权通过** - 执行工具调用并返回结果

**🔒 安全特性**：

- 令牌仅通过 HTTP headers 传递，不出现在 URL 或日志中
- 支持标准 `Authorization: Bearer` 和自定义 header 字段
- 服务器端不从环境变量读取认证信息
- 所有敏感信息在日志中自动掩码处理

### 3.4 工具签名

**数据查询工具**：

- `query_odoo_model(model_name: string, domain?: string, fields?: string, limit?: int, offset?: int, order?: string)`
- `get_odoo_record(model_name: string, record_id: int)`
- `get_odoo_model_metadata(model_name: string)`

**数据变更工具**：

- `create_odoo_record(model_name: string, values: object)`
- `update_odoo_record(model_name: string, record_id: int, values: object)`
- `delete_odoo_record(model_name: string, record_id: int)`

**资源管理工具**：

- `list_resources()`
- `get_resource_content(resource_uri: string)`

**GraphQL 工具**：

- `graphql(query: string, variables?: object)`

---

## 4) MCP 客户端配置示例（更新）

### 4.1 使用 serverAuthToken（推荐）

**标准配置**：
```json
{
  "mcpServers": {
    "odoo-mcp": {
      "url": "http://127.0.0.1:10888",
      "transport": "streamable-http",
      "serverAuthToken": "your-mcp-server-api-key"
    }
  }
}
```

**TypeScript 客户端配置**：

```typescript
const mcpConfig = {
  description: {
    serverAuthToken: "your-mcp-server-api-key",
    // 可选：自定义 header 名称
    serverAuthTokenHeader: "X-API-Key"
  }
};
```

### 4.2 传输类型选择

- **`streamable-http`** - 推荐，支持现代 HTTP 特性
- **`sse`** - 兼容老版本 FastMCP

### 4.3 认证配置说明

**✅ 新方式（serverAuthToken）**：

- 通过 `serverAuthToken` 字段配置
- 自动使用 `Authorization: Bearer` header
- 符合 MCP 标准，更安全

**⚠️ 过时方式（不推荐）**：

```json
{
  "env": {
    "MCP_API_KEY": "your-api-key"
  },
  "metadata": {
    "api_key": "your-api-key"
  }
}
```

### 4.4 完整配置示例

```json
{
  "mcpServers": {
    "odoo-mcp": {
      "url": "http://127.0.0.1:10888",
      "transport": "streamable-http",
      "serverAuthToken": "aaa123",
      "disabled": false,
      "description": "Odoo ERP MCP 服务器",
      "timeout": 30
    }
  }
}
```

---

## 5) 版本变更与升级指南

### 5.1 v1.1+ 重要变更

**🔐 认证机制升级**：

- MCP 工具认证从环境变量迁移至 `serverAuthToken` 标准
- 客户端需使用 `Authorization: Bearer <token>` HTTP header
- 提供更好的安全性和 MCP 标准兼容性

**🔧 实现改进**：

- 使用 `ctx.get_http_request()` 正确提取 HTTP 请求信息
- 增强调试日志，支持认证流程追踪
- 自动掩码敏感信息以保护安全

### 5.2 升级步骤

1. **更新客户端配置**：
   ```json
   {
     "serverAuthToken": "your-api-key"  // 新增
     // 删除或注释旧的 env/metadata 配置
   }
   ```

2. **验证连接**：
   ```bash
   curl -H "Authorization: Bearer your-api-key" \
        -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
        http://127.0.0.1:10888
   ```

3. **检查日志**：查看服务器日志确认认证成功：
   ```
   ✅ 从 Authorization Bearer header 中提取到 serverAuthToken
   🎉 serverAuthToken 授权检查成功
   ```

---

## 6) 调试与故障排除

### 6.1 常见错误

**401 Unauthorized**：

```json
{
  "code": 401,
  "message": "Unauthorized"
}
```

- 检查 `serverAuthToken` 是否正确
- 确认 MCP 服务器记录中的 `api_key` 字段匹配

**连接失败**：

- 确认 MCP 服务器已启动（检查端口 10888）
- 验证防火墙和网络配置

**传输错误**：

- 尝试使用 `sse` 替代 `streamable-http`
- 检查 FastMCP 版本兼容性

### 6.2 调试工具

**连接测试**：

```bash
curl -H "Authorization: Bearer your-api-key" \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
     http://127.0.0.1:10888
```

**日志查看**：

```bash
# 查看 Odoo 日志
tail -f /var/log/odoo/odoo.log | grep mcp_server

# 查看认证流程
tail -f /var/log/odoo/odoo.log | grep "serverAuthToken"
```

---

## 7) 总结

本 MCP 服务器提供：

- **🔌 标准 MCP 协议支持** - 符合 MCP 规范的工具调用
- **🔐 安全认证机制** - serverAuthToken 标准认证
- **📊 GraphQL 数据访问** - 灵活的 Odoo 数据查询和变更
- **🚀 REST API 接口** - 用于调试和直接集成
- **💡 丰富的调试信息** - 详细的日志和错误提示

**快速开始**：

1. 配置 `serverAuthToken` 认证
2. 连接到 MCP 服务端口（默认 10888）
3. 使用 MCP 工具访问 Odoo 数据

**技术支持**：查看服务器日志获取详细的调试信息和错误诊断。

---

**文档版本**：v1.1+ （支持 serverAuthToken 标准认证）  
**最后更新**：2025-09-27
