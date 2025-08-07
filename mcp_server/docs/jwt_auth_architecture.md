# FastMCP JWT 认证 - 架构设计文档

## 1. 系统架构概述

FastMCP JWT认证机制基于OAuth 2.0 Bearer Token规范实现，通过扩展现有的FastMCPService认证逻辑，增加JWT解析与验证能力，同时保持对现有API密钥认证的兼容支持。

### 1.1 架构图

```
┌──────────────┐      ┌─────────────────┐      ┌───────────────────┐
│              │      │                 │      │                   │
│  客户端应用  ├──────▶  MCP HTTP 服务  ├──────▶  认证提供者工厂   │
│              │      │                 │      │                   │
└──────────────┘      └─────────────────┘      └─────────┬─────────┘
                                                         │
                                                         ▼
                      ┌─────────────────────────────────────────────────────┐
                      │                                                     │
                      │                认证提供者                            │
                      │                                                     │
                      └───────────┬─────────────────────────────┬───────────┘
                                  │                             │
                                  ▼                             ▼
                      ┌─────────────────────┐       ┌─────────────────────┐
                      │                     │       │                     │
                      │  API密钥认证提供者  │       │  JWT认证提供者      │
                      │                     │       │                     │
                      └─────────────────────┘       └─────────────────────┘
```

## 2. 核心组件设计

### 2.1 认证提供者工厂

**实现位置**: `_create_auth_provider` 方法

负责根据服务器配置创建适当类型的认证提供者实例。根据`auth_method`配置创建以下两种认证提供者之一：

1. **API密钥认证提供者**：简单字符串比对的认证逻辑
2. **JWT认证提供者**：实现完整的JWT解析与验证逻辑

```python
def _create_auth_provider(self, server_security_settings):
    """
    根据安全设置创建合适的认证提供者
    """
    auth_method = server_security_settings.get('auth_method', 'api_key')
    
    if auth_method == 'jwt':
        # JWT认证逻辑
        return BearerAuthProvider(...)
    else:
        # API密钥认证逻辑
        return ApiKeyAuthProvider(...)
```

### 2.2 认证检查流程

**实现位置**: `_check_authentication` 异步方法

处理HTTP请求的认证逻辑，执行以下流程：

1. 从HTTP请求中提取Authorization头
2. 解析Bearer token
3. 根据认证提供者类型执行相应验证
4. 验证通过后返回用户信息并设置到上下文

```python
async def _check_authentication(self, mcp_server, ctx):
    """
    检查并验证请求的认证信息
    """
    # 1. 检查是否需要认证
    if not mcp_server._security_settings.get('require_auth'):
        return None
    
    # 2. 获取请求和令牌
    request = ctx.get_http_request()
    token = self._extract_token(request)
    
    # 3. 根据认证类型执行验证
    auth_method = mcp_server._security_settings.get('auth_method', 'api_key')
    
    if auth_method == 'jwt':
        # JWT验证流程
        user_info = await mcp_server._auth_provider.verify_token(token)
        ...
    else:
        # API密钥验证流程
        if token != mcp_server._security_settings.get('api_key'):
            return {"status": "error", "message": "Invalid API key"}
        ...
```

### 2.3 JWT验证流程

JWT认证提供者使用FastMCP内置的`BearerAuthProvider`类，执行以下验证：

1. JWT结构与格式验证
2. 签名验证（使用RSA公钥或JWKS获取的密钥）
3. 过期时间检查
4. 发行者和受众验证

验证配置通过以下参数设置：

- `public_key`: RSA公钥，PEM格式
- `jwks_uri`: JWKS端点URI（与public_key二选一）
- `issuer`: 允许的JWT发行者
- `audience`: 允许的JWT受众
- `algorithm`: JWT签名算法（默认RS256）

## 3. 数据模型设计

### 3.1 MCPServer模型扩展

在`mcp_server.py`中的`MCPServer`模型中添加以下字段：

```python
auth_method = fields.Selection([
    ('api_key', 'API密钥认证'),
    ('jwt', 'JWT令牌认证')
], string='认证方式', default='api_key', required=True)

api_key = fields.Char(string='API密钥')

jwt_public_key = fields.Text(string='JWT公钥')

jwks_uri = fields.Char(string='JWKS URI')

jwt_issuer = fields.Char(string='JWT发行者')

jwt_audience = fields.Char(string='JWT受众')

jwt_algorithm = fields.Char(string='JWT算法', default='RS256')
```

### 3.2 安全设置数据流

在`_get_server_security_settings`方法中，收集安全配置并提供给认证组件：

```python
def _get_server_security_settings(self, mcp_server_id):
    """获取MCP服务器的安全设置"""
    MCP_Server = self.env['mcp.server']
    mcp_server = MCP_Server.browse(mcp_server_id)
    
    settings = {
        'require_auth': mcp_server.require_auth,
        'auth_method': mcp_server.auth_method,
        'allowed_ips': mcp_server.allowed_ips.split('\n') if mcp_server.allowed_ips else [],
        'log_requests': mcp_server.log_requests
    }
    
    # 根据认证方式添加相应配置
    if settings['auth_method'] == 'api_key':
        settings['api_key'] = mcp_server.api_key
    elif settings['auth_method'] == 'jwt':
        if mcp_server.jwt_public_key:
            settings['jwt_public_key'] = mcp_server.jwt_public_key
        if mcp_server.jwks_uri:
            settings['jwks_uri'] = mcp_server.jwks_uri
        if mcp_server.jwt_issuer:
            settings['jwt_issuer'] = mcp_server.jwt_issuer
        if mcp_server.jwt_audience:
            settings['jwt_audience'] = mcp_server.jwt_audience
        if mcp_server.jwt_algorithm:
            settings['jwt_algorithm'] = mcp_server.jwt_algorithm
    
    return settings
```

## 4. 接口设计

### 4.1 HTTP认证接口

所有FastMCP HTTP请求通过以下方式提供认证信息：

**请求头**:

```
Authorization: Bearer <token>
```

其中`<token>`为：

- API密钥认证：API密钥字符串
- JWT认证：完整的JWT令牌

### 4.2 JWT令牌结构

标准JWT令牌包含三部分：Header、Payload和Signature

**示例Header**:

```json
{
  "alg": "RS256",
  "typ": "JWT"
}
```

**示例Payload**:

```json
{
  "sub": "1234567890",
  "name": "用户名称",
  "iss": "认证服务器标识符",
  "aud": "mcp-server",
  "iat": 1516239022,
  "exp": 1516242622
}
```

## 5. 测试策略

### 5.1 单元测试

针对认证功能的单元测试包括：

1. API密钥认证测试用例
    - 有效API密钥测试
    - 无效API密钥测试
    - 缺少Authorization头测试

2. JWT认证测试用例
    - 有效JWT令牌测试
    - 过期JWT令牌测试
    - 签名无效JWT令牌测试
    - 发行者/受众不匹配测试

### 5.2 集成测试

确保认证机制与FastMCP服务的其他组件集成正常：

1. API密钥到JWT迁移测试
2. IP白名单与JWT组合测试
3. 日志记录功能测试

## 6. 安全考虑

1. **密钥管理**
    - JWT私钥安全存储
    - 公钥适当保护
    - 定期密钥轮换机制

2. **防护措施**
    - 令牌过期机制
    - IP地址过滤
    - 权限最小化原则

3. **日志与监控**
    - 认证失败记录
    - 异常访问模式检测
