# -*- coding: utf-8 -*-

import base64
import json
import jwt
import logging
import unittest
from datetime import datetime, timedelta
from odoo.tests.common import TransactionCase, tagged
from unittest.mock import patch, MagicMock, AsyncMock

from ..services.fast_mcp_service import FastMCPService

_logger = logging.getLogger(__name__)

# 生成一对RSA密钥用于测试JWT (此处仅生成用于测试的临时密钥)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_test_keys():
    """生成用于测试的RSA密钥对"""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return private_pem, public_pem


@tagged('post_install', '-at_install')
class TestAuthentication(TransactionCase):
    """测试MCP服务器的认证机制"""

    def setUp(self):
        """设置测试环境"""
        super(TestAuthentication, self).setUp()

        # 创建测试服务器记录
        self.test_api_key = "test_api_key_123456"
        self.private_key, self.public_key = generate_test_keys()

        # 创建使用API密钥认证的测试服务器
        self.api_key_server = self.env['mcp.server'].create({
            'name': 'Test API Key Server',
            'server_url': 'http://localhost:8888',
            'server_port': 8888,
            'require_auth': True,
            'auth_method': 'api_key',
            'api_key': self.test_api_key,
        })

        # 创建使用JWT认证的测试服务器
        self.jwt_server = self.env['mcp.server'].create({
            'name': 'Test JWT Server',
            'server_url': 'http://localhost:8889',
            'server_port': 8889,
            'require_auth': True,
            'auth_method': 'jwt',
            'jwt_public_key': self.public_key,
            'jwt_issuer': 'test-issuer',
            'jwt_audience': 'test-audience',
            'jwt_algorithm': 'RS256'
        })

        # 使用模拟对象替代实际的FastMCPService
        # 避免在测试中创建实际的服务器实例
        self.mcp_service = FastMCPService()

    def test_get_security_settings_api_key(self):
        """测试获取API密钥认证服务器的安全设置"""
        settings = self.mcp_service._get_server_security_settings(self.api_key_server.id)

        self.assertTrue(settings.get('require_auth'))
        self.assertEqual(settings.get('auth_method'), 'api_key')
        self.assertEqual(settings.get('api_key'), self.test_api_key)

    def test_get_security_settings_jwt(self):
        """测试获取JWT认证服务器的安全设置"""
        settings = self.mcp_service._get_server_security_settings(self.jwt_server.id)

        self.assertTrue(settings.get('require_auth'))
        self.assertEqual(settings.get('auth_method'), 'jwt')
        self.assertEqual(settings.get('jwt_public_key'), self.public_key)
        self.assertEqual(settings.get('jwt_issuer'), 'test-issuer')
        self.assertEqual(settings.get('jwt_audience'), 'test-audience')
        self.assertEqual(settings.get('jwt_algorithm'), 'RS256')

    def test_create_auth_provider_api_key(self):
        """测试创建API密钥认证提供者"""
        settings = {
            'require_auth': True,
            'auth_method': 'api_key',
            'api_key': self.test_api_key,
            'allowed_ips': [],
            'log_requests': True
        }

        auth_provider = self.mcp_service._create_auth_provider(settings)
        self.assertIsNotNone(auth_provider)
        self.assertEqual(auth_provider.api_key, self.test_api_key)

    @patch('fastmcp.server.auth.BearerAuthProvider')
    def test_create_auth_provider_jwt(self, mock_bearer):
        """测试创建JWT认证提供者"""
        # 配置模拟的BearerAuthProvider
        mock_instance = MagicMock()
        mock_bearer.return_value = mock_instance

        settings = {
            'require_auth': True,
            'auth_method': 'jwt',
            'jwt_public_key': self.public_key,
            'jwt_issuer': 'test-issuer',
            'jwt_audience': 'test-audience',
            'jwt_algorithm': 'RS256'
        }

        auth_provider = self.mcp_service._create_auth_provider(settings)

        # 验证BearerAuthProvider是否使用正确的参数创建
        mock_bearer.assert_called_once()
        call_kwargs = mock_bearer.call_args.kwargs
        self.assertEqual(call_kwargs.get('public_key'), self.public_key)
        self.assertEqual(call_kwargs.get('issuer'), 'test-issuer')
        self.assertEqual(call_kwargs.get('audience'), 'test-audience')
        self.assertEqual(call_kwargs.get('algorithm'), 'RS256')

        # 验证返回的是BearerAuthProvider的实例
        self.assertEqual(auth_provider, mock_instance)

    @patch('fastmcp.server.auth.BearerAuthProvider')
    def test_create_auth_provider_jwks(self, mock_bearer):
        """测试使用JWKS URI创建JWT认证提供者"""
        # 配置模拟的BearerAuthProvider
        mock_instance = MagicMock()
        mock_bearer.return_value = mock_instance

        jwks_uri = "https://example.com/.well-known/jwks.json"
        settings = {
            'require_auth': True,
            'auth_method': 'jwt',
            'jwks_uri': jwks_uri,
            'jwt_issuer': 'test-issuer',
            'jwt_audience': 'test-audience',
            'jwt_algorithm': 'RS256'
        }

        auth_provider = self.mcp_service._create_auth_provider(settings)

        # 验证BearerAuthProvider是否使用正确的参数创建
        mock_bearer.assert_called_once()
        call_kwargs = mock_bearer.call_args.kwargs
        self.assertEqual(call_kwargs.get('jwks_uri'), jwks_uri)
        self.assertEqual(call_kwargs.get('issuer'), 'test-issuer')
        self.assertEqual(call_kwargs.get('audience'), 'test-audience')
        self.assertEqual(call_kwargs.get('algorithm'), 'RS256')

    async def async_test_check_authentication_api_key(self):
        """测试API密钥认证检查 (异步测试)"""
        # 创建模拟MCP服务器实例
        mcp_server = MagicMock()
        mcp_server._security_settings = {
            'require_auth': True,
            'auth_method': 'api_key',
            'api_key': self.test_api_key,
            'allowed_ips': [],
            'log_requests': True
        }

        # 创建模拟上下文和请求
        ctx = MagicMock()
        request = MagicMock()
        request.headers = {'authorization': f'Bearer {self.test_api_key}'}
        request.client = MagicMock()
        request.client.host = '127.0.0.1'

        ctx.get_http_request = MagicMock(return_value=request)

        # 测试有效的API密钥
        result = await self.mcp_service._check_authentication(mcp_server, ctx)
        self.assertIsNone(result)  # None表示认证通过

        # 测试无效的API密钥
        request.headers = {'authorization': 'Bearer invalid_key'}
        result = await self.mcp_service._check_authentication(mcp_server, ctx)
        self.assertIsNotNone(result)  # 不是None表示认证失败
        self.assertEqual(result.get('status'), 'error')

    async def async_test_check_authentication_jwt(self):
        """测试JWT认证检查 (异步测试)"""
        # 创建一个有效的JWT令牌
        payload = {
            'sub': 'test-user',
            'iss': 'test-issuer',
            'aud': 'test-audience',
            'exp': datetime.utcnow() + timedelta(hours=1),
            'iat': datetime.utcnow()
        }

        # 使用测试私钥签名
        valid_token = jwt.encode(payload, self.private_key, algorithm='RS256')

        # 创建模拟的BearerAuthProvider
        auth_provider = MagicMock()
        auth_provider.verify_token = AsyncMock()

        # 模拟verify_token返回用户信息
        auth_provider.verify_token.return_value = {
            'sub': 'test-user',
            'client_id': 'test-client'
        }

        # 创建模拟MCP服务器实例
        mcp_server = MagicMock()
        mcp_server._security_settings = {
            'require_auth': True,
            'auth_method': 'jwt',
            'log_requests': True
        }
        mcp_server._auth_provider = auth_provider

        # 创建模拟上下文和请求
        ctx = MagicMock()
        request = MagicMock()
        request.headers = {'authorization': f'Bearer {valid_token}'}
        request.client = MagicMock()
        request.client.host = '127.0.0.1'

        ctx.get_http_request = MagicMock(return_value=request)

        # 测试有效的JWT令牌
        result = await self.mcp_service._check_authentication(mcp_server, ctx)
        self.assertIsNone(result)  # None表示认证通过
        auth_provider.verify_token.assert_called_once_with(valid_token)

        # 模拟verify_token返回None (无效令牌)
        auth_provider.verify_token.reset_mock()
        auth_provider.verify_token.return_value = None

        result = await self.mcp_service._check_authentication(mcp_server, ctx)
        self.assertIsNotNone(result)  # 不是None表示认证失败
        self.assertEqual(result.get('status'), 'error')

    def test_check_authentication_api_key(self):
        """API密钥认证检查的同步测试包装器"""
        # 使用Python 3.8+的asyncio.run运行异步测试
        import asyncio
        asyncio.run(self.async_test_check_authentication_api_key())

    def test_check_authentication_jwt(self):
        """JWT认证检查的同步测试包装器"""
        # 使用Python 3.8+的asyncio.run运行异步测试
        import asyncio
        asyncio.run(self.async_test_check_authentication_jwt())
