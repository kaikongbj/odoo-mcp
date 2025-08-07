# MCP服务器自动启动功能文档

## 功能概述

MCP服务器模块现在支持在模块启动时自动启动所有处于"活动"
状态的MCP服务器。每个mcp.server记录都是一个独立的MCP服务器实例，运行在不同的端口上。这确保了在Odoo重启后，之前运行的多个MCP服务器能够自动恢复运行状态。

## 实现原理

### 1. 模块初始化钩子

在`__manifest__.py`中配置了`post_init_hook`，指向`post_init_hook`函数：

```python
'post_init_hook': 'post_init_hook',
```

### 2. 自动启动流程

1. **系统启动时**：Odoo启动并加载模块
2. **模型注册**：调用`_register_hook`方法
3. **触发自动启动**：调用`_auto_start_servers_on_startup`方法
4. **延迟启动**：使用后台线程延迟3秒启动，确保系统完全初始化
5. **查找活动服务器**：自动查找所有状态为"active"的MCP服务器
6. **批量启动**：依次启动找到的每个活动服务器
7. **状态更新**：更新服务器的连接状态和URL信息

### 3. 核心方法

#### `FastMCPService.auto_start_active_servers()`

- 查找所有活动状态的MCP服务器
- 依次启动每个服务器
- 记录启动成功和失败的数量
- 返回是否有服务器成功启动

#### `MCPServer._auto_start_servers_on_startup()`

- 系统启动时调用的模型方法
- 使用全局锁确保只执行一次
- 在后台线程中延迟执行自动启动

#### `MCPServer._register_hook()`

- 模型注册时调用的钩子方法
- 在每次Odoo启动时触发自动启动
- 确保系统启动时自动启动活动服务器

#### `FastMCPService.auto_start_on_module_init()`

- 模块初始化时调用的类方法
- 获取服务实例并调用自动启动方法
- 处理初始化过程中的异常

## 默认配置

### 默认MCP服务器

模块安装时会自动创建多个MCP服务器，每个运行在不同端口：

```xml
<!-- 默认MCP服务器 - 端口10888 -->
<record id="default_mcp_server" model="mcp.server">
    <field name="name">默认MCP服务器</field>
    <field name="server_port">10888</field>
    <field name="server_url">http://127.0.0.1:10888</field>
    <field name="api_key">default_mcp_key_auto_generated</field>
    <field name="state">active</field>
    <field name="note">这是默认的MCP服务器，会在模块启动时自动启动。</field>
</record>

<!-- 演示服务器1 - 端口10889 -->
<record id="demo_mcp_server_1" model="mcp.server">
    <field name="name">演示服务器 1</field>
    <field name="server_port">10889</field>
    <field name="server_url">http://127.0.0.1:10889</field>
    <field name="state">draft</field>
</record>
```

### 默认资源

默认服务器包含以下资源：

1. **Odoo模型访问** (`/odoo/models`)
    - 提供对所有Odoo模型的CRUD操作
    - 支持查询、创建、更新、删除和元数据获取

2. **服务器信息** (`/server/info`)
    - 提供MCP服务器状态和配置信息
    - 包含连接信息和可用功能列表

## 使用方法

### 自动启动

1. **安装模块**：安装MCP服务器模块时，默认服务器会自动创建并设置为活动状态
2. **重启Odoo**：每次Odoo重启后，所有活动状态的MCP服务器都会自动启动
3. **无需手动操作**：用户无需手动激活服务器，系统会自动处理

### 手动控制

如果需要手动控制服务器启动：

1. **停用自动启动**：将服务器状态设置为"草稿"或"不活动"
2. **手动启动**：在服务器表单页面点击"激活"按钮
3. **测试连接**：使用"测试连接"按钮验证服务器状态

## 日志监控

### 启动日志

```
INFO: 开始执行MCP服务器模块初始化钩子
INFO: 开始延迟自动启动MCP服务器
INFO: 找到 1 个活动状态的MCP服务器
INFO: 正在自动启动MCP服务器: 默认MCP服务器 (ID: 1)
INFO: 开始异步启动MCP服务器: 默认MCP服务器 (端口: 10888)
INFO: FastMCP服务器线程已启动，线程名: FastMCP-Server-1-10888
INFO: 成功自动启动MCP服务器: 默认MCP服务器
INFO: 自动启动完成，成功启动 1/1 个MCP服务器
INFO: FastMCP服务器已在 0.0.0.0:10888 启动
```

### 错误处理

如果启动失败，会记录详细的错误信息：

```
ERROR: 自动启动MCP服务器 默认MCP服务器 时发生错误: [错误详情]
WARNING: 自动启动MCP服务器失败: 默认MCP服务器
```

## 配置选项

### 延迟启动时间

在`__init__.py`中可以调整延迟启动时间：

```python
time.sleep(5.0)  # 延迟5秒启动，可根据需要调整
```

### 服务器端口

默认使用端口10888，可以在服务器配置中修改：

```python
port = 10888  # 在fast_mcp_service.py中配置
```

## 故障排除

### 常见问题

1. **服务器未自动启动**
    - 检查服务器状态是否为"active"
    - 查看Odoo日志中的启动信息
    - 确认FastMCP依赖已正确安装

2. **端口冲突**
    - 检查端口10888是否被其他服务占用
    - 修改服务器配置使用不同端口

3. **数据库连接问题**
    - 确认数据库连接正常
    - 检查SafeDatabaseManager的连接池状态

### 调试方法

1. **启用详细日志**：设置日志级别为DEBUG
2. **检查服务器状态**：在MCP服务器列表中查看服务器状态
3. **手动测试**：使用"测试连接"按钮手动验证服务器

## 安全考虑

1. **API密钥**：每个服务器都有唯一的API密钥
2. **访问控制**：通过Odoo的权限系统控制访问
3. **网络安全**：默认只监听本地接口(127.0.0.1)

## 版本兼容性

- **Odoo版本**：17.0+
- **Python版本**：3.10+
- **FastMCP版本**：2.4.0+

## 更新日期

2025-07-22