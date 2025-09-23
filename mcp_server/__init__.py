import logging

_logger = logging.getLogger(__name__)
_logger.info("[MCP] mcp_server.__init__ loaded (module import)")
from . import controllers
from . import models


def _register_hook(cr):
    import logging
    _logger = logging.getLogger(__name__)
    _logger.info("[MCP] mcp_server._register_hook called by Odoo registry")
    """Automatically start active MCP servers when registry loads for this DB.

    - Runs once per database per worker at registry build; guarded by an advisory lock
      so only one worker performs the start to avoid duplication.
    - Spawns a daemon thread to start servers without blocking the boot process.
    """
    import logging
    import threading
    import time
    from odoo import api
    from odoo.modules.registry import Registry

    _logger = logging.getLogger(__name__)

    # Acquire advisory lock to ensure single execution per DB
    LOCK_KEY = 0x6D63705F6175746F  # arbitrary 64-bit key
    try:
        cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        res = cr.fetchone()
        locked = bool(res and res[0])
    except Exception as e:
        _logger.warning("MCP auto-start: unable to acquire advisory lock (%s). Skipping.", e)
        return

    if not locked:
        _logger.info("MCP auto-start: another worker holds the lock. Skipping.")
        return

    # Release the lock immediately after scheduling the thread
    def _unlock():
        try:
            cr.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        except Exception as ue:
            _logger.debug("MCP auto-start: unlock advisory lock failed: %s", ue)

    def _thread_entry(db_name: str):
        # Create a new Environment using a fresh cursor; avoid api.Environment.manage for compatibility
        registry = Registry(db_name)
        with registry.cursor() as tcr:
            env = api.Environment(tcr, 1, {})  # SUPERUSER_ID
            try:
                _logger.info("MCP auto-start thread: waiting a moment for registry readiness...")
                time.sleep(2.0)
                servers = env['mcp.server'].sudo().search([
                    ('active', '=', True),
                    ('auto_start', '=', True),
                ])
                if not servers:
                    _logger.info("MCP auto-start: no active servers found in DB '%s'", db_name)
                    return
                _logger.info("MCP auto-start: starting %d server(s) in DB '%s'", len(servers), db_name)
                for server in servers:
                    try:
                        # 健康检查：若标记为active但未监听，应尝试重启
                        svc = None
                        try:
                            svc = server._get_fastmcp_service()
                        except Exception:
                            svc = None
                        healthy = False
                        listening = False
                        registered = False
                        if svc:
                            health = svc.health_check(server)
                            data = health.get('data', {}) if isinstance(health, dict) else {}
                            listening = bool(data.get('listening', False))
                            registered = bool(data.get('registered', False))
                            # 只在“监听且已注册”时判断为真正已运行
                            healthy = (health.get('status') == 'success') and listening and registered

                        if healthy:
                            if server.state != 'active':
                                server.sudo().write({'state': 'active'})
                            _logger.info("MCP server '%s' already running on port %s (listening=%s, registered=%s)",
                                         server.name, server.port, listening, registered)
                        elif listening and not registered:
                            # 端口被占用但当前进程未注册：避免误判
                            _logger.warning(
                                "MCP port %s is listening but server '%s' not registered in this process; skip starting to avoid conflict",
                                server.port, server.name)
                        else:
                            _logger.info("Auto-starting MCP server '%s' (port %s), previous state=%s, healthy=%s",
                                         server.name, server.port, server.state, healthy)
                            server._start_fastmcp_server(server)
                    except Exception as se:
                        _logger.error("Auto-start failed for '%s': %s", server.name, se)
            except Exception as e:
                _logger.error("MCP auto-start thread error: %s", e)

    # Spawn background thread
    try:
        db_name = cr.dbname if hasattr(cr, 'dbname') else getattr(cr, 'db', None) or ''
        t = threading.Thread(target=_thread_entry, args=(db_name,), name="MCP-AutoStart", daemon=True)
        t.start()
        _logger.info("MCP auto-start thread scheduled for DB '%s'", db_name)
    finally:
        _unlock()


# 兼容 Odoo 多版本：如有 api.post_load 则注册，否则跳过并依赖模块/模型级钩子
try:
    from odoo import api

    if hasattr(api, 'post_load'):
        api.post_load(_register_hook)
        _logger.info("[MCP] mcp_server._register_hook registered via post_load")
    else:
        _logger.info("[MCP] api.post_load not available; relying on module/model hooks")
except Exception as e:
    _logger.debug("[MCP] post_load registration check failed: %s", e)
