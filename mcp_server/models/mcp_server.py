import importlib
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class MCPServer(models.Model):
    _name = 'mcp.server'
    _description = 'MCP 服务器'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    def _register_hook(self):
        """在模型注册后触发一次，用于调度 MCP 服务器自动启动。

        注意：某些环境不会调用模块级 _register_hook，这里用模型级覆盖确保在 Odoo 18 下可被调用。
        通过 PostgreSQL advisory lock 确保多 worker 下只执行一次，并在后台线程中执行以避免阻塞启动。
        """
        res = super()._register_hook()
        try:
            import threading
            import time
            from odoo import api
            from odoo.modules.registry import Registry

            _logger.info("[MCP] MCPServer._register_hook called; scheduling auto-start thread")

            cr = self.env.cr
            db_name = cr.dbname

            # 单实例执行保护
            LOCK_KEY = 0x6D63705F6175746F  # 与模块级一致，防止重复
            try:
                cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
                res_lock = cr.fetchone()
                locked = bool(res_lock and res_lock[0])
            except Exception as e:
                _logger.warning("[MCP] auto-start: unable to acquire advisory lock (model hook): %s", e)
                return res

            # 如果未获取到锁，直接返回
            if not locked:
                _logger.info("[MCP] auto-start: another worker holds the lock (model hook). Skipping.")
                return res

            def _unlock():
                try:
                    cr.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
                except Exception as ue:
                    _logger.debug("[MCP] auto-start: unlock advisory lock failed (model hook): %s", ue)

            def _thread_entry(db: str):
                registry = Registry(db)
                with registry.cursor() as tcr:
                    env = api.Environment(tcr, 1, {})
                    try:
                        _logger.info("[MCP] auto-start thread (model hook): waiting registry readiness...")
                        time.sleep(2.0)
                        servers = env['mcp.server'].sudo().search([
                            ('active', '=', True),
                            ('auto_start', '=', True),
                        ])
                        if not servers:
                            _logger.info("[MCP] auto-start: no active+auto_start servers in DB '%s'", db)
                            return
                        _logger.info("[MCP] auto-start: starting %d server(s) in DB '%s'", len(servers), db)
                        for server in servers:
                            try:
                                # 健康检查：即使标记为 active，也确认端口监听，否则重启
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
                                    # 仅在“监听且已注册”时视为真正已运行
                                    healthy = (health.get('status') == 'success') and listening and registered

                                if healthy:
                                    if server.state != 'active':
                                        server.sudo().write({'state': 'active'})
                                    _logger.info(
                                        "[MCP] Server '%s' already running on port %s (listening=%s, registered=%s)",
                                        server.name, server.port, listening, registered)
                                elif listening and not registered:
                                    # 端口被占用但当前进程未注册：提示占用情况，避免错误跳过
                                    _logger.warning(
                                        "[MCP] Port %s is listening but server '%s' not registered in current process; skip starting to avoid conflict",
                                        server.port, server.name)
                                    # 将状态保持原样，不强行置为 active，等待管理员处理端口冲突
                                else:
                                    _logger.info("[MCP] Auto-starting '%s' (port %s), previous state=%s, healthy=%s",
                                                 server.name, server.port, server.state, healthy)
                                    server._start_fastmcp_server(server)
                            except Exception as se:
                                _logger.error("[MCP] Auto-start failed for '%s': %s", server.name, se)
                    except Exception as e:
                        _logger.error("[MCP] auto-start thread error (model hook): %s", e)

            try:
                t = threading.Thread(target=_thread_entry, args=(db_name,), name="MCP-AutoStart(Model)", daemon=True)
                t.start()
                _logger.info("[MCP] auto-start thread scheduled (model hook) for DB '%s'", db_name)
            finally:
                _unlock()
        except Exception as e:
            _logger.warning("[MCP] MCPServer._register_hook scheduling failed: %s", e)
        return res

    name = fields.Char('服务器名称', required=True, tracking=True)
    port = fields.Integer('端口', default=10888, tracking=True, help='FastMCP 服务端口，可以修改')
    api_key = fields.Char('API密钥', tracking=True)
    active = fields.Boolean('激活状态', default=True, tracking=True)
    auto_start = fields.Boolean('开机自动启动', default=True, help='当 Odoo 启动或模块加载时自动启动该 MCP 服务器')
    state = fields.Selection([
        ('draft', '草稿'),
        ('active', '活动'),
        ('inactive', '不活动'),
    ], string='状态', default='draft', tracking=True)

    note = fields.Text('备注')
    last_connection = fields.Datetime('最后连接时间', readonly=True)
    connection_count = fields.Integer('连接次数', readonly=True, default=0)

    resource_ids = fields.One2many('mcp.resource', 'server_id', string='资源')
    resource_count = fields.Integer(compute='_compute_resource_count', string='资源数量')

    @api.depends('resource_ids')
    def _compute_resource_count(self):
        for record in self:
            record.resource_count = len(record.resource_ids)

    @api.constrains('port')
    def _check_port(self):
        for record in self:
            if not record.port:
                raise ValidationError(_('请设置服务端口'))
            if record.port < 1024 or record.port > 65535:
                raise ValidationError(_('端口必须在 1024-65535 范围内'))
            # 活跃服务器之间端口唯一
            domain = [('id', '!=', record.id), ('active', '=', True), ('port', '=', record.port)]
            conflict = self.search_count(domain)
            if conflict:
                raise ValidationError(_('端口 %s 已被其他活跃服务占用') % record.port)

    def action_activate(self):
        for record in self:
            # 启动FastMCP服务器
            if self._start_fastmcp_server(record):
                record.state = 'active'
            else:
                raise UserError(_('启动MCP服务器失败，请查看日志了解详情。'))

    def action_deactivate(self):
        for record in self:
            # 停止FastMCP服务器
            if self._stop_fastmcp_server(record):
                record.state = 'inactive'
            else:
                raise UserError(_('停止MCP服务器失败，请查看日志了解详情。'))

    def action_test_connection(self):
        self.ensure_one()
        try:
            # 使用FastMCP服务测试连接
            fastmcp_service = self._get_fastmcp_service()
            if not fastmcp_service:
                raise UserError(_('无法获取FastMCP服务，请确保服务已正确安装和配置。'))

            # 获取或创建MCP服务器实例
            mcp_server = fastmcp_service.get_or_create_mcp_server(self)
            if not mcp_server:
                raise UserError(_('无法创建FastMCP服务器实例。'))

            # 自动启动服务器
            _logger.info('测试连接时自动启动MCP服务器: %s', self.name)
            if not fastmcp_service.start_server(self):
                _logger.warning('在测试连接时启动服务器失败，将继续测试连接')

            # 更新连接信息
            self.write({
                'last_connection': fields.Datetime.now(),
                'connection_count': self.connection_count + 1,
                'state': 'active'  # 自动将状态设置为活动
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('连接成功'),
                    'message': _('与MCP服务器的连接测试成功，服务器已自动启动'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error('MCP服务器连接测试失败: %s', str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('连接失败'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': False,
                }
            }

    def _get_fastmcp_service(self):
        """获取FastMCP服务实例"""
        try:
            # 动态导入FastMCP服务模块
            module = importlib.import_module('odoo.addons.mcp_server.services.fast_mcp_service')
            # 获取FastMCPService类的单例实例
            return module.FastMCPService.get_instance()
        except ImportError as e:
            _logger.error('导入FastMCP服务模块失败: %s', str(e))
            return None
        except Exception as e:
            _logger.error('获取FastMCP服务实例失败: %s', str(e))
            return None

    def _start_fastmcp_server(self, record):
        """启动FastMCP服务器"""
        try:
            fastmcp_service = self._get_fastmcp_service()
            if not fastmcp_service:
                _logger.error('无法获取FastMCP服务实例')
                return False

            # 启动服务器
            result = fastmcp_service.start_server(record)
            if result:
                _logger.info('成功启动FastMCP服务器: %s', record.name)
            else:
                _logger.error('启动FastMCP服务器失败: %s', record.name)

            return result
        except Exception as e:
            _logger.error('启动FastMCP服务器时发生错误: %s', str(e))
            return False

    def _stop_fastmcp_server(self, record):
        """停止FastMCP服务器"""
        try:
            fastmcp_service = self._get_fastmcp_service()
            if not fastmcp_service:
                _logger.error('无法获取FastMCP服务实例')
                return False

            # 停止服务器
            result = fastmcp_service.stop_server(record)
            if result:
                _logger.info('成功停止FastMCP服务器: %s', record.name)
            else:
                _logger.error('停止FastMCP服务器失败: %s', record.name)

            return result
        except Exception as e:
            _logger.error('停止FastMCP服务器时发生错误: %s', str(e))
            return False


class MCPResource(models.Model):
    _name = 'mcp.resource'
    _description = 'MCP 资源'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char('资源名称', required=True, tracking=True)
    resource_uri = fields.Char('资源URI', required=True, tracking=True)
    server_id = fields.Many2one('mcp.server', string='服务器', required=True, ondelete='cascade')
    active = fields.Boolean('激活状态', default=True, tracking=True)
    resource_type = fields.Selection([
        ('file', '文件'),
        ('service', '服务'),
        ('api', 'API'),
        ('other', '其他'),
    ], string='资源类型', default='file', tracking=True)

    description = fields.Text('描述')
    content = fields.Text('内容', help='资源内容或描述')
    last_fetch = fields.Datetime('最后获取时间', readonly=True)

    def action_fetch_resource(self):
        self.ensure_one()
        try:
            # 在这里实现资源获取逻辑
            self.write({
                'last_fetch': fields.Datetime.now(),
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('获取成功'),
                    'message': _('资源获取成功'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error('MCP资源获取失败: %s', str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('获取失败'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': False,
                }
            }
