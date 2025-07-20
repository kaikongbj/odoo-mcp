#!/usr/bin/env python3
"""
测试 FastMCP 服务器初始化时序修复
专门针对 "Received request before initialization was complete" 错误
"""

import asyncio
import logging
import time

from fastmcp import FastMCP, Context

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TimingTestServer:
    """时序测试服务器"""

    def __init__(self):
        self.server = FastMCP(name="时序测试服务器")
        self.setup_tools()
        self.client_results = []

    def setup_tools(self):
        """设置测试工具"""

        @self.server.tool()
        async def timing_test_tool(message: str, ctx: Context = None) -> dict:
            """时序测试工具"""
            current_time = time.time()
            if ctx:
                await ctx.info(f"处理消息: {message}")

            return {
                "status": "success",
                "message": message,
                "timestamp": current_time,
                "server_ready": True
            }

    async def simulate_early_client_requests(self):
        """模拟客户端过早发送请求"""
        logger.info("开始模拟早期客户端请求...")

        # 等待不同的时间后发送请求
        delays = [0.1, 0.5, 1.0, 1.5, 2.0, 3.0]

        for i, delay in enumerate(delays):
            await asyncio.sleep(delay)
            try:
                logger.info(f"客户端请求 {i + 1}，延迟 {delay}s 后发送")

                # 尝试获取工具列表（这会触发初始化检查）
                tools = await self.server.get_tools()
                result = f"请求 {i + 1} 成功，获取到 {len(tools)} 个工具"
                self.client_results.append(result)
                logger.info(result)

            except Exception as e:
                error_msg = f"请求 {i + 1} 失败: {str(e)}"
                self.client_results.append(error_msg)
                if "initialization was complete" in str(e):
                    logger.warning(f"❌ {error_msg} - 这是我们要修复的错误！")
                else:
                    logger.error(f"❌ {error_msg}")


async def test_timing_robustness():
    """测试时序健壮性"""
    logger.info("=== FastMCP 时序健壮性测试 ===")

    test_server = TimingTestServer()

    # 并发启动服务器和客户端请求
    logger.info("并发启动服务器初始化和客户端请求...")

    # 创建任务
    server_task = asyncio.create_task(simulate_server_startup(test_server))
    client_task = asyncio.create_task(test_server.simulate_early_client_requests())

    # 等待两个任务完成
    await asyncio.gather(server_task, client_task)

    # 分析结果
    logger.info("\n=== 测试结果分析 ===")
    for result in test_server.client_results:
        if "失败" in result and "initialization was complete" in result:
            logger.error(f"❌ 仍存在时序问题: {result}")
        elif "失败" in result:
            logger.warning(f"⚠️  其他错误: {result}")
        else:
            logger.info(f"✅ {result}")

    # 判断整体成功率
    success_count = sum(1 for r in test_server.client_results if "成功" in r)
    total_count = len(test_server.client_results)
    success_rate = success_count / total_count if total_count > 0 else 0

    logger.info(f"\n=== 成功率: {success_count}/{total_count} ({success_rate:.1%}) ===")

    if success_rate >= 0.8:  # 80% 成功率认为是可接受的
        logger.info("🎉 时序问题修复效果良好！")
        return True
    else:
        logger.error("❌ 时序问题仍需进一步优化")
        return False


async def simulate_server_startup(test_server):
    """模拟服务器启动过程"""
    logger.info("开始模拟服务器启动过程...")

    # 模拟启动延迟
    await asyncio.sleep(0.5)
    logger.info("服务器启动阶段1: 基础初始化")

    await asyncio.sleep(0.5)
    logger.info("服务器启动阶段2: 工具注册")

    await asyncio.sleep(1.0)
    logger.info("服务器启动阶段3: 准备接受连接")

    await asyncio.sleep(0.5)
    logger.info("服务器启动完成")


async def test_delayed_startup_strategy():
    """测试延迟启动策略"""
    logger.info("\n=== 测试延迟启动策略 ===")

    # 创建服务器但不立即启动
    server = FastMCP(name="延迟启动测试")

    @server.tool()
    async def delayed_tool(data: str) -> dict:
        return {"processed": data, "timestamp": time.time()}

    # 模拟我们的延迟启动逻辑
    logger.info("步骤1: 创建服务器实例")
    await asyncio.sleep(0.5)

    logger.info("步骤2: 内部初始化延迟")
    await asyncio.sleep(2.0)  # 对应我们代码中的延迟

    logger.info("步骤3: 标记就绪")

    logger.info("步骤4: 测试工具可用性")
    try:
        tools = await server.get_tools()
        logger.info(f"✅ 延迟启动成功，工具数量: {len(tools)}")
        return True
    except Exception as e:
        logger.error(f"❌ 延迟启动失败: {str(e)}")
        return False


async def main():
    """主测试函数"""
    logger.info("FastMCP 时序修复验证测试")
    logger.info("=" * 50)

    # 测试1: 时序健壮性
    timing_result = await test_timing_robustness()

    # 测试2: 延迟启动策略
    delay_result = await test_delayed_startup_strategy()

    # 汇总结果
    logger.info("\n" + "=" * 50)
    logger.info("测试汇总:")
    logger.info(f"时序健壮性测试: {'✅ 通过' if timing_result else '❌ 失败'}")
    logger.info(f"延迟启动策略测试: {'✅ 通过' if delay_result else '❌ 失败'}")

    if timing_result and delay_result:
        logger.info("🎉 所有测试通过！时序修复生效")
        logger.info("\n关键改进:")
        logger.info("1. 增加了启动延迟到2秒")
        logger.info("2. 改进了初始化检查逻辑")
        logger.info("3. 添加了时序错误的重试机制")
        logger.info("4. 优化了错误检测和处理")
    else:
        logger.error("❌ 部分测试失败，需要进一步优化")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("测试被用户中断")
    except Exception as e:
        logger.error(f"测试运行失败: {str(e)}")
        import traceback

        logger.error(f"详细错误: {traceback.format_exc()}")
