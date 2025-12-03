# -*- coding: utf-8 -*-
import json

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestAPIAuthentication(HttpCase):
    def setUp(self):
        super().setUp()
        # 创建一个测试用的 MCP 服务器记录
        self.server = self.env['mcp.server'].sudo().create({
            'name': 'Test MCP Server',
            'api_key': 'test-key-123',
            'state': 'active',
        })

    def _open_json(self, url):
        res = self.url_open(url)
        # url_open 可能返回 bytes 或 str
        if isinstance(res, bytes):
            res = res.decode('utf-8')
        try:
            return json.loads(res)
        except Exception:
            # 若不是纯文本 JSON，可能是 werkzeug Response 对象
            try:
                return json.loads(res.data.decode('utf-8'))
            except Exception:
                return {}

    def test_fastmcp_proxy_unauthorized(self):
        # 不带 API Key，应返回未授权码
        url = f"/api/mcp/server/{self.server.id}/fastmcp"
        data = self._open_json(url)
        self.assertIn('code', data)
        self.assertEqual(data['code'], 401)

    def test_fastmcp_proxy_authorized_with_query_param(self):
        # 使用查询参数 api_key 应通过
        url = f"/api/mcp/server/{self.server.id}/fastmcp?api_key={self.server.api_key}"
        data = self._open_json(url)
        self.assertEqual(data.get('status'), 'success')

    def test_fastmcp_proxy_authorized_with_body_param(self):
        # 使用 body JSON 携带 api_key（type='http' 路由可用）
        url = f"/api/mcp/server/{self.server.id}/fastmcp"
        payload = json.dumps({'api_key': self.server.api_key}).encode('utf-8')
        res = self.url_open(url, data=payload, headers={'Content-Type': 'application/json'})
        if hasattr(res, 'data'):
            raw = res.data
        else:
            raw = res
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        self.assertEqual(data.get('status'), 'success')
