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
            'server_url': 'https://mcp.example.com',
            'api_key': 'test-key-123',
            'state': 'active',
        })

    def _open_json(self, url, headers=None):
        headers = headers or {}
        res = self.url_open(url, headers=headers)
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

    def test_fastmcp_proxy_authorized_with_header(self):
        # 使用 X-Api-Key 头部应通过
        url = f"/api/mcp/server/{self.server.id}/fastmcp"
        data = self._open_json(url, headers={'X-Api-Key': self.server.api_key})
        self.assertEqual(data.get('status'), 'success')

    def test_fastmcp_proxy_authorized_with_bearer(self):
        # 使用 Authorization: Bearer 应通过
        url = f"/api/mcp/server/{self.server.id}/fastmcp"
        headers = {'Authorization': f"Bearer {self.server.api_key}"}
        data = self._open_json(url, headers=headers)
        self.assertEqual(data.get('status'), 'success')
