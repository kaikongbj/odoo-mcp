import importlib
import json
import logging

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class MCPServerController(http.Controller):
    def _extract_api_key(self):
        """从请求头提取 API Key，支持 X-Api-Key 或 Authorization: Bearer <token>"""
        try:
            headers = request.httprequest.headers
            api_key = headers.get('X-Api-Key') or headers.get('x-api-key')
            if not api_key:
                auth_header = headers.get('Authorization') or headers.get('authorization')
                if auth_header and auth_header.lower().startswith('bearer '):
                    api_key = auth_header.split(' ', 1)[1].strip()
            return api_key
        except Exception:
            return None

    def _is_authorized(self, server_id=None):
        """校验请求是否携带有效 API Key。

        - 若提供 server_id，则校验该服务器的 api_key 是否匹配。
        - 否则，校验是否存在任一活动服务器的 api_key 匹配。
        """
        key = self._extract_api_key()
        if not key:
            return False
        env = request.env['mcp.server'].sudo()
        try:
            if server_id:
                server = env.browse(int(server_id))
                return bool(server.exists() and server.api_key and server.api_key == key)
            # 任意匹配即可放行
            return bool(env.search_count([('active', '=', True), ('api_key', '=', key)]) > 0)
        except Exception:
            return False
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

    @http.route('/api/mcp/servers', auth='public', type='json', methods=['GET'], csrf=False)
    def get_servers(self, **kwargs):
        if not self._is_authorized():
            return {'status': 'error', 'message': 'Unauthorized', 'code': 401}
        try:
            servers = request.env['mcp.server'].sudo().search([('active', '=', True)])
            result = []
            for server in servers:
                result.append({
                    'id': server.id,
                    'name': server.name,
                    'server_url': server.server_url,
                    'port': server.port,
                    'state': server.state,
                    'last_connection': server.last_connection,
                })
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.error("获取服务器列表失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/resources', auth='public', type='json', methods=['GET'], csrf=False)
    def get_resources(self, server_id=None, **kwargs):
        if not self._is_authorized(server_id=server_id):
            return {'status': 'error', 'message': 'Unauthorized', 'code': 401}
        try:
            domain = [('active', '=', True)]
            if server_id:
                domain.append(('server_id', '=', int(server_id)))

            resources = request.env['mcp.resource'].sudo().search(domain)
            result = []
            for resource in resources:
                result.append({
                    'id': resource.id,
                    'name': resource.name,
                    'resource_uri': resource.resource_uri,
                    'server_id': resource.server_id.id,
                    'server_name': resource.server_id.name,
                    'resource_type': resource.resource_type,
                    'last_fetch': resource.last_fetch,
                })
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.error("获取资源列表失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/resource/<int:resource_id>', auth='public', type='json', methods=['GET'], csrf=False)
    def get_resource_content(self, resource_id, **kwargs):
        if not self._is_authorized():
            return {'status': 'error', 'message': 'Unauthorized', 'code': 401}
        try:
            resource = request.env['mcp.resource'].sudo().browse(resource_id)
            if not resource.exists():
                return {'status': 'error', 'message': '资源不存在'}

            # 更新最后获取时间
            resource.write({'last_fetch': fields.Datetime.now()})

            return {
                'status': 'success',
                'data': {
                    'id': resource.id,
                    'name': resource.name,
                    'content': resource.content,
                    'resource_uri': resource.resource_uri,
                    'server_id': resource.server_id.id,
                    'server_name': resource.server_id.name,
                    'resource_type': resource.resource_type,
                    'last_fetch': resource.last_fetch,
                }
            }
        except Exception as e:
            _logger.error("获取资源内容失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/server/<int:server_id>/fastmcp', auth='public', type='http', methods=['GET', 'POST'],
                csrf=False)
    def fastmcp_proxy(self, server_id, **kwargs):
        """代理FastMCP服务器请求"""
        try:
            if not self._is_authorized(server_id=server_id):
                return json.dumps({'status': 'error', 'message': 'Unauthorized', 'code': 401})
            server = request.env['mcp.server'].sudo().browse(server_id)
            if not server.exists():
                return json.dumps({'status': 'error', 'message': 'MCP服务器不存在'})

            if server.state != 'active':
                return json.dumps({'status': 'error', 'message': 'MCP服务器不活动，请先激活服务器'})

            # 获取FastMCP服务
            fastmcp_service = self._get_fastmcp_service()
            if not fastmcp_service:
                return json.dumps({'status': 'error', 'message': '无法获取FastMCP服务'})

            # 获取或创建MCP服务器实例
            mcp_server = fastmcp_service.get_or_create_mcp_server(server)
            if not mcp_server:
                return json.dumps({'status': 'error', 'message': '无法创建FastMCP服务器实例'})

            # 更新服务器连接信息
            server.write({
                'last_connection': fields.Datetime.now(),
                'connection_count': server.connection_count + 1
            })

            # 这里需要根据FastMCP的实际API实现代理逻辑
            # 暂时返回一个成功响应
            return json.dumps({
                'status': 'success',
                'message': 'FastMCP服务器已就绪',
                'server_name': server.name,
                'server_url': server.server_url,
                'port': server.port
            })

        except Exception as e:
            _logger.error("FastMCP代理请求失败: %s", str(e))
            return json.dumps({'status': 'error', 'message': str(e)})

    @http.route('/api/mcp/server/<int:server_id>/start', auth='public', type='json', methods=['POST'], csrf=False)
    def start_fastmcp_server(self, server_id, **kwargs):
        """启动FastMCP服务器"""
        try:
            if not self._is_authorized(server_id=server_id):
                return {'status': 'error', 'message': 'Unauthorized', 'code': 401}
            server = request.env['mcp.server'].sudo().browse(server_id)
            if not server.exists():
                return {'status': 'error', 'message': 'MCP服务器不存在'}

            # 启动服务器
            result = server._start_fastmcp_server(server)
            if result:
                # 进行一次健康检查
                svc = self._get_fastmcp_service()
                health = svc.health_check(server) if svc else {'status': 'error', 'message': 'no service'}
                return {
                    'status': 'success',
                    'message': f'FastMCP服务器 {server.name} 已成功启动',
                    'health': health,
                }
            else:
                return {
                    'status': 'error',
                    'message': f'FastMCP服务器 {server.name} 启动失败'
                }
        except Exception as e:
            _logger.error("启动FastMCP服务器失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/server/<int:server_id>/stop', auth='public', type='json', methods=['POST'], csrf=False)
    def stop_fastmcp_server(self, server_id, **kwargs):
        """停止FastMCP服务器"""
        try:
            if not self._is_authorized(server_id=server_id):
                return {'status': 'error', 'message': 'Unauthorized', 'code': 401}
            server = request.env['mcp.server'].sudo().browse(server_id)
            if not server.exists():
                return {'status': 'error', 'message': 'MCP服务器不存在'}

            # 停止服务器
            result = server._stop_fastmcp_server(server)
            if result:
                return {
                    'status': 'success',
                    'message': f'FastMCP服务器 {server.name} 已成功停止'
                }
            else:
                return {
                    'status': 'error',
                    'message': f'FastMCP服务器 {server.name} 停止失败'
                }
        except Exception as e:
            _logger.error("停止FastMCP服务器失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/server/<int:server_id>/health', auth='public', type='json', methods=['GET'], csrf=False)
    def server_health(self, server_id, **kwargs):
        """查询服务器健康状态"""
        try:
            if not self._is_authorized(server_id=server_id):
                return {'status': 'error', 'message': 'Unauthorized', 'code': 401}
            server = request.env['mcp.server'].sudo().browse(server_id)
            if not server.exists():
                return {'status': 'error', 'message': 'MCP服务器不存在'}

            svc = self._get_fastmcp_service()
            if not svc:
                return {'status': 'error', 'message': '无法获取FastMCP服务'}
            return svc.health_check(server)
        except Exception as e:
            _logger.error("健康检查接口失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}
