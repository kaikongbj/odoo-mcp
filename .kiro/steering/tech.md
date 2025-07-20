# 技术栈

## 框架和平台

- **Odoo 17**：主要ERP框架
- **Python 3.10+**：编程语言
- **FastMCP 2.4.0+**：MCP协议实现框架
- **Uvicorn 0.24.0+**：用于异步操作的ASGI服务器

## 架构模式

- **MVC模式**：遵循Odoo标准的模型-视图-控制器架构
- **异步/等待**：广泛使用asyncio处理MCP协议
- **多线程**：为FastMCP集成管理后台事件循环
- **单例模式**：FastMCP服务使用单例进行实例管理

## 关键依赖

```
fastmcp>=2.4.0
uvicorn>=0.24.0
```

## Odoo模块结构

- **模型**：`mcp.server`和`mcp.resource`，集成邮件功能
- **控制器**：带API密钥认证的RESTful API端点
- **服务**：FastMCP集成服务，支持异步工具/资源注册
- **视图**：基于XML的服务器和资源管理UI定义
- **安全**：通过`ir.model.access.csv`进行访问控制

## 常用命令

### 安装

```bash
pip install -r requirements.txt
```

### Odoo模块管理

```bash
# 更新模块列表并安装
odoo-bin -u mcp_server -d your_database

# 开发模式，支持自动重载
odoo-bin --dev=reload,qweb,werkzeug,xml
```

### 测试

```bash
# 运行特定测试文件
python test_mcp_server.py
python test_fastmcp_api.py
python test_final_integration.py
```

## API认证

所有API端点都使用`auth='api_key'`，需要在Odoo中正确配置API密钥。
