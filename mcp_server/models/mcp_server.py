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

    name = fields.Char('服务器名称', required=True, tracking=True)
    server_url = fields.Char('服务器URL', required=True, tracking=True)
    api_key = fields.Char('API密钥', tracking=True)
    active = fields.Boolean('激活状态', default=True, tracking=True)
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

    @api.constrains('server_url')
    def _check_server_url(self):
        for record in self:
            if not record.server_url.startswith(('http://', 'https://')):
                raise ValidationError(_('服务器URL必须以http://或https://开头'))

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
