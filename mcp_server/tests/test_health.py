# -*- coding: utf-8 -*-
import json

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestHealthEndpoint(HttpCase):
    def setUp(self):
        super().setUp()
        self.server = self.env['mcp.server'].sudo().create({
            'name': 'HealthCheck Server',
            'server_url': 'https://mcp.example.com',
            'api_key': 'health-key-456',
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

    def test_health_unauthorized(self):
        url = f"/api/mcp/server/{self.server.id}/health"
        data = self._open_json(url)
        assert data.get('code') == 401

    def test_health_authorized(self):
        url = f"/api/mcp/server/{self.server.id}/health"
        headers = {'X-Api-Key': self.server.api_key}
        data = self._open_json(url, headers=headers)
        assert data.get('status') in ('success', 'error')  # 允许失败但格式正确
        # 若成功应包含必要字段
        if data.get('status') == 'success':
            payload = data.get('data', {})
            assert 'server_id' in payload and payload.get('server_id') == self.server.id
            assert 'port' in payload
