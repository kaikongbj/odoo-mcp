import importlib
import json
import logging

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class MCPServerController(http.Controller):
    def _extract_api_key(self):
        """按 MCP 规范从接口参数中提取 API Key（不再使用 Header）。

        优先级：
        1) JSON 请求体中的 api_key（含 JSON-RPC 包裹 params.api_key）
        2) 查询字符串 ?api_key=...
        3) 原始请求体 JSON 中的 api_key（对 type='http' 路由兜底），使用 cache=True
        """
        try:
            # 1) Odoo json 路由：request.jsonrequest 直接可用
            if hasattr(request, 'jsonrequest') and isinstance(request.jsonrequest, dict):
                body = request.jsonrequest
                if 'api_key' in body and body['api_key']:
                    return str(body['api_key']).strip()
                if 'params' in body and isinstance(body['params'], dict) and body['params'].get('api_key'):
                    return str(body['params']['api_key']).strip()

            # 2) 查询字符串
            try:
                qs = request.httprequest.args
                if qs:
                    api_key = qs.get('api_key')
                    if api_key:
                        return str(api_key).strip()
            except Exception:
                pass

            # 3) 原始请求体（type='http' 兜底），cache=True 避免后续读取失败
            try:
                raw = request.httprequest.get_data(cache=True, as_text=True) or ''
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        if data.get('api_key'):
                            return str(data['api_key']).strip()
                        if isinstance(data.get('params'), dict) and data['params'].get('api_key'):
                            return str(data['params']['api_key']).strip()
            except Exception:
                pass
        except Exception:
            pass
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

    @http.route('/api/mcp/servers', auth='public', type='jsonrpc', methods=['GET'], csrf=False)
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
                    'port': server.port,
                    'state': server.state,
                    'last_connection': server.last_connection,
                })
            return {'status': 'success', 'data': result}
        except Exception as e:
            _logger.error("获取服务器列表失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/mcp/resources', auth='public', type='jsonrpc', methods=['GET'], csrf=False)
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

    @http.route('/api/mcp/resource/<int:resource_id>', auth='public', type='jsonrpc', methods=['GET'], csrf=False)
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
                'port': server.port
            })

        except Exception as e:
            _logger.error("FastMCP代理请求失败: %s", str(e))
            return json.dumps({'status': 'error', 'message': str(e)})

    @http.route('/api/mcp/server/<int:server_id>/start', auth='public', type='jsonrpc', methods=['POST'], csrf=False)
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

    @http.route('/api/mcp/server/<int:server_id>/stop', auth='public', type='jsonrpc', methods=['POST'], csrf=False)
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

    @http.route('/api/mcp/server/<int:server_id>/health', auth='public', type='jsonrpc', methods=['GET'], csrf=False)
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

    # ----------------------
    # GraphQL HTTP 接口（直连 Odoo）
    # ----------------------
    @http.route('/api/mcp/graphql', auth='public', type='jsonrpc', methods=['POST'], csrf=False)
    def graphql_http(self, server_id=None, **kwargs):
        """执行 GraphQL 查询（需要 API Key 授权）。

        请求体 JSON 示例：
        {
          "query": "query { models }",
          "variables": {"key": "value"}
        }
        可选参数 server_id 用于凭据限定（与其他接口一致）。
        """
        try:
            if not self._is_authorized(server_id=server_id):
                return {'status': 'error', 'message': 'Unauthorized', 'code': 401}

            body = {}
            try:
                # 新版 Odoo 提供 jsonrequest；若不可用则回退到原始数据解析
                if hasattr(request, 'jsonrequest') and isinstance(request.jsonrequest, dict):
                    body = request.jsonrequest
                else:
                    raw = request.httprequest.get_data(cache=False, as_text=True) or ''
                    if raw:
                        import json
                        body = json.loads(raw)
                # 兼容 JSON-RPC 包装：{"jsonrpc":"2.0","method":"call","params":{...}}
                if isinstance(body, dict) and 'params' in body and isinstance(body['params'], dict):
                    body = body['params']
            except Exception:
                body = {}

            # 读取 query / variables，优先 JSON 体；若缺失则从查询字符串兜底
            query = (body.get('query') if isinstance(body, dict) else '') or ''
            variables = (body.get('variables') if isinstance(body, dict) else {}) or {}
            if not query:
                try:
                    qs = request.httprequest.args  # ImmutableMultiDict
                    if qs:
                        query = qs.get('query') or query
                        import json as _json
                        vars_qs = qs.get('variables')
                        if vars_qs and not variables:
                            try:
                                variables = _json.loads(vars_qs)
                            except Exception:
                                variables = {}
                except Exception:
                    pass
            if not query:
                return {'status': 'error', 'message': 'Missing query'}

            # 延迟导入 schema
            try:
                from odoo.addons.mcp_server.services.graphql_schema import build_schema
            except Exception as ie:
                _logger.error("导入 GraphQL schema 失败: %s", ie)
                return {'status': 'error', 'message': f'schema import failed: {ie}'}

            schema = build_schema()
            env = request.env
            context_value = {'env': env}
            result = schema.execute(query, variable_values=variables, context_value=context_value)

            payload = {'status': 'success'}
            if result.errors:
                payload['status'] = 'error'
                payload['errors'] = [str(e) for e in result.errors]
            if result.data is not None:
                payload['data'] = result.data
            return payload
        except Exception as e:
            _logger.error("GraphQL HTTP 调用失败: %s", e)
            return {'status': 'error', 'message': str(e)}

    # 兼容：某些环境下请求被推断为 HTTP，增加同路径 HTTP 路由做兜底
    @http.route('/api/mcp/graphql', auth='public', type='http', methods=['POST'], csrf=False)
    def graphql_http_fallback(self, server_id=None, **kwargs):
        try:
            if not self._is_authorized(server_id=server_id):
                return request.make_json_response({'status': 'error', 'message': 'Unauthorized', 'code': 401}, status=401)

            # 读取原始请求体
            body = {}
            try:
                # 使用 cache=True，避免 _extract_api_key 已读取导致此处读取不到数据
                raw = request.httprequest.get_data(cache=True, as_text=True) or ''
                if raw:
                    body = json.loads(raw)
                if isinstance(body, dict) and 'params' in body and isinstance(body['params'], dict):
                    body = body['params']
            except Exception:
                body = {}

            query = (body.get('query') if isinstance(body, dict) else '') or ''
            variables = (body.get('variables') if isinstance(body, dict) else {}) or {}
            if not query:
                # 查询字符串兜底
                try:
                    qs = request.httprequest.args
                    if qs:
                        query = qs.get('query') or query
                        vars_qs = qs.get('variables')
                        if vars_qs and not variables:
                            try:
                                variables = json.loads(vars_qs)
                            except Exception:
                                variables = {}
                except Exception:
                    pass
            if not query:
                return request.make_json_response({'status': 'error', 'message': 'Missing query'}, status=400)

            try:
                from odoo.addons.mcp_server.services.graphql_schema import build_schema
            except Exception as ie:
                _logger.error("导入 GraphQL schema 失败: %s", ie)
                return request.make_json_response({'status': 'error', 'message': f'schema import failed: {ie}'}, status=500)

            schema = build_schema()
            env = request.env
            context_value = {'env': env}
            result = schema.execute(query, variable_values=variables, context_value=context_value)

            payload = {'status': 'success'}
            if result.errors:
                payload['status'] = 'error'
                payload['errors'] = [str(e) for e in result.errors]
            if result.data is not None:
                payload['data'] = result.data
            return request.make_json_response(payload)
        except Exception as e:
            _logger.error("GraphQL HTTP 兜底路由失败: %s", e)
            return request.make_json_response({'status': 'error', 'message': str(e)}, status=500)

    # 显式 HTTP 路径，便于使用 curl 直接调用
    @http.route('/api/mcp/graphql/http', auth='public', type='http', methods=['POST'], csrf=False)
    def graphql_http_explicit(self, server_id=None, **kwargs):
        return self.graphql_http_fallback(server_id=server_id, **kwargs)
