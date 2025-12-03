# GraphQL 使用指南

本文档提供 MCP 服务器 GraphQL API 的全面使用指南，包含各种实际场景的查询示例和最佳实践。

## 📚 目录

1. [快速开始](#快速开始)
2. [基础查询](#基础查询)
3. [嵌套数据查询](#嵌套数据查询)
4. [数据变更操作](#数据变更操作)
5. [字段元数据查询](#字段元数据查询)
6. [高级功能](#高级功能)
7. [错误处理](#错误处理)
8. [性能优化](#性能优化)
9. [实际应用场景](#实际应用场景)

---

## 🚀 快速开始

### 连接信息

- **端点**: `POST /api/mcp/graphql`
- **认证**: API Key（在请求体中传递）
- **Content-Type**: `application/json`

### 基础请求结构

```bash
curl -X POST http://127.0.0.1:8069/api/mcp/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "your-api-key",
    "query": "query { models }"
  }'
```

---

## 📊 基础查询

### 1. 获取可用模型列表

```graphql
query {
  models
}
```

**响应示例**:

```json
{
  "status": "success",
  "data": {
    "models": [
      "res.partner",
      "sale.order", 
      "product.product",
      "account.invoice",
      "..."
    ]
  }
}
```

### 2. 查询记录列表

**基础查询**:

```graphql
query {
  odooRecords(
    model: "res.partner",
    fields: ["name", "email", "phone"],
    limit: 10
  )
}
```

**带条件查询**:

```graphql
query {
  odooRecords(
    model: "res.partner",
    domain: "[('is_company', '=', True)]",
    fields: ["name", "email", "country_id"],
    limit: 5,
    offset: 0,
    order: "name asc"
  )
}
```

### 3. 获取单条记录

```graphql
query {
  odooRecord(
    model: "res.partner",
    id: 14,
    fields: ["name", "email", "phone", "street", "city"]
  )
}
```

### 4. 统计记录数量

```graphql
query {
  odooSearchCount(
    model: "sale.order",
    domain: "[('state', 'in', ['sale', 'done'])]"
  )
}
```

---

## 🔗 嵌套数据查询

### 1. 简单嵌套查询

**Many2One 字段**:

```graphql
query {
  odooRecords(
    model: "sale.order",
    fields: ["name", "date_order", "partner_id", "amount_total"],
    nested_fields: ["partner_id"],
    limit: 5
  )
}
```

**响应示例**:

```json
{
  "data": {
    "odooRecords": [
      {
        "id": 8,
        "name": "SO001",
        "date_order": "2025-01-15 10:30:00",
        "amount_total": 2950.0,
        "partner_id": {
          "id": 14,
          "name": "Agrolait"
        }
      }
    ]
  }
}
```

### 2. One2Many 嵌套查询

```graphql
query {
  odooRecords(
    model: "sale.order",
    fields: ["name", "partner_id", "order_line"],
    nested_fields: ["partner_id", "order_line"],
    max_depth: 2,
    limit: 3
  )
}
```

### 3. 高级嵌套查询（推荐）

**精细控制嵌套字段**:

```graphql
query {
  odooRecordsNested(
    model: "sale.order",
    fields: ["name", "date_order", "state", "amount_total"],
    nested_config: [
      {
        field: "partner_id",
        sub_fields: ["name", "email", "phone", "country_id"]
      },
      {
        field: "order_line",
        sub_fields: ["name", "price_unit", "product_uom_qty", "product_id"],
        max_records: 10
      }
    ],
    domain: "[('state', '!=', 'cancel')]",
    limit: 5
  )
}
```

### 4. 深度嵌套示例

**产品 → 分类 → 父分类**:

```graphql
query {
  odooRecordsNested(
    model: "product.product",
    nested_config: [
      {
        field: "categ_id",
        sub_fields: ["name", "parent_id"]
      }
    ],
    max_depth: 3,
    limit: 10
  )
}
```

---

## ✏️ 数据变更操作

### 1. 创建记录

**创建客户**:

```graphql
mutation {
  createRecord(
    model: "res.partner",
    values: "{\"name\": \"新客户\", \"email\": \"new@example.com\", \"is_company\": true}"
  )
}
```

**创建销售订单**:

```graphql
mutation {
  createRecord(
    model: "sale.order",
    values: "{\"partner_id\": 14, \"date_order\": \"2025-01-20\"}"
  )
}
```

### 2. 更新记录

**更新客户信息**:

```graphql
mutation {
  updateRecord(
    model: "res.partner",
    id: 45,
    values: "{\"phone\": \"+86-138-0013-8000\", \"street\": \"新地址\"}"
  )
}
```

**使用变量（推荐）**:

```graphql
mutation($partnerId: Int!, $updates: JSONString!) {
  updateRecord(
    model: "res.partner",
    id: $partnerId,
    values: $updates
  )
}
```

**变量**:

```json
{
  "partnerId": 45,
  "updates": "{\"phone\": \"+86-138-0013-8000\", \"street\": \"更新的地址\"}"
}
```

### 3. 删除记录

```graphql
mutation {
  deleteRecord(
    model: "res.partner",
    id: 999
  )
}
```

---

## 📋 字段元数据查询

### 1. 获取模型字段信息

```graphql
query {
  model_fields(model: "res.partner") {
    name
    type
    string
    required
    relation
    readonly
    help
    selection_options
  }
}
```

**响应示例**:

```json
{
  "data": {
    "model_fields": [
      {
        "name": "name",
        "type": "char",
        "string": "Name",
        "required": true,
        "relation": null,
        "readonly": false,
        "help": "客户或供应商的名称"
      },
      {
        "name": "country_id",
        "type": "many2one",
        "string": "Country",
        "required": false,
        "relation": "res.country",
        "readonly": false
      },
      {
        "name": "category_id",
        "type": "many2many",
        "string": "Tags",
        "relation": "res.partner.category"
      }
    ]
  }
}
```

### 2. 选择字段选项

```graphql
query {
  model_fields(model: "sale.order") {
    name
    string
    selection_options
  }
}
```

---

## 🔧 高级功能

### 1. 组合查询

**一次查询多种数据**:

```graphql
query {
  partners: odooRecords(
    model: "res.partner",
    domain: "[('is_company', '=', True)]",
    fields: ["name", "email"],
    limit: 5
  )
  
  orders: odooRecords(
    model: "sale.order",
    domain: "[('state', '=', 'sale')]",
    fields: ["name", "partner_id", "amount_total"],
    nested_fields: ["partner_id"],
    limit: 5
  )
  
  orderCount: odooSearchCount(
    model: "sale.order",
    domain: "[('create_date', '>=', '2025-01-01')]"
  )
}
```

### 2. 条件查询示例

**复杂域条件**:

```graphql
query {
  odooRecords(
    model: "sale.order",
    domain: "[('create_date', '>=', '2025-01-01'), ('state', 'in', ['sale', 'done']), ('amount_total', '>', 1000)]",
    fields: ["name", "partner_id", "amount_total", "create_date"],
    nested_fields: ["partner_id"],
    order: "amount_total desc",
    limit: 10
  )
}
```

### 3. 分页查询

**第一页**:

```graphql
query {
  odooRecords(
    model: "res.partner",
    fields: ["name", "email"],
    limit: 20,
    offset: 0,
    order: "name asc"
  )
}
```

**第二页**:

```graphql
query {
  odooRecords(
    model: "res.partner",
    fields: ["name", "email"],
    limit: 20,
    offset: 20,
    order: "name asc"
  )
}
```

---

## ❌ 错误处理

### 1. 常见错误类型

**401 未授权**:

```json
{
  "status": "error",
  "code": 401,
  "message": "Unauthorized"
}
```

**模型不存在**:

```json
{
  "status": "error",
  "errors": ["Model 'invalid.model' not found"]
}
```

**字段错误**:

```json
{
  "status": "error", 
  "errors": ["Field 'invalid_field' does not exist in model 'res.partner'"]
}
```

### 2. 错误处理最佳实践

```javascript
// JavaScript 示例
async function queryGraphQL(query, variables = {}) {
  try {
    const response = await fetch('/api/mcp/graphql', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        api_key: 'your-api-key',
        query: query,
        variables: variables
      })
    });
    
    const result = await response.json();
    
    if (result.status === 'error') {
      console.error('GraphQL Error:', result.message || result.errors);
      return null;
    }
    
    return result.data;
  } catch (error) {
    console.error('Network Error:', error);
    return null;
  }
}
```

---

## ⚡ 性能优化

### 1. 字段选择优化

**❌ 避免**:

```graphql
# 不指定字段，可能返回大量不需要的数据
query {
  odooRecords(model: "res.partner")
}
```

**✅ 推荐**:

```graphql
# 明确指定需要的字段
query {
  odooRecords(
    model: "res.partner",
    fields: ["name", "email", "phone"]
  )
}
```

### 2. 嵌套深度控制

```graphql
query {
  odooRecordsNested(
    model: "sale.order",
    nested_config: [
      {
        field: "order_line",
        sub_fields: ["name", "price_unit"],  # 限制子字段
        max_records: 5  # 限制记录数量
      }
    ],
    max_depth: 2,  # 限制嵌套深度
    limit: 10
  )
}
```

### 3. 分页和限制

```graphql
query {
  odooRecords(
    model: "product.product",
    fields: ["name", "default_code"],
    limit: 50,  # 合理的分页大小
    offset: 0
  )
}
```

---

## 🎯 实际应用场景

### 1. 客户管理系统

**客户列表页**:

```graphql
query {
  customers: odooRecords(
    model: "res.partner",
    domain: "[('is_company', '=', True), ('customer_rank', '>', 0)]",
    fields: ["name", "email", "phone", "country_id"],
    nested_fields: ["country_id"],
    order: "name asc",
    limit: 50
  )
  
  customerCount: odooSearchCount(
    model: "res.partner",
    domain: "[('is_company', '=', True), ('customer_rank', '>', 0)]"
  )
}
```

**客户详情页**:

```graphql
query($customerId: Int!) {
  customer: odooRecord(
    model: "res.partner",
    id: $customerId,
    nested_fields: ["country_id", "state_id", "category_id"],
    max_depth: 2
  )
  
  orders: odooRecords(
    model: "sale.order",
    domain: "[('partner_id', '=', " + $customerId + ")]",
    fields: ["name", "date_order", "state", "amount_total"],
    order: "date_order desc",
    limit: 10
  )
}
```

### 2. 销售订单管理

**订单列表**:

```graphql
query {
  orders: odooRecordsNested(
    model: "sale.order",
    fields: ["name", "date_order", "state", "amount_total"],
    nested_config: [
      {
        field: "partner_id",
        sub_fields: ["name", "email"]
      },
      {
        field: "user_id",
        sub_fields: ["name"]
      }
    ],
    domain: "[('state', 'not in', ['draft', 'cancel'])]",
    order: "date_order desc",
    limit: 20
  )
}
```

**订单详情**:

```graphql
query($orderId: Int!) {
  order: odooRecordsNested(
    model: "sale.order",
    nested_config: [
      {
        field: "partner_id",
        sub_fields: ["name", "email", "phone", "street", "city", "country_id"]
      },
      {
        field: "order_line",
        sub_fields: ["name", "product_id", "price_unit", "product_uom_qty", "price_subtotal"],
        max_records: 50
      }
    ],
    domain: "[('id', '=', " + $orderId + ")]",
    max_depth: 3
  )
}
```

### 3. 产品目录

**产品列表**:

```graphql
query($categoryId: Int, $searchTerm: String) {
  products: odooRecordsNested(
    model: "product.product",
    fields: ["name", "default_code", "list_price", "qty_available"],
    nested_config: [
      {
        field: "categ_id",
        sub_fields: ["name"]
      }
    ],
    domain: "[('sale_ok', '=', True)]",  # 动态域构建
    limit: 24
  )
  
  categories: odooRecords(
    model: "product.category",
    fields: ["name", "parent_id"],
    nested_fields: ["parent_id"]
  )
}
```

### 4. 创建销售订单

```graphql
mutation($orderData: JSONString!) {
  order: createRecord(
    model: "sale.order",
    values: $orderData
  )
}
```

**变量**:

```json
{
  "orderData": "{\"partner_id\": 14, \"date_order\": \"2025-01-20\", \"order_line\": [[0, 0, {\"product_id\": 25, \"product_uom_qty\": 2, \"price_unit\": 1500}]]}"
}
```

### 5. 仪表板数据

**销售仪表板**:

```graphql
query {
  # 本月销售额
  monthlyRevenue: odooSearchCount(
    model: "sale.order",
    domain: "[('date_order', '>=', '2025-01-01'), ('date_order', '<', '2025-02-01'), ('state', 'in', ['sale', 'done'])]"
  )
  
  # 热门产品
  topProducts: odooRecords(
    model: "product.product",
    fields: ["name", "sales_count"],
    order: "sales_count desc",
    limit: 5
  )
  
  # 最近订单
  recentOrders: odooRecordsNested(
    model: "sale.order",
    fields: ["name", "date_order", "amount_total"],
    nested_config: [
      {
        field: "partner_id",
        sub_fields: ["name"]
      }
    ],
    order: "date_order desc",
    limit: 10
  )
}
```

---

## 📝 最佳实践总结

### 1. 查询优化

- ✅ 始终指定需要的字段
- ✅ 使用合理的 limit 和分页
- ✅ 控制嵌套深度和记录数量
- ✅ 使用索引字段进行排序和过滤

### 2. 错误处理

- ✅ 检查响应状态和错误信息
- ✅ 实现重试机制
- ✅ 提供用户友好的错误提示

### 3. 安全性

- ✅ 妥善保管 API Key
- ✅ 验证输入数据
- ✅ 使用 HTTPS 传输

### 4. 性能监控

- ✅ 监控查询执行时间
- ✅ 记录慢查询日志
- ✅ 优化频繁查询

---

**文档版本**: v1.1+  
**最后更新**: 2025-09-27  
**适用于**: MCP 服务器 GraphQL API
