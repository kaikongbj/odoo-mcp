# -*- coding: utf-8 -*-
import json

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestGraphQLViaMCP(HttpCase):
    def setUp(self):
        super().setUp()
        self.server = self.env['mcp.server'].sudo().create({
            'name': 'GraphQL Test Server',
            'api_key': 'gql-key-123',
            'state': 'active',
        })
        self.env['mcp.resource'].sudo().create({
            'name': 'Cfg',
            'resource_uri': '/api/config',
            'server_id': self.server.id,
            'resource_type': 'file',
        })

    def _open_json(self, url):
        res = self.url_open(url)
        if isinstance(res, bytes):
            res = res.decode('utf-8')
        try:
            return json.loads(res)
        except Exception:
            try:
                return json.loads(res.data.decode('utf-8'))
            except Exception:
                return {}

    def test_graphql_query_servers(self):
        # 通过 FastMCP 初始化后，GraphQL 作为工具对外暴露，
        # 这里仅做冒烟：调用 fastmcp 代理接口确保服务可达
        url = f"/api/mcp/server/{self.server.id}/fastmcp?api_key={self.server.api_key}"
        data = self._open_json(url)
        self.assertEqual(data.get('status'), 'success')
