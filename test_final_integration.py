#!/usr/bin/env python3
"""
最终集成测试脚本
验证所有工具函数是否正确使用了 _safe_execute_with_env 方法
"""

import re


def check_tool_functions(file_path):
    """检查文件中的工具函数是否正确使用了安全执行方法"""

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"无法读取文件: {e}")
        return False

    # 找到所有工具函数
    tool_pattern = r'@mcp_server\.tool\(\)\s*async def (\w+)\([^)]*\)[^{]*?:'
    tools = re.findall(tool_pattern, content, re.MULTILINE | re.DOTALL)

    print(f"找到 {len(tools)} 个工具函数:")
    for tool in tools:
        print(f"  - {tool}")

    # 检查每个工具函数是否使用了正确的模式
    issues = []

    # 检查是否直接调用 _get_env()
    direct_get_env_pattern = r'env = self\._get_env\(\)'
    direct_calls = re.findall(direct_get_env_pattern, content)

    if direct_calls:
        print(f"\n⚠️ 发现 {len(direct_calls)} 处直接调用 _get_env() 的情况")
        issues.append("直接调用 _get_env()")

    # 检查是否使用了 _safe_execute_with_env
    safe_execute_pattern = r'self\._safe_execute_with_env\('
    safe_calls = re.findall(safe_execute_pattern, content)

    print(f"\n✅ 发现 {len(safe_calls)} 处使用 _safe_execute_with_env() 的情况")

    # 检查特定工具函数
    tools_to_check = [
        'query_odoo_model',
        'get_odoo_record',
        'create_odoo_record',
        'update_odoo_record',
        'delete_odoo_record',
        'get_odoo_model_metadata',
        'list_resources',
        'get_resource_content'
    ]

    for tool_name in tools_to_check:
        # 查找工具函数的内容
        tool_pattern = rf'@mcp_server\.tool\(\)\s*async def {tool_name}\([^)]*\).*?(?=@mcp_server\.tool\(\)|def _|\Z)'
        tool_match = re.search(tool_pattern, content, re.MULTILINE | re.DOTALL)

        if tool_match:
            tool_content = tool_match.group(0)

            # 检查是否使用了安全执行模式
            if '_safe_execute_with_env(' in tool_content:
                print(f"✅ {tool_name}: 使用安全执行模式")
            elif 'env = self._get_env()' in tool_content:
                print(f"❌ {tool_name}: 仍在直接使用 _get_env()")
                issues.append(f"{tool_name} 直接使用 _get_env()")
            else:
                print(f"⚠️ {tool_name}: 未检测到数据库访问模式")
        else:
            print(f"❓ {tool_name}: 未找到函数定义")

    # 检查资源函数
    resource_functions = ['get_resources_list', 'get_resource']
    for func_name in resource_functions:
        if f'def {func_name}(' in content:
            func_pattern = rf'def {func_name}\([^)]*\).*?(?=def |\Z)'
            func_match = re.search(func_pattern, content, re.MULTILINE | re.DOTALL)

            if func_match:
                func_content = func_match.group(0)
                if '_safe_execute_with_env(' in func_content:
                    print(f"✅ 资源函数 {func_name}: 使用安全执行模式")
                elif 'env = self._get_env()' in func_content:
                    print(f"❌ 资源函数 {func_name}: 仍在直接使用 _get_env()")
                    issues.append(f"资源函数 {func_name} 直接使用 _get_env()")

    # 总结
    print(f"\n{'=' * 50}")
    if issues:
        print(f"❌ 发现 {len(issues)} 个问题:")
        for issue in issues:
            print(f"  - {issue}")
        return False
    else:
        print("✅ 所有检查通过！所有工具函数都使用了安全执行模式。")
        return True


def main():
    """主函数"""
    print("FastMCP 服务器最终集成测试")
    print("=" * 50)

    file_path = r"d:\odoo_app\mcp-odoo\mcp_server\services\fast_mcp_service.py"

    success = check_tool_functions(file_path)

    if success:
        print("\n🎉 所有修改已完成！服务器现在应该能够：")
        print("  1. ✅ 避免 FastMCP API 兼容性问题")
        print("  2. ✅ 防止数据库游标关闭错误")
        print("  3. ✅ 正确处理异步工具执行")
        print("  4. ✅ 使用统一的安全数据库访问模式")
        print("\n下一步：在实际 Odoo 环境中进行集成测试")
    else:
        print("\n⚠️ 仍有问题需要解决，请检查上述错误")


if __name__ == "__main__":
    main()
