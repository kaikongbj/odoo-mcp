# MCP服务器模块说明文档

## 项目概述

MCP服务器模块是一个基于Odoo 17和Python
3.10开发的模块，用于管理和提供MCP（模型上下文协议）服务。该模块集成了FastMCP框架，可以方便地创建、管理和与大型语言模型(LLM)
交互的MCP服务器。

## 主要功能

1. **MCP服务器管理**
    - 创建和配置MCP服务器
    - 激活/停用服务器
    - 测试服务器连接
    - 管理服务器状态

2. **资源管理**
    - 创建和管理MCP资源
    - 支持多种资源类型（文件、服务、API等）
    - 资源内容检索和更新

3. **FastMCP集成**
    - 基于FastMCP框架提供标准MCP协议实现
    - 提供工具和资源注册机制
    - 支持异步操作和事件处理

4. **API接口**
    - RESTful API接口，支持外部系统集成
    - JSON格式数据交换
    - 支持服务器和资源管理

## 技术架构

```
mcp_server/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py
├── models/
│   ├── __init__.py
│   └── mcp_server.py
├── services/
│   ├── __init__.py
│   └── fast_mcp_service.py
├── views/
│   └── mcp_server_views.xml
├── security/
│   └── ir.model.access.csv
├── data/
│   └── mcp_server_data.xml
└── static/
    └── description/
        ├── icon.png
        └── index.html
```

### 核心组件

1. **MCP服务器模型** (`models/mcp_server.py`)
    - `mcp.server`: 管理MCP服务器配置和状态
    - `mcp.resource`: 管理MCP资源

2. **FastMCP服务** (`services/fast_mcp_service.py`)
    - `FastMCPService`: 实现FastMCP框架集成
    - 管理FastMCP服务器实例
    - 注册工具和资源

3. **控制器** (`controllers/main.py`)
    - 提供RESTful API接口
    - 处理外部请求
    - 代理FastMCP服务

4. **视图** (`views/mcp_server_views.xml`)
    - 定义用户界面
    - 提供服务器和资源管理界面

## 安装要求

- Odoo 17
- Python 3.10+
- FastMCP 2.0+

## 安装步骤

1. 确保满足安装要求
2. 安装必要的Python依赖:
   ```
   pip install -r requirements.txt
   ```
3. 将`mcp_server`目录复制到Odoo的addons路径
4. 更新Odoo模块列表并安装MCP服务器模块

## 使用指南

### 基本使用

1. **创建MCP服务器**
    - 导航到MCP服务器 > 服务器菜单
    - 点击"创建"按钮
    - 填写服务器名称、URL和其他必要信息
    - 保存服务器记录

2. **激活服务器**
    - 在服务器表单页面，点击"激活"按钮
    - 系统将启动FastMCP服务器实例
    - 服务器状态将变为"活动"

3. **创建资源**
    - 导航到MCP服务器 > 资源菜单
    - 点击"创建"按钮
    - 选择服务器，填写资源名称、URI和类型
    - 保存资源记录

4. **测试连接**
    - 在服务器表单页面，点击"测试连接"按钮
    - 系统将测试与FastMCP服务器的连接
    - 显示测试结果

### API使用

MCP服务器模块提供以下API接口：

1. **获取服务器列表**
    - URL: `/api/mcp/servers`
    - 方法: GET
    - 认证: API密钥
    - 返回: 服务器列表JSON

2. **获取资源列表**
    - URL: `/api/mcp/resources`
    - 方法: GET
    - 参数: server_id (可选)
    - 认证: API密钥
    - 返回: 资源列表JSON

3. **获取资源内容**
    - URL: `/api/mcp/resource/<resource_id>`
    - 方法: GET
    - 认证: API密钥
    - 返回: 资源内容JSON

4. **FastMCP代理**
    - URL: `/api/mcp/server/<server_id>/fastmcp`
    - 方法: GET/POST
    - 认证: API密钥
    - 返回: FastMCP响应

5. **启动FastMCP服务器**
    - URL: `/api/mcp/server/<server_id>/start`
    - 方法: POST
    - 认证: API密钥
    - 返回: 操作结果JSON

6. **停止FastMCP服务器**
    - URL: `/api/mcp/server/<server_id>/stop`
    - 方法: POST
    - 认证: API密钥
    - 返回: 操作结果JSON

### FastMCP使用

FastMCP框架允许您注册工具和资源，以供大型语言模型(LLM)使用。

**工具示例**:

```python
@mcp_server.tool()
async def multiply(a: float, b: float, ctx: Context) -> float:
    """将两个数字相乘"""
    result = a * b
    await ctx.info(f"计算结果: {a} * {b} = {result}")
    return result
```

**资源示例**:

```python
@mcp_server.resource("config://settings")
def get_settings():
    """获取配置设置"""
    return {
        "version": "1.0",
        "max_connections": 100,
        "timeout": 30
    }
```

## 高级配置

### 自定义工具

您可以在`fast_mcp_service.py`中的`_register_default_tools`方法中添加自定义工具:

```python
@mcp_server.tool()
async def custom_tool(param1: str, param2: int, ctx: Context) -> Dict[str, Any]:
    """自定义工具说明"""
    # 工具实现...
    return {"result": "..."}
```

### 自定义资源

您可以在`fast_mcp_service.py`中的`_register_default_resources`方法中添加自定义资源:

```python
@mcp_server.resource("custom://resource/{param}")
def custom_resource(param: str):
    """自定义资源说明"""
    # 资源实现...
    return {"data": "..."}
```

## 故障排除

### 常见问题

1. **无法启动FastMCP服务器**
    - 确认FastMCP库已正确安装
    - 检查服务器URL格式是否正确
    - 查看Odoo日志获取详细错误信息

2. **API调用失败**
    - 确认API密钥正确
    - 确认服务器处于活动状态
    - 检查请求格式和参数

3. **资源获取失败**
    - 确认资源存在且激活
    - 确认资源URI格式正确
    - 检查资源类型是否支持

## 开发指南

### 扩展模型

1. 在`models`目录下创建新的模型文件
2. 在`__init__.py`中导入新模型
3. 添加必要的字段和方法
4. 更新安全访问规则

### 添加API接口

1. 在`controllers/main.py`中添加新的路由方法
2. 实现请求处理逻辑
3. 返回适当的JSON响应

### 集成新功能

1. 根据需求修改现有模型或添加新模型
2. 更新视图以支持新功能
3. 添加必要的业务逻辑
4. 更新文档和测试

## 版本历史

- 1.0.0 (2025-05-23): 初始版本
    - 基本MCP服务器管理功能
    - FastMCP集成
    - API接口

## 联系与支持

如有问题或需要支持，请联系:

- 技术支持: support@example.com
- 项目维护: dev@example.com

## 许可证

本模块基于LGPL-3许可证发布。详见LICENSE文件。
