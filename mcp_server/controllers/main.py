import importlib
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MCPServerController(http.Controller):
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

    @http.route('/api/mcp/servers', auth='api_key', type='json', methods=['GET'])
    def get_servers(self, **kwargs):
        try:
            servers = request.env['mcp.server'].sudo().search([('active', '=', True)])
            result = []
            for server in servers:
                result.append({
                    'id': server.id,
                    'name': server.name,
                    'server_url': server.server_url,
                    'state': server.state,
                    'last_connection': server.last_connection,
                })
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.error("获取服务器列表失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/resources', auth='api_key', type='json', methods=['GET'])
    def get_resources(self, server_id=None, **kwargs):
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

    @http.route('/api/mcp/resource/<int:resource_id>', auth='api_key', type='json', methods=['GET'])
    def get_resource_content(self, resource_id, **kwargs):
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

    @http.route('/api/mcp/server/<int:server_id>/fastmcp', auth='api_key', type='http', methods=['GET', 'POST'])
    def fastmcp_proxy(self, server_id, **kwargs):
        """代理FastMCP服务器请求"""
        try:
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
                'server_url': server.server_url
            })

        except Exception as e:
            _logger.error("FastMCP代理请求失败: %s", str(e))
            return json.dumps({'status': 'error', 'message': str(e)})

    @http.route('/api/mcp/server/<int:server_id>/start', auth='api_key', type='json', methods=['POST'])
    def start_fastmcp_server(self, server_id, **kwargs):
        """启动FastMCP服务器"""
        try:
            server = request.env['mcp.server'].sudo().browse(server_id)
            if not server.exists():
                return {'status': 'error', 'message': 'MCP服务器不存在'}

            # 启动服务器
            result = server._start_fastmcp_server(server)
            if result:
                return {
                    'status': 'success',
                    'message': f'FastMCP服务器 {server.name} 已成功启动'
                }
            else:
                return {
                    'status': 'error',
                    'message': f'FastMCP服务器 {server.name} 启动失败'
                }
        except Exception as e:
            _logger.error("启动FastMCP服务器失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/server/<int:server_id>/stop', auth='api_key', type='json', methods=['POST'])
    def stop_fastmcp_server(self, server_id, **kwargs):
        """停止FastMCP服务器"""
        try:
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
