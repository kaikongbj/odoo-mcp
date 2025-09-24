# -*- coding: utf-8 -*-
import os

from odoo.tests.common import TransactionCase, tagged


class _FakeCtx(dict):
    """简单的 Context 模拟对象，兼容属性和 dict 访问。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)


@tagged('post_install', '-at_install')
class TestMCPContextAuthorization(TransactionCase):
    def setUp(self):
        super().setUp()
        # 延迟导入服务模块
        from odoo.addons.mcp_server.services.fast_mcp_service import FastMCPService
        self.service = FastMCPService.get_instance()

    def test_extract_api_key_from_metadata(self):
        ctx = _FakeCtx(metadata={"api_key": "abc123"})
        key = self.service._extract_api_key_from_ctx(ctx)
        self.assertEqual(key, "abc123")

    def test_extract_api_key_from_env_uppercase(self):
        ctx = _FakeCtx(env={"MCP_API_KEY": "UPPER-KEY"})
        key = self.service._extract_api_key_from_ctx(ctx)
        self.assertEqual(key, "UPPER-KEY")

    def test_extract_api_key_none_without_ctx_and_no_fallback(self):
        # 即使服务器进程环境里有变量，也不应当回退读取
        old_env = dict(os.environ)
        try:
            os.environ["MCP_API_KEY"] = "ENV-SHOULD-NOT-BE-USED"
            key = self.service._extract_api_key_from_ctx(None)
            self.assertIsNone(key)
            # 提供空上下文对象但不含任何凭证
            ctx = _FakeCtx()
            key2 = self.service._extract_api_key_from_ctx(ctx)
            self.assertIsNone(key2)
        finally:
            os.environ.clear()
            os.environ.update(old_env)
