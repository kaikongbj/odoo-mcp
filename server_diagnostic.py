#!/usr/bin/env python3
"""
FastMCP 服务器监控和诊断工具
用于监控服务器状态并提供诊断信息
"""

import json
from datetime import datetime

import requests


def check_server_health(host="localhost", port=10888):
    """检查服务器健康状态"""
    print(f"\n=== FastMCP 服务器健康检查 ===")
    print(f"时间: {datetime.now()}")
    print(f"检查地址: http://{host}:{port}")

    # 检查基本连通性
    try:
        # 尝试连接 SSE 端点
        sse_url = f"http://{host}:{port}/sse"
        print(f"\n1. 检查 SSE 端点: {sse_url}")

        response = requests.get(sse_url, timeout=5, stream=True)
        print(f"   响应状态码: {response.status_code}")
        print(f"   响应头: {dict(response.headers)}")

        if response.status_code == 200:
            print("   ✅ SSE 端点可访问")
        else:
            print(f"   ❌ SSE 端点返回错误状态码: {response.status_code}")

    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ 连接错误: {e}")
    except requests.exceptions.Timeout as e:
        print(f"   ❌ 超时错误: {e}")
    except Exception as e:
        print(f"   ❌ 其他错误: {e}")

    # 检查消息端点
    try:
        msg_url = f"http://{host}:{port}/messages/"
        print(f"\n2. 检查消息端点: {msg_url}")

        # 创建测试会话
        session_id = "health_check_session"
        test_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "health_checker",
                    "version": "1.0.0"
                }
            }
        }

        response = requests.post(
            f"{msg_url}?session_id={session_id}",
            json=test_data,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )

        print(f"   响应状态码: {response.status_code}")

        if response.status_code == 202:
            print("   ✅ 消息端点接受请求")
        elif response.status_code == 200:
            print("   ✅ 消息端点直接处理请求")
            try:
                result = response.json()
                print(f"   响应内容: {json.dumps(result, indent=2)}")
            except:
                print(f"   响应内容: {response.text}")
        else:
            print(f"   ❌ 消息端点返回错误状态码: {response.status_code}")
            print(f"   响应内容: {response.text}")

    except Exception as e:
        print(f"   ❌ 消息端点测试失败: {e}")


def monitor_server_logs():
    """监控服务器日志（简化版本）"""
    print(f"\n=== 服务器监控建议 ===")
    print("1. 检查 Odoo 日志中的 FastMCP 相关错误")
    print("2. 监控端口 10888 的网络连接")
    print("3. 检查防火墙设置")
    print("4. 验证 FastMCP 版本兼容性")

    print(f"\n=== 常见错误解决方案 ===")
    print("1. ExceptionGroup 错误:")
    print("   - 这通常是 FastMCP 内部的异步任务管理问题")
    print("   - 尝试重启 Odoo 服务")
    print("   - 检查 FastMCP 版本是否与 MCP 协议版本兼容")

    print("2. SSE 连接错误:")
    print("   - 检查客户端是否正确实现 SSE 协议")
    print("   - 验证请求头是否正确设置")
    print("   - 尝试使用不同的传输模式")


def run_diagnostic():
    """运行完整诊断"""
    print("FastMCP 服务器诊断工具")
    print("=" * 50)

    # 检查服务器健康
    check_server_health()

    # 提供监控建议
    monitor_server_logs()

    print(f"\n=== 诊断完成 ===")
    print("如果问题持续存在，请检查:")
    print("1. Odoo 服务器日志")
    print("2. FastMCP 版本兼容性")
    print("3. 网络配置和防火墙设置")


if __name__ == "__main__":
    run_diagnostic()
