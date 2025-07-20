# MCP 服务器 API 调用文档

本文档详细说明了如何通过 API 与 MCP 服务器进行交互，包括服务器管理和工具调用。

## 基础概念

### 认证

所有对 API 的请求都必须包含有效的 API 密钥进行认证。请在请求的 Header 中提供密钥。

**示例 Header**:
`Authorization: Bearer <YOUR_API_KEY>`

### 服务器 ID

许多 API 端点都需要一个 `server_id` 作为路径参数。您可以通过 Odoo 后台界面或调用“获取服务器列表” API 来获取此 ID。

---

## 1. 服务器管理 API

这些端点用于管理 MCP 服务器本身的状态和配置。

### 获取服务器列表

- **端点**: `GET /api/mcp/servers`
- **描述**: 返回所有已配置的 MCP 服务器的列表。
- **响应**: 一个包含服务器对象的 JSON 数组，每个对象包含 `id`, `name`, `url`, `state` 等信息。

### 启动服务器

- **端点**: `POST /api/mcp/server/<server_id>/start`
- **描述**: 启动指定的 MCP 服务器实例。
- **响应**: 返回操作结果，例如 `{"status": "success", "message": "Server started"}`。

### 停止服务器

- **端点**: `POST /api/mcp/server/<server_id>/stop`
- **描述**: 停止指定的 MCP 服务器实例。
- **响应**: 返回操作结果，例如 `{"status": "success", "message": "Server stopped"}`。

---

## 2. 资源管理 API

这些端点用于管理与服务器关联的资源。

### 获取资源列表

- **端点**: `GET /api/mcp/resources`
- **描述**: 返回所有已配置的资源列表。
- **查询参数**:
    - `server_id` (可选): 按指定服务器 ID 筛选资源。
- **响应**: 一个包含资源对象的 JSON 数组。

### 获取资源内容

- **端点**: `GET /api/mcp/resource/<resource_id>`
- **描述**: 获取指定资源的具体内容。
- **响应**: 资源的具体内容，格式取决于资源类型。

---

## 3. FastMCP 工具调用代理 API

这是与大语言模型（LLM）交互的核心端点。通过此接口，您可以调用在 FastMCP 服务器上注册的任何工具。

### 调用工具

- **端点**: `POST /api/mcp/server/<server_id>/fastmcp`
- **描述**: 向指定的、已激活的 MCP 服务器代理一个工具调用请求。
- **请求体 (Body)**:
    - `tool` (字符串): 要调用的工具名称。
    - `arguments` (对象): 一个包含工具所需参数的键值对对象。

### 工具调用示例

#### 示例 1: 查询客户列表

调用 `query_odoo_model` 工具，查询前 10 个客户的名称和邮箱。

**请求体**:

```json
{
  "tool": "query_odoo_model",
  "arguments": {
    "model_name": "res.partner",
    "domain": "[]",
    "fields": "[\"name\", \"email\"]",
    "limit": 10
  }
}
```

#### 示例 2: 创建一个新客户

调用 `create_odoo_record` 工具，创建一个名为“新客户”的记录。

**请求体**:

```json
{
  "tool": "create_odoo_record",
  "arguments": {
    "model_name": "res.partner",
    "values": {
      "name": "新客户",
      "email": "customer@example.com"
    }
  }
}
```

#### 示例 3: 获取单个客户的详细信息

调用 `get_odoo_record` 工具，获取 ID 为 1 的客户的所有字段信息。

**请求体**:

```json
{
  "tool": "get_odoo_record",
  "arguments": {
    "model_name": "res.partner",
    "record_id": 1
  }
}
```