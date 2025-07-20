#!/usr/bin/env python3
"""
测试 FastMCP API 和工具管理
"""

from fastmcp import FastMCP

# 创建 FastMCP 实例
mcp = FastMCP('test')

print("=== FastMCP 实例属性检查 ===")
print(f"_tool_manager: {hasattr(mcp, '_tool_manager')}")
print(f"get_tools: {hasattr(mcp, 'get_tools')}")
print(f"_tools: {hasattr(mcp, '_tools')}")


# 注册一个工具
@mcp.tool()
def test_tool(param: str) -> str:
    """测试工具"""
    return f"收到参数: {param}"


print("\n=== 工具注册后检查 ===")
print(f"_tools: {hasattr(mcp, '_tools')}")
print(f"_tool_manager: {type(mcp._tool_manager)}")

# 尝试获取工具
try:
    tools = mcp.get_tools()
    print(f"get_tools() 返回: {tools}")
    print(f"工具数量: {len(tools)}")
    for tool in tools:
        print(f"工具: {tool.name}")
except Exception as e:
    print(f"获取工具失败: {e}")

# 检查工具管理器内部
try:
    if hasattr(mcp._tool_manager, 'tools'):
        print(f"_tool_manager.tools: {mcp._tool_manager.tools}")
    if hasattr(mcp._tool_manager, '_tools'):
        print(f"_tool_manager._tools: {mcp._tool_manager._tools}")
    if hasattr(mcp._tool_manager, 'get_all'):
        print(f"_tool_manager.get_all(): {mcp._tool_manager.get_all()}")
except Exception as e:
    print(f"检查工具管理器失败: {e}")

print(f"\n_tool_manager 属性: {dir(mcp._tool_manager)}")
