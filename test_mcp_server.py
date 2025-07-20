#!/usr/bin/env python3
"""
测试 MCP 服务器启动和基本功能
"""

import asyncio

from fastmcp import FastMCP, Context


class MockRequest:
    """模拟 Odoo request 对象"""

    def __init__(self):
        self.env = None
        self.db = "test_db"


class MockEnv:
    """模拟 Odoo 环境"""

    def __init__(self):
        self.cr = MockCursor()

    def __contains__(self, model_name):
        # 模拟一些常见的 Odoo 模型
        return model_name in ['res.partner', 'product.template', 'sale.order']


class MockCursor:
    """模拟数据库游标"""

    def __init__(self):
        self.closed = False

    def commit(self):
        print("Mock cursor: commit")

    def rollback(self):
        print("Mock cursor: rollback")

    def close(self):
        print("Mock cursor: close")
        self.closed = True


def mock_get_env():
    """模拟获取环境的方法"""
    print("获取模拟环境")
    return MockEnv()


def mock_safe_execute_with_env(func, *args, **kwargs):
    """模拟安全执行方法"""
    try:
        env = mock_get_env()
        result = func(env, *args, **kwargs)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def test_fastmcp_tools():
    """测试 FastMCP 工具注册和执行"""
    print("=== 测试 FastMCP 工具注册和执行 ===")

    # 创建 FastMCP 实例
    mcp_server = FastMCP(name="test-server")

    # 注册一个测试工具，模拟查询 Odoo 模型的工具
    @mcp_server.tool()
    async def query_odoo_model(
            model_name: str,
            domain: str = None,
            fields: str = None,
            limit: int = 100,
            ctx: Context = None
    ):
        """查询 Odoo 模型的模拟实现"""
        print(f"执行工具: query_odoo_model, 模型: {model_name}")

        if ctx:
            await ctx.info(f"开始查询模型 '{model_name}'")

        def execute_query(env):
            if model_name not in env:
                return {"status": "error", "message": f"模型 '{model_name}' 不存在"}

            # 模拟查询结果
            records = [
                {"id": 1, "name": "测试记录1"},
                {"id": 2, "name": "测试记录2"}
            ]

            return {
                "status": "success",
                "data": {
                    "model": model_name,
                    "count": len(records),
                    "records": records
                }
            }

        # 使用模拟的安全执行方法
        result = mock_safe_execute_with_env(execute_query)

        if ctx and result.get("status") == "success":
            await ctx.info(f"查询成功，返回 {result['data']['count']} 条记录")

        return result

    # 测试工具是否正确注册
    print("检查工具注册...")
    tools = await mcp_server.get_tools()
    print(f"注册的工具数量: {len(tools)}")

    for tool_name in tools:
        print(f"- 工具名称: {tool_name}")
        # 尝试获取工具详细信息
        try:
            tool_info = mcp_server._tool_manager.get_tool(tool_name)
            print(f"  描述: {tool_info.description}")
        except Exception as e:
            print(f"  获取工具信息失败: {e}")

    # 测试工具执行
    print("\n测试工具执行...")

    try:
        # 模拟工具调用
        result = await mcp_server._tool_manager.call_tool(
            "query_odoo_model",
            {"model_name": "res.partner", "limit": 10}
        )
        print(f"工具执行结果: {result}")

        # 测试不存在的模型
        result2 = await mcp_server._tool_manager.call_tool(
            "query_odoo_model",
            {"model_name": "nonexistent.model"}
        )
        print(f"错误情况测试结果: {result2}")

    except Exception as e:
        print(f"工具执行失败: {e}")
        import traceback
        traceback.print_exc()


async def test_server_startup():
    """测试服务器启动流程"""
    print("\n=== 测试服务器启动流程 ===")

    # 创建服务器实例
    mcp_server = FastMCP(name="test-startup")

    # 注册简单工具
    @mcp_server.tool()
    async def simple_tool(message: str, ctx: Context = None):
        """简单的测试工具"""
        if ctx:
            await ctx.info(f"收到消息: {message}")
        return {"status": "success", "message": f"处理了消息: {message}"}

    print("服务器实例创建成功")
    print(f"服务器名称: {mcp_server.name}")

    # 检查工具
    tools = await mcp_server.get_tools()
    print(f"工具数量: {len(tools)}")

    return True


def test_cursor_management():
    """测试游标管理"""
    print("\n=== 测试游标管理 ===")

    cursor = MockCursor()
    print(f"游标初始状态 - closed: {cursor.closed}")

    try:
        # 模拟正常操作
        print("执行正常操作...")
        cursor.commit()
        print("操作成功")
    except Exception as e:
        print(f"操作失败: {e}")
        cursor.rollback()
    finally:
        cursor.close()
        print(f"游标最终状态 - closed: {cursor.closed}")


async def main():
    """主测试函数"""
    print("开始 MCP 服务器功能测试")
    print("=" * 50)

    # 测试工具注册和执行
    await test_fastmcp_tools()

    # 测试服务器启动
    await test_server_startup()

    # 测试游标管理
    test_cursor_management()

    print("\n" + "=" * 50)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
