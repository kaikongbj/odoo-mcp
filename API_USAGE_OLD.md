---

## 7) MCP 客户端配置 json 示例

推荐在 MCP 客户端配置文件（如 mcp_config.json）中通过 `env` 字段传递 API Key：

```json
{
  "mcpServers": {
    "odoo-mcp": {
      "url": "http://127.0.0.1:10888",
      "transport": "streamable-http",
      "env": {
        "MCP_API_KEY": "your-mcp-server-api-key"
      },
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
- 说明：返回“服务器就绪”的简单 JSON（占位实现），用于连通性与权限校验。

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

### 2.3 读取单条记录（自动补全字段）

```graphql
query {
  odooRecord(model: "res.partner", id: 1)
}
```

未显式指定 fields 时，后端会排除大字段（binary/html）并读取其余字段。

### 2.4 统计符合条件的数量

```graphql
query {
  odooSearchCount(model: "res.partner", domain: "[]")
}
```

### 2.5 变更：创建/更新/删除

GraphQL 变量推荐使用 JSONString 以兼容多类型：

创建：

```graphql
mutation($vals: JSONString!) {
  createRecord(model: "res.partner", values: $vals)
}
```

变量：

```json
{"vals": "{\"name\":\"GQL Test Partner\"}"}
```

更新：

```graphql
mutation($id:Int!, $vals:JSONString!) {
  updateRecord(model:"res.partner", id:$id, values:$vals)
}
```

变量：

```json
{"id": 123, "vals": "{\"phone\":\"123456\"}"}
```

删除：

```graphql
mutation($id:Int!) {

  deleteRecord(model:"res.partner", id:$id)
}
```

PS 示例调用（PowerShell）：

```pwsh
$q = @"
mutation($vals: JSONString!) { createRecord(model: "res.partner", values: $vals) }
"@
$vars = @{ vals = '{"name":"GQL Test Partner"}' } | ConvertTo-Json -Compress
ssh 192.168.1.100 "curl -s -X POST -H 'Content-Type: application/json' --data '{"api_key":"<YOUR_API_KEY>","query":$($q | ConvertTo-Json),"variables":$vars}' 'http://127.0.0.1:8069/api/mcp/graphql?db=<DB>'"
```

### 2.6 模型与字段元数据

```graphql
query {
  model_fields(model: "res.partner") { name type string required relation }
}
```

### 2.7 错误返回与排错

- 授权失败：`{"status":"error","code":401,"message":"Unauthorized"}`
- Schema 或执行异常：`{"status":"error","errors":["...堆栈..." ]}`
- `Missing query`：未提供 `query` 或解析失败（检查 Content-Type/json 结构/变量拼接）。

常见问题：

- 收到 HTML 而非 JSON：通常是未命中路由（如代理重写、Content-Type 不匹配或服务未载入新控制器）。建议：
    1. 确认携带 API Key 且为激活服务器；
    2. 指定 `-H 'Content-Type: application/json'`；
    3. 尝试显式路径 `/api/mcp/graphql/http`；
    4. 给 URL 附上 `?db=<DB>`；
    5. 重启 Odoo 服务以加载最新路由。

---

## 3) 认证细节与最佳实践

- API Key 存放于模型 `mcp.server`，只要匹配任一激活服务器即可访问无 server_id 的通用端点（如 GraphQL、服务器列表）。
- 带有 `/<server_id>/...` 路由会限定必须匹配该服务器的 API Key。
- 客户端应优先使用 HTTPS 与内网访问，避免泄露密钥。

---

## 4) 健康检查与自动启动提示

- 健康接口在服务启动后会返回 `listening` 与 `registered` 双判定，避免仅端口监听即误判已启动。
- 模块升级后（尤其是新增控制器/路由）建议重启 Odoo 服务以确保新路由生效。

---

## 5) 附录：快速命令清单（PowerShell）

替换占位：`<YOUR_API_KEY>`、`<DB>`、主机 IP。

```pwsh
# 服务器列表
ssh 192.168.1.100 "curl -s 'http://127.0.0.1:8069/api/mcp/servers?db=<DB>&api_key=<YOUR_API_KEY>'"

# 资源列表
ssh 192.168.1.100 "curl -s 'http://127.0.0.1:8069/api/mcp/resources?db=<DB>&api_key=<YOUR_API_KEY>'"

# GraphQL - 模型列表
ssh 192.168.1.100 "curl -s -X POST -H 'Authorization: Bearer <YOUR_API_KEY>' -H 'Content-Type: application/json' --data '{"query":"query { models }"}' 'http://127.0.0.1:8069/api/mcp/graphql?db=<DB>'"

# GraphQL - 记录列表
ssh 192.168.1.100 "curl -s -X POST -H 'Authorization: Bearer <YOUR_API_KEY>' -H 'Content-Type: application/json' --data '{"query":"query { odooRecords(model: \"res.partner\", domain: \"[]\", fields: [\"name\"], limit: 3) }"}' 'http://127.0.0.1:8069/api/mcp/graphql?db=<DB>'"
# GraphQL - 创建/更新/删除（变量示意）
ssh 192.168.1.100 "curl -s -X POST -H 'Authorization: Bearer <YOUR_API_KEY>' -H 'Content-Type: application/json' --data '{"query":"mutation($vals: JSONString!) { createRecord(model: \"res.partner\", values: $vals) }","variables":{"vals":"{\\"name\\":\\"GQL Test Partner\\"}"}}' 'http://127.0.0.1:8069/api/mcp/graphql?db=<DB>'"
