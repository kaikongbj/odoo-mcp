import logging

from . import controllers
from . import models
from . import services

_logger = logging.getLogger(__name__)

# 在模块加载时设置自动启动标志
import threading

_auto_start_executed = False
_auto_start_lock = threading.Lock()


def post_init_hook(cr, registry):
    """模块安装后的初始化钩子 - 只在模块安装/升级时执行"""
    try:
        _logger.info("开始执行MCP服务器模块安装后初始化钩子")

        # 模块安装后的初始化工作
        # 注意：这里不执行自动启动，自动启动由_register_hook处理

        _logger.info("MCP服务器模块安装后初始化钩子执行完成")
        _logger.info("MCP服务器将在系统启动时自动启动活动状态的服务器")

    except Exception as e:
        _logger.error("执行MCP服务器模块安装后初始化钩子时发生错误: %s", str(e))
        import traceback
        _logger.error("错误详情: %s", traceback.format_exc())
