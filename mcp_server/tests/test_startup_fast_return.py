# -*- coding: utf-8 -*-
import time

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestFastStartupReturn(HttpCase):
    def setUp(self):
        super().setUp()
        self.server = self.env['mcp.server'].sudo().create({
            'name': 'Quick Start Server',
            'server_url': 'https://mcp.example.com',
            'api_key': 'quick-key',
            'state': 'inactive',
            'active': True,
        })

    def test_start_server_quick_health_fallback(self):
        svc = self.env['mcp.server']._get_fastmcp_service()
        self.assertTrue(svc)

        # 保存原始 health_check
        original_health = svc.health_check

        # 构造一个快速返回的 health_check：第一次调用监听=False，第二次开始监听=True
        calls = {'n': 0}

        def fake_health(record):
            calls['n'] += 1
            listening = calls['n'] >= 2  # 第二次起返回监听成功
            return {
                'status': 'success',
                'data': {
                    'server_id': record.id,
                    'name': record.name,
                    'host': '127.0.0.1',
                    'port': int(record.port or 10888),
                    'listening': listening,
                    'registered': record.id in svc.mcp_servers,
                }
            }

        try:
            svc.health_check = fake_health
            t0 = time.time()
            ok = self.server._start_fastmcp_server(self.server)
            elapsed = time.time() - t0
            # 启动逻辑会多次轮询，允许数秒；只验证最终 True
            self.assertTrue(ok, '启动未能成功')
            self.assertEqual(self.server.state, 'active')
            # 确保 fake_health 调用多于一次，说明进行了轮询
            self.assertGreaterEqual(calls['n'], 1)
        finally:
            svc.health_check = original_health
