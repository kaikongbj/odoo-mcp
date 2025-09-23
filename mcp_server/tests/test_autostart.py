# -*- coding: utf-8 -*-
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestAutoStartLogic(HttpCase):
    def setUp(self):
        super().setUp()
        self.server = self.env['mcp.server'].sudo().create({
            'name': 'AutoStart Server',
            'server_url': 'https://mcp.example.com',
            'api_key': 'auto-key-789',
            'state': 'inactive',
            'auto_start': True,
            'active': True,
        })

    def test_precheck_requires_registered(self):
        # 获取服务并猴子补丁 health_check 模拟 仅监听但未注册 的情况
        svc = self.env['mcp.server']._get_fastmcp_service()
        self.assertTrue(svc)

        original_health = svc.health_check

        def fake_health(record):
            return {
                'status': 'success',
                'data': {
                    'server_id': record.id,
                    'name': record.name,
                    'host': '127.0.0.1',
                    'port': int(record.port or 10888),
                    'listening': True,
                    'registered': False,
                }
            }

        try:
            svc.health_check = fake_health  # 模拟仅监听未注册
            # 调用启动：应返回 False（跳过以避免冲突），且不把状态错误置为 active
            ok = self.server._start_fastmcp_server(self.server)
            self.assertFalse(ok)
            self.assertNotEqual(self.server.state, 'active')
        finally:
            svc.health_check = original_health
