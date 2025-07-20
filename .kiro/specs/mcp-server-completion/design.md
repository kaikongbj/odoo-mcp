# MCP服务器模块完善设计文档

## 概述

本设计文档描述了如何完善MCP服务器模块的关键技术问题，确保系统达到生产就绪状态。重点解决数据库访问安全性、异步操作稳定性和测试覆盖等问题。

## 架构设计

### 1. 安全数据库访问架构

#### 设计原则

- **线程安全**：每个异步操作使用独立的数据库连接
- **资源管理**：自动管理数据库游标的生命周期
- **异常处理**：确保异常情况下资源正确释放
- **性能优化**：复用连接池，避免频繁创建连接

#### 核心组件

```python
class SafeDatabaseManager:
    """安全数据库管理器"""
    
    def __init__(self):
        self.connection_pool = {}
        self.lock = threading.Lock()
    
    async def execute_with_env(self, operation, *args, **kwargs):
        """安全执行数据库操作"""
        # 创建独立连接
        # 执行操作
        # 自动清理资源
```

### 2. FastMCP工具函数重构

#### 当前问题

- 直接使用`self._get_env()`可能导致游标关闭错误
- 缺少统一的错误处理机制
- 异步操作中的资源管理不当

#### 解决方案

```python
# 重构前
async def query_odoo_model(self, model_name, domain=None):
    env = self._get_env()  # 不安全
    records = env[model_name].search_read(domain)
    return records

# 重构后
async def query_odoo_model(self, model_name, domain=None):
    return await self._safe_execute_with_env(
        self._query_odoo_model_impl,
        model_name, domain
    )
```

### 3. 异步事件循环优化

#### 当前架构

```
主线程 -> FastMCP服务 -> 后台事件循环线程 -> 数据库操作
```

#### 优化设计

- **连接池管理**：为每个线程维护独立的连接池
- **任务队列**：使用队列管理异步任务，避免阻塞
- **超时控制**：为长时间运行的操作设置超时
- **资源监控**：监控连接使用情况，及时释放资源

### 4. 错误处理和日志系统

#### 分层错误处理

1. **API层**：统一的HTTP错误响应格式
2. **服务层**：业务逻辑错误处理和转换
3. **数据层**：数据库操作错误捕获和恢复

#### 日志记录策略

```python
# 结构化日志记录
_logger.info("MCP工具调用", extra={
    'tool_name': tool_name,
    'server_id': server_id,
    'execution_time': execution_time,
    'status': 'success'
})
```

## 数据模型

### 现有模型保持不变

- `mcp.server`：服务器管理模型
- `mcp.resource`：资源管理模型

### 新增配置选项

```python
# 在MCPServer模型中添加
connection_timeout = fields.Integer('连接超时', default=30)
max_concurrent_requests = fields.Integer('最大并发请求', default=10)
enable_debug_logging = fields.Boolean('启用调试日志', default=False)
```

## 组件和接口

### 1. SafeDatabaseManager类

```python
class SafeDatabaseManager:
    """安全数据库管理器"""
    
    async def execute_with_env(self, operation, *args, **kwargs):
        """安全执行数据库操作"""
        
    def get_connection(self, db_name):
        """获取数据库连接"""
        
    def release_connection(self, connection):
        """释放数据库连接"""
```

### 2. FastMCPService重构

```python
class FastMCPService:
    """重构后的FastMCP服务"""
    
    def __init__(self):
        self.db_manager = SafeDatabaseManager()
        self.performance_monitor = PerformanceMonitor()
    
    async def _safe_execute_with_env(self, operation, *args, **kwargs):
        """安全执行数据库操作的统一入口"""
```

### 3. 性能监控组件

```python
class PerformanceMonitor:
    """性能监控组件"""
    
    def start_timing(self, operation_name):
        """开始计时"""
        
    def end_timing(self, operation_name):
        """结束计时并记录"""
        
    def get_metrics(self):
        """获取性能指标"""
```

## 错误处理策略

### 1. 分类错误处理

#### 数据库错误

- **连接错误**：自动重试机制
- **查询错误**：参数验证和错误转换
- **事务错误**：自动回滚和清理

#### MCP协议错误

- **工具调用错误**：标准化错误响应
- **资源访问错误**：权限检查和错误提示
- **超时错误**：优雅的超时处理

### 2. 错误恢复机制

```python
async def with_retry(operation, max_retries=3):
    """带重试的操作执行"""
    for attempt in range(max_retries):
        try:
            return await operation()
        except RecoverableError as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # 指数退避
```

## 测试策略

### 1. 单元测试

- **数据库操作测试**：模拟数据库环境
- **异步操作测试**：测试并发场景
- **错误处理测试**：验证异常情况

### 2. 集成测试

- **API端点测试**：完整的请求-响应测试
- **FastMCP工具测试**：端到端工具调用测试
- **性能测试**：负载和压力测试

### 3. 测试环境配置

```python
# 测试配置
TEST_CONFIG = {
    'database_url': 'postgresql://test:test@localhost/test_db',
    'fastmcp_timeout': 5,
    'max_test_records': 100
}
```

## 部署考虑

### 1. 环境要求

- **Python 3.10+**
- **Odoo 17**
- **PostgreSQL 12+**
- **Redis**（用于缓存和会话管理）

### 2. 配置管理

```ini
[mcp_server]
database_pool_size = 20
connection_timeout = 30
max_concurrent_requests = 50
log_level = INFO
```

### 3. 监控和维护

- **健康检查端点**：`/api/mcp/health`
- **性能指标**：响应时间、错误率、并发数
- **日志聚合**：结构化日志便于分析

## 安全考虑

### 1. 数据访问安全

- **权限验证**：每个操作都验证用户权限
- **SQL注入防护**：使用参数化查询
- **数据脱敏**：敏感数据不记录到日志

### 2. API安全

- **API密钥管理**：定期轮换和撤销
- **请求限流**：防止API滥用
- **输入验证**：严格的参数验证

这个设计确保了MCP服务器模块的稳定性、安全性和可维护性，为生产环境部署做好准备。
