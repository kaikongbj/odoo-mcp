import requests


def check_server():
    print("=== FastMCP 服务器状态检查 ===")

    # 检查 SSE 端点
    try:
        response = requests.get("http://localhost:10888/sse", timeout=5)
        print(f"SSE 端点状态: {response.status_code}")
        if response.status_code == 200:
            print("✅ SSE 端点正常")
        else:
            print("❌ SSE 端点异常")
    except Exception as e:
        print(f"❌ SSE 连接失败: {e}")

    # 检查消息端点
    try:
        test_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}
            }
        }

        response = requests.post(
            "http://localhost:10888/messages/?session_id=test",
            json=test_msg,
            timeout=10
        )
        print(f"消息端点状态: {response.status_code}")

        if response.status_code in [200, 202]:
            print("✅ 消息端点正常")
        else:
            print("❌ 消息端点异常")

    except Exception as e:
        print(f"❌ 消息测试失败: {e}")


if __name__ == "__main__":
    check_server()
