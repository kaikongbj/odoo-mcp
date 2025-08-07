# MCP服务器自动启动修复文档

## 问题描述

系统启动时MCP服务器没有自动启动，只有点击"测试连接"按钮时才会启动服务器。这违背了自动启动的设计初衷。

## 问题原因分析

### 1. 钩子执行时机问题

原来的实现使用`post_init_hook`，但这个钩子只在模块安装/升级时执行，而不是每次Odoo启动时执行。

```python
# 问题代码 - 只在模块安装时执行
def post_init_hook(cr, registry):
    # 这里的代码只在模块安装时运行，不是每次启动时运行
    pass
```

### 2. 测试连接方法的副作用

`action_test_connection`方法总是会启动服务器，导致用户误以为只有测试连接才能启动服务器。

```python
# 问题代码 - 总是启动服务器
def action_test_connection(self):
    # 无论服务器是否运行，都会尝试启动
    fastmcp_service.start_server(self)
```

## 解决方案

### 1. 使用模型注册钩子

使用`_register_hook`方法，这个方法在每次Odoo启动时都会执行：

```python
@api.model
def _register_hook(self):
    """在模型注册时调用，用于设置自动启动"""
    super()._register_hook()
    # 在模型注册完成后触发自动启动
    self._auto_start_servers_on_startup()
```

### 2. 实现系统启动时的自动启动

```python
@api.model
def _auto_start_servers_on_startup(self):
    """在系统启动时自动启动活动的MCP服务器"""
    global _auto_start_executed, _auto_start_lock
    
    with _auto_start_lock:
        if _auto_start_executed:
            return  # 确保只执行一次
        _auto_start_executed = True
    
    # 延迟启动逻辑
    def delayed_auto_start():
        time.sleep(3.0)  # 等待系统完全启动
        FastMCPService.auto_start_on_module_init()
    
    # 在后台线程中执行
    threading.Thread(target=delayed_auto_start, daemon=True).start()
```

### 3. 修复测试连接方法

修改测试连接方法，只在服务器未运行时才启动：

```python
def action_test_connection(self):
    # 检查服务器是否已经运行
    server_running = self.id in fastmcp_service.mcp_servers
    
    if not server_running:
        # 只在服务器未运行时才启动
        if fastmcp_service.start_server(self):
            self.write({'state': 'active'})
        else:
            return error_notification
    
    # 测试连接逻辑
```

## 修复内容

### 1. 模型文件修改 (`mcp_server/models/mcp_server.py`)

- **修复导入顺序**：将`import threading`移到文件开头
- 添加全局标志防止重复执行
- 实现`_auto_start_servers_on_startup`方法
- 实现`_register_hook`方法
- 修复`action_test_connection`方法

### 2. 初始化文件修改 (`mcp_server/__init__.py`)

- 简化`post_init_hook`，只处理模块安装后的初始化
- 移除重复的自动启动逻辑

## 执行流程

### 系统启动时

1. **Odoo启动** → 加载模块
2. **模型注册** → 调用`_register_hook`
3. **触发自动启动** → 调用`_auto_start_servers_on_startup`
4. **延迟执行** → 等待3秒确保系统完全启动
5. **查找活动服务器** → 搜索`state='active'`的服务器
6. **批量启动** → 依次启动每个活动服务器
7. **记录日志** → 记录启动成功/失败的服务器

### 测试连接时

1. **检查服务器状态** → 确认是否已在运行
2. **条件启动** → 只在未运行时启动服务器
3. **测试连接** → 验证服务器连接
4. **更新状态** → 更新连接时间和计数

## 日志输出

### 系统启动日志

```
INFO: 系统启动：开始自动启动活动的MCP服务器
INFO: 系统启动：已启动MCP服务器自动启动线程
INFO: 开始延迟自动启动MCP服务器
INFO: 模块初始化：开始自动启动MCP服务器
INFO: 找到 1 个活动状态的MCP服务器
INFO: 正在自动启动MCP服务器: 默认MCP服务器 (ID: 1)
INFO: 开始异步启动MCP服务器: 默认MCP服务器 (端口: 10888)
INFO: 成功自动启动MCP服务器: 默认MCP服务器
INFO: 系统启动：MCP服务器自动启动成功
```

### 测试连接日志

```
INFO: 测试连接时发现服务器已在运行: 默认MCP服务器
INFO: 与MCP服务器的连接测试成功
```

## 验证方法

### 1. 重启Odoo验证

```bash
# 重启Odoo服务
sudo systemctl restart odoo

# 查看日志确认自动启动
tail -f /var/log/odoo/odoo.log | grep "MCP"
```

### 2. 检查服务器状态

1. 重启后立即登录Odoo
2. 导航到 **MCP服务器 > 控制面板**
3. 查看默认服务器状态应为"运行中"
4. 点击"检查状态"确认服务器详细信息

### 3. 测试连接验证

1. 点击"测试连接"按钮
2. 应该显示"连接成功"而不是"服务器已自动启动"
3. 日志应显示"服务器已在运行"而不是启动信息

## 注意事项

1. **导入顺序**: 确保所有导入语句在使用前声明
2. **线程安全**: 使用锁机制防止重复执行自动启动
3. **延迟启动**: 等待3秒确保系统完全初始化
4. **错误处理**: 完善的异常处理和日志记录
5. **状态同步**: 确保数据库状态与实际运行状态一致

## 兼容性

- **向后兼容**: 不影响现有的手动启动功能
- **升级兼容**: 模块升级时会正确处理自动启动
- **多实例兼容**: 支持多个MCP服务器实例的自动启动

## 修复日期

2025-07-22