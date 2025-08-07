# FastMCP *args 参数修复

## 问题描述

在使用FastMCP框架注册工具函数时，遇到以下错误：

```
创建FastMCP服务器实例失败: Functions with *args are not supported as tools
```

这是因为FastMCP不支持使用`*args`参数的函数作为工具。在我们的实现中，`require_auth`装饰器创建了一个使用`*args`
的包装函数，导致FastMCP无法正确处理工具函数。

## 解决方案

我们修改了工具注册方式，不再使用包装函数，而是在每个工具函数内部直接进行认证检查：

1. 移除了使用`*args`的包装函数
2. 创建了一个`check_auth`辅助函数，在每个工具函数内部调用
3. 在每个工具函数开始时添加认证检查逻辑

## 修改示例

修改前：

```python
def require_auth(func):
    async def wrapper(*args, ctx=None, **kwargs):  # 使用了*args，不被FastMCP支持
        auth_result = await self._check_authentication(mcp_server, ctx)
        if auth_result:
            return auth_result
        return await func(*args, ctx=ctx, **kwargs)
    return wrapper

@mcp_server.tool()
@require_auth
async def query_odoo_model(...):
    # 函数实现
```

修改后：

```python
async def check_auth(ctx):
    """检查认证，返回错误或None"""
    return await self._check_authentication(mcp_server, ctx)

@mcp_server.tool()
async def query_odoo_model(...):
    # 检查认证
    auth_result = await check_auth(ctx)
    if auth_result:
        return auth_result
    
    # 函数实现
```

## 注意事项

1. 所有工具函数都需要添加认证检查逻辑
2. 确保认证检查是函数中的第一个操作
3. 避免在FastMCP工具函数中使用`*args`参数