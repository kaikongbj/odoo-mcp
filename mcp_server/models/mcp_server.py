import importlib
import logging
import secrets
import string
import threading

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# 全局标志，确保自动启动只执行一次
_auto_start_executed = False
_auto_start_lock = threading.Lock()


class MCPServer(models.Model):
    _name = 'mcp.server'
    _description = 'MCP 服务器'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    # 移除SQL约束，改用Python验证

    name = fields.Char('服务器名称', required=True, tracking=True)
    server_url = fields.Char('服务器URL', readonly=True, help="自动生成的服务器URL")
    server_port = fields.Integer('服务器端口', default=lambda self: self._get_next_available_port(),
                                 help="MCP服务器监听端口", tracking=True)
    api_key = fields.Char('API密钥', tracking=True)
    active = fields.Boolean('激活状态', default=True, tracking=True)
    state = fields.Selection([
        ('draft', '草稿'),
        ('active', '活动'),
        ('inactive', '不活动'),
    ], string='状态', default='draft', tracking=True)

    # 安全设置
    require_auth = fields.Boolean('需要授权', default=True,
                                  help="启用后，所有请求必须包含有效的认证凭证", tracking=True)
    auth_method = fields.Selection([
        ('api_key', 'API密钥'),
        ('jwt', 'JWT Bearer Token')
    ], string='认证方式', default='api_key', required=True, tracking=True)
    allowed_ips = fields.Text('允许的IP地址',
                              help="每行一个IP地址或CIDR格式。留空表示允许所有IP", tracking=True)
    log_requests = fields.Boolean('记录请求', default=True,
                                  help="启用后，记录所有请求到日志", tracking=True)
    max_requests_per_minute = fields.Integer('每分钟最大请求数', default=60,
                                             help="限制每个IP每分钟的最大请求数，0表示不限制", tracking=True)

    # API密钥认证相关设置
    api_key = fields.Char('API密钥', tracking=True,
                          help="用于API密钥认证方式的密钥")

    # JWT认证相关设置
    jwt_public_key = fields.Text('JWT公钥', tracking=True,
                                 help="用于验证JWT令牌的RSA公钥（PEM格式）")
    jwks_uri = fields.Char('JWKS URI', tracking=True,
                           help="JSON Web Key Set URI，用于动态获取验证密钥")
    jwt_issuer = fields.Char('令牌颁发者(Issuer)', tracking=True,
                             help="JWT令牌颁发者标识，用于验证令牌来源")
    jwt_audience = fields.Char('令牌接收方(Audience)', tracking=True,
                               help="JWT令牌接收方标识，用于验证令牌目标")
    jwt_algorithm = fields.Selection([
        ('RS256', 'RS256'),
        ('RS384', 'RS384'),
        ('RS512', 'RS512'),
        ('ES256', 'ES256'),
        ('ES384', 'ES384'),
        ('ES512', 'ES512')
    ], string='签名算法', default='RS256', tracking=True)

    note = fields.Text('备注')
    last_connection = fields.Datetime('最后连接时间', readonly=True)
    connection_count = fields.Integer('连接次数', readonly=True, default=0)

    resource_ids = fields.One2many('mcp.resource', 'server_id', string='资源')
    resource_count = fields.Integer(compute='_compute_resource_count', string='资源数量')

    @api.depends('resource_ids')
    def _compute_resource_count(self):
        for record in self:
            record.resource_count = len(record.resource_ids)

    @api.model
    def _auto_start_servers_on_startup(self):
        """在系统启动时自动启动活动的MCP服务器"""
        global _auto_start_executed, _auto_start_lock

        with _auto_start_lock:
            if _auto_start_executed:
                return
            _auto_start_executed = True

        try:
            _logger.info("系统启动：开始自动启动活动的MCP服务器")

            # 延迟启动，确保系统完全初始化
            def delayed_auto_start():
                try:
                    import time
                    time.sleep(3.0)  # 等待3秒确保系统完全启动

                    _logger.info("开始延迟自动启动MCP服务器")

                    # 获取FastMCP服务并启动活动服务器
                    from ..services.fast_mcp_service import FastMCPService
                    success = FastMCPService.auto_start_on_module_init()

                    if success:
                        _logger.info("系统启动：MCP服务器自动启动成功")
                    else:
                        _logger.warning("系统启动：MCP服务器自动启动未完全成功")

                except Exception as e:
                    _logger.error("系统启动时自动启动MCP服务器失败: %s", str(e))
                    import traceback
                    _logger.error("错误详情: %s", traceback.format_exc())

            # 在后台线程中执行延迟启动
            startup_thread = threading.Thread(
                target=delayed_auto_start,
                daemon=True,
                name="MCP-SystemAutoStart"
            )
            startup_thread.start()

            _logger.info("系统启动：已启动MCP服务器自动启动线程")

        except Exception as e:
            _logger.error("设置MCP服务器自动启动时发生错误: %s", str(e))

    @api.model
    def _register_hook(self):
        """在模型注册时调用，用于设置自动启动"""
        super()._register_hook()
        # 在模型注册完成后触发自动启动
        self._auto_start_servers_on_startup()

    def _get_next_available_port(self):
        """获取下一个可用的端口号"""
        import socket
        import random

        # 端口范围配置
        start_port = 10888
        max_port = 11000  # 最大端口范围

        # 获取已使用的端口
        used_ports = set()
        existing_servers = self.search([('server_port', '!=', False)])
        for server in existing_servers:
            if server.server_port:
                used_ports.add(server.server_port)

        # 首先尝试顺序查找
        for port in range(start_port, max_port):
            if port not in used_ports:
                # 检查端口是否真的可用
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.bind(('127.0.0.1', port))
                    sock.close()
                    _logger.info("找到可用端口: %d", port)
                    return port
                except OSError:
                    _logger.debug("端口 %d 已被占用", port)
                    continue

        # 如果顺序查找失败，尝试随机端口
        _logger.warning("顺序查找端口失败，尝试随机端口")
        attempts = 0
        while attempts < 50:  # 最多尝试50次
            attempts += 1
            port = random.randint(20000, 65000)  # 使用高端口范围
            if port not in used_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.bind(('127.0.0.1', port))
                    sock.close()
                    _logger.info("找到随机可用端口: %d", port)
                    return port
                except OSError:
                    continue

        # 如果仍然失败，使用默认端口并警告
        _logger.error("无法找到可用端口，使用默认端口10888，可能会导致端口冲突")
        return 10888
        return 10888

    @api.constrains('server_port')
    def _check_server_port(self):
        """验证服务器端口唯一性"""
        for record in self:
            if not record.server_port:
                continue

            # 检查是否有其他记录使用相同的端口
            same_port_records = self.search([
                ('id', '!=', record.id),
                ('server_port', '=', record.server_port)
            ])

            if same_port_records:
                raise ValidationError(_(
                    '端口 %s 已被服务器 "%s" 使用，请选择其他端口。'
                ) % (record.server_port, same_port_records[0].name))

    def action_generate_new_api_key(self):
        """生成新的API密钥"""
        self.ensure_one()
        alphabet = string.ascii_letters + string.digits
        new_api_key = ''.join(secrets.choice(alphabet) for i in range(32))

        self.write({'api_key': new_api_key})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('API密钥已更新'),
                'message': _('已为服务器 "%s" 生成新的API密钥') % self.name,
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        # 处理单个字典的情况
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        processed_vals_list = []
        for vals in vals_list:
            vals = dict(vals)  # 创建副本以避免修改原始数据
            if 'api_key' not in vals or not vals['api_key']:
                alphabet = string.ascii_letters + string.digits
                vals['api_key'] = ''.join(secrets.choice(alphabet) for i in range(32))

            # 确保每个服务器都有唯一的端口
            if 'server_port' not in vals or not vals['server_port']:
                vals['server_port'] = self._get_next_available_port()
            else:
                # 检查端口是否已被使用
                same_port_records = self.search([('server_port', '=', vals['server_port'])])
                if same_port_records:
                    raise ValidationError(_(
                        '端口 %s 已被服务器 "%s" 使用，请选择其他端口。'
                    ) % (vals['server_port'], same_port_records[0].name))

            # 生成服务器URL
            if 'server_port' in vals:
                vals['server_url'] = f'http://127.0.0.1:{vals["server_port"]}'

            processed_vals_list.append(vals)

        return super(MCPServer, self).create(processed_vals_list)

    def write(self, vals):
        """重写write方法，确保端口唯一性"""
        if 'server_port' in vals:
            # 检查端口是否已被其他服务器使用
            same_port_records = self.search([
                ('id', 'not in', self.ids),
                ('server_port', '=', vals['server_port'])
            ])

            if same_port_records:
                raise ValidationError(_(
                    '端口 %s 已被服务器 "%s" 使用，请选择其他端口。'
                ) % (vals['server_port'], same_port_records[0].name))

            # 更新服务器URL
            vals['server_url'] = f'http://127.0.0.1:{vals["server_port"]}'

        return super(MCPServer, self).write(vals)

    def action_activate(self):
        """启动MCP服务器"""
        for record in self:
            if record.state == 'active':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('服务器已运行'),
                        'message': _('MCP服务器 "%s" 已经在运行中') % record.name,
                        'type': 'info',
                        'sticky': False,
                    }
                }

            try:
                _logger.info('用户请求启动MCP服务器: %s (端口: %d)', record.name, record.server_port)
                # 启动FastMCP服务器
                if self._start_fastmcp_server(record):
                    record.write({
                        'state': 'active',
                        'last_connection': fields.Datetime.now()
                    })
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('启动成功'),
                            'message': _('MCP服务器 "%s" 已成功启动在端口 %d') % (record.name, record.server_port),
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('启动失败'),
                            'message': _('MCP服务器 "%s" 启动失败，请查看日志了解详情') % record.name,
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
            except Exception as e:
                _logger.error('启动MCP服务器失败: %s', str(e))
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('启动错误'),
                        'message': _('启动MCP服务器时发生错误: %s') % str(e),
                        'type': 'danger',
                        'sticky': True,
                    }
                }

    def action_deactivate(self):
        """停止MCP服务器"""
        for record in self:
            if record.state == 'inactive':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('服务器已停止'),
                        'message': _('MCP服务器 "%s" 已经处于停止状态') % record.name,
                        'type': 'info',
                        'sticky': False,
                    }
                }

            try:
                _logger.info('用户请求停止MCP服务器: %s (端口: %d)', record.name, record.server_port)
                # 停止FastMCP服务器
                if self._stop_fastmcp_server(record):
                    record.write({
                        'state': 'inactive'
                    })
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('停止成功'),
                            'message': _('MCP服务器 "%s" 已成功停止') % record.name,
                            'type': 'success',
                            'sticky': False,
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('停止失败'),
                            'message': _('MCP服务器 "%s" 停止失败，请查看日志了解详情') % record.name,
                            'type': 'warning',
                            'sticky': True,
                        }
                    }
            except Exception as e:
                _logger.error('停止MCP服务器失败: %s', str(e))
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('停止错误'),
                        'message': _('停止MCP服务器时发生错误: %s') % str(e),
                        'type': 'danger',
                        'sticky': True,
                    }
                }

    def action_restart(self):
        """重启MCP服务器"""
        self.ensure_one()
        try:
            _logger.info('用户请求重启MCP服务器: %s (端口: %d)', self.name, self.server_port)

            # 如果服务器正在运行，先停止它
            if self.state == 'active':
                if not self._stop_fastmcp_server(self):
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('重启失败'),
                            'message': _('无法停止MCP服务器 "%s"，重启失败') % self.name,
                            'type': 'danger',
                            'sticky': True,
                        }
                    }

                # 等待一下确保服务器完全停止
                import time
                time.sleep(2)

            # 启动服务器
            if self._start_fastmcp_server(self):
                self.write({
                    'state': 'active',
                    'last_connection': fields.Datetime.now()
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('重启成功'),
                        'message': _('MCP服务器 "%s" 已成功重启在端口 %d') % (self.name, self.server_port),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                self.write({'state': 'inactive'})
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('重启失败'),
                        'message': _('MCP服务器 "%s" 重启失败，请查看日志了解详情') % self.name,
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        except Exception as e:
            _logger.error('重启MCP服务器失败: %s', str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('重启错误'),
                    'message': _('重启MCP服务器时发生错误: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_check_port_availability(self):
        """检查端口是否可用"""
        self.ensure_one()
        import socket

        try:
            # 检查端口是否被占用
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('127.0.0.1', self.server_port))
            sock.close()

            if result == 0:
                # 端口已被占用
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('端口检查'),
                        'message': _('端口 %d 已被占用，请选择其他端口') % self.server_port,
                        'type': 'warning',
                        'sticky': True,
                    }
                }
            else:
                # 端口可用
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('端口检查'),
                        'message': _('端口 %d 可用') % self.server_port,
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('端口检查错误'),
                    'message': _('检查端口时发生错误: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def action_get_server_status(self):
        """获取服务器详细状态"""
        self.ensure_one()
        try:
            fastmcp_service = self._get_fastmcp_service()
            if not fastmcp_service:
                status_info = "FastMCP服务不可用"
                is_running = False
            else:
                # 检查服务器是否在服务字典中
                is_running = self.id in fastmcp_service.mcp_servers
                if is_running:
                    server_info = fastmcp_service.mcp_servers[self.id]
                    thread_alive = server_info['thread'].is_alive() if server_info['thread'] else False
                    status_info = f"服务器运行中\n端口: {server_info['port']}\n线程状态: {'活动' if thread_alive else '已停止'}"
                else:
                    status_info = "服务器未运行"

            # 检查端口是否被占用
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            port_in_use = sock.connect_ex(('127.0.0.1', self.server_port)) == 0
            sock.close()

            status_info += f"\n端口 {self.server_port}: {'占用' if port_in_use else '空闲'}"
            status_info += f"\n数据库状态: {self.state}"
            status_info += f"\n最后连接: {self.last_connection or '从未连接'}"

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('服务器状态: %s') % self.name,
                    'message': status_info,
                    'type': 'info',
                    'sticky': True,
                }
            }

        except Exception as e:
            _logger.error('获取服务器状态失败: %s', str(e))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('状态检查错误'),
                    'message': _('获取服务器状态时发生错误: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

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

            # 检查服务器是否已经运行
            server_running = self.id in fastmcp_service.mcp_servers

            if not server_running:
                _logger.info('测试连接时发现服务器未运行，尝试启动: %s', self.name)
                if fastmcp_service.start_server(self):
                    _logger.info('测试连接时成功启动MCP服务器: %s', self.name)
                    self.write({'state': 'active'})
                else:
                    _logger.warning('在测试连接时启动服务器失败: %s', self.name)
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('连接失败'),
                            'message': _('MCP服务器未运行且启动失败，请检查服务器配置'),
                            'type': 'danger',
                            'sticky': True,
                        }
                    }
            else:
                _logger.info('测试连接时发现服务器已在运行: %s', self.name)

            # 更新连接信息
            self.write({
                'last_connection': fields.Datetime.now(),
                'connection_count': self.connection_count + 1,
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

    def action_batch_start(self):
        """批量启动选中的服务器"""
        success_count = 0
        failed_servers = []

        for record in self:
            if record.state != 'active':
                try:
                    if self._start_fastmcp_server(record):
                        record.write({
                            'state': 'active',
                            'last_connection': fields.Datetime.now()
                        })
                        success_count += 1
                    else:
                        failed_servers.append(record.name)
                except Exception as e:
                    _logger.error('批量启动服务器 %s 失败: %s', record.name, str(e))
                    failed_servers.append(record.name)

        message = f'成功启动 {success_count} 个服务器'
        if failed_servers:
            message += f'，失败: {", ".join(failed_servers)}'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('批量启动结果'),
                'message': message,
                'type': 'success' if not failed_servers else 'warning',
                'sticky': False,
            }
        }

    def action_batch_stop(self):
        """批量停止选中的服务器"""
        success_count = 0
        failed_servers = []

        for record in self:
            if record.state == 'active':
                try:
                    if self._stop_fastmcp_server(record):
                        record.write({'state': 'inactive'})
                        success_count += 1
                    else:
                        failed_servers.append(record.name)
                except Exception as e:
                    _logger.error('批量停止服务器 %s 失败: %s', record.name, str(e))
                    failed_servers.append(record.name)

        message = f'成功停止 {success_count} 个服务器'
        if failed_servers:
            message += f'，失败: {", ".join(failed_servers)}'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('批量停止结果'),
                'message': message,
                'type': 'success' if not failed_servers else 'warning',
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
