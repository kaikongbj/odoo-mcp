# 项目结构

## 根目录

- **README.md**：中文综合文档
- **requirements.txt**：Python依赖（fastmcp, uvicorn）
- **task.md**：空任务文件
- 各种测试文件（`test_*.py`）用于不同组件
- 诊断和完成报告文件

## 主模块：`mcp_server/`

### 核心文件

- `__init__.py`：模块初始化
- `__manifest__.py`：Odoo插件清单，依赖'base'和'mail'

### 模型（`models/`）

- `mcp_server.py`：核心模型
  - `MCPServer`：主服务器管理，包含状态（草稿/活动/不活动）
  - `MCPResource`：资源管理，包含类型（文件/服务/API/其他）
  - 两者都继承自`mail.thread`和`mail.activity.mixin`

### 控制器（`controllers/`）

- `main.py`：RESTful API端点
  - `/api/mcp/servers` - 服务器列表
  - `/api/mcp/resources` - 资源管理
  - `/api/mcp/server/<id>/fastmcp` - FastMCP代理
  - `/api/mcp/server/<id>/start|stop` - 服务器控制

### 服务（`services/`）

- `fast_mcp_service.py`：FastMCP集成
  - 单例服务类
  - 异步事件循环管理
  - Odoo数据访问工具注册
  - MCP协议资源注册

### 视图（`views/`）

- `mcp_server_views.xml`：完整UI定义
  - 带状态栏的服务器和资源表单
  - 带装饰的树视图
  - 带过滤器和分组的搜索视图
  - "MCP服务器"下的菜单结构

### 安全（`security/`）

- `ir.model.access.csv`：访问控制定义

### 数据（`data/`）

- `mcp_server_data.xml`：初始数据设置

### 静态文件（`static/description/`）

- `icon.png`：模块图标
- `index.html`：模块描述页面

## 命名约定

- 模型使用下划线记法（`mcp.server`，`mcp.resource`）
- 全程使用中文字段标签和UI文本
- API端点遵循RESTful模式
- 文件名统一使用snake_case

## 关键关系

- `mcp.resource`与`mcp.server`有Many2one关系
- 两个模型都通过`active`字段支持归档
- 邮件集成提供聊天功能
- 通过选择字段和适当工作流进行状态管理
