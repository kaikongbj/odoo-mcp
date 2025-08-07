# FastMCP JWT 认证 - 使用指南

## 1. 认证配置指南

### 1.1 API密钥认证配置

1. 在Odoo后台导航至 `MCP管理` > `服务器` 菜单
2. 创建新服务器或编辑现有服务器
3. 在`安全配置`标签页中：
    - 勾选`启用认证`
    - 选择`认证方式`: **API密钥认证**
    - 填写`API密钥`字段
    - 可选：在`允许的IP地址`字段每行输入一个IP地址，限制访问

### 1.2 JWT认证配置

1. 在Odoo后台导航至 `MCP管理` > `服务器` 菜单
2. 创建新服务器或编辑现有服务器
3. 在`安全配置`标签页中：
    - 勾选`启用认证`
    - 选择`认证方式`: **JWT令牌认证**
    - 配置以下JWT参数（至少需要公钥或JWKS URI之一）：
        - `JWT公钥`: 粘贴PEM格式的RSA公钥
        - `JWKS URI`: 输入提供JWT密钥的JWKS端点URL
        - `JWT发行者`: 输入允许的令牌发行者标识符（可选）
        - `JWT受众`: 输入允许的令牌受众标识符（可选）
        - `JWT算法`: 默认为RS256，可根据需要修改
    - 可选：在`允许的IP地址`字段每行输入一个IP地址，限制访问

### 1.3 生成API密钥

使用以下Python代码生成安全的随机API密钥：

```python
import secrets
import string

def generate_api_key(length=32):
    """生成指定长度的随机API密钥"""
    alphabet = string.ascii_letters + string.digits
    api_key = ''.join(secrets.choice(alphabet) for _ in range(length))
    return api_key

# 生成32位API密钥
api_key = generate_api_key()
print(f"生成的API密钥: {api_key}")
```

### 1.4 生成JWT密钥对

使用以下Python代码生成RSA密钥对（用于JWT签名与验证）：

```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def generate_rsa_key_pair():
    """生成RSA密钥对，返回私钥和公钥的PEM格式字符串"""
    # 生成私钥
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    
    # 导出私钥为PEM格式
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')
    
    # 导出公钥为PEM格式
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    
    return private_pem, public_pem

# 生成RSA密钥对
private_key, public_key = generate_rsa_key_pair()
print(f"私钥 (保存在客户端用于签发JWT):\n{private_key}")
print(f"\n公钥 (配置在MCP服务器用于验证JWT):\n{public_key}")
```

## 2. 客户端调用指南

### 2.1 使用API密钥认证

#### Python示例

```python
import requests

def call_mcp_api_with_key(server_url, api_key, endpoint):
    """使用API密钥调用MCP API"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(
        f"{server_url}/{endpoint}",
        headers=headers
    )
    
    return response.status_code, response.json()

# 使用示例
server_url = "http://localhost:8069/mcp/server/1"
api_key = "your_api_key_here"
endpoint = "resources/list"

status, data = call_mcp_api_with_key(server_url, api_key, endpoint)
print(f"状态码: {status}")
print(f"响应数据: {data}")
```

#### cURL示例

```bash
curl -X GET "http://localhost:8069/mcp/server/1/resources/list" \
     -H "Authorization: Bearer your_api_key_here" \
     -H "Content-Type: application/json"
```

### 2.2 使用JWT认证

#### 创建JWT令牌（Python）

```python
import jwt
import time

def create_jwt_token(private_key, issuer, audience, subject, expiry_hours=1):
    """创建JWT令牌"""
    # 当前时间戳
    now = int(time.time())
    
    # 构建JWT载荷
    payload = {
        "iss": issuer,                      # 发行者
        "aud": audience,                    # 受众
        "sub": subject,                     # 主题(通常为用户ID)
        "iat": now,                         # 发行时间
        "exp": now + (3600 * expiry_hours)  # 过期时间
    }
    
    # 使用私钥签名JWT
    token = jwt.encode(payload, private_key, algorithm="RS256")
    
    return token

# 使用示例
private_key = """-----BEGIN PRIVATE KEY-----
...您的私钥内容...
-----END PRIVATE KEY-----"""

token = create_jwt_token(
    private_key=private_key,
    issuer="my-auth-service",
    audience="mcp-server",
    subject="user123",
    expiry_hours=1
)

print(f"JWT令牌: {token}")
```

#### 使用JWT令牌调用API（Python）

```python
import requests

def call_mcp_api_with_jwt(server_url, jwt_token, endpoint):
    """使用JWT令牌调用MCP API"""
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(
        f"{server_url}/{endpoint}",
        headers=headers
    )
    
    return response.status_code, response.json()

# 使用示例
server_url = "http://localhost:8069/mcp/server/1"
jwt_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."  # 您的JWT令牌
endpoint = "resources/list"

status, data = call_mcp_api_with_jwt(server_url, jwt_token, endpoint)
print(f"状态码: {status}")
print(f"响应数据: {data}")
```

#### cURL示例

```bash
curl -X GET "http://localhost:8069/mcp/server/1/resources/list" \
     -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." \
     -H "Content-Type: application/json"
```

## 3. 故障排除

### 3.1 常见错误与解决方案

| 错误消息                     | 可能原因            | 解决方案                     |
|--------------------------|-----------------|--------------------------|
| "无效的API密钥"               | API密钥不匹配        | 检查API密钥是否正确配置，无多余空格或换行符  |
| "无效或过期的JWT Bearer token" | JWT令牌签名验证失败或已过期 | 检查公钥配置是否正确，验证令牌是否过期      |
| "Authorization头格式错误"     | 认证头格式不正确        | 确保认证头格式为`Bearer <token>` |
| "缺少Authorization头"       | 请求中未包含认证头       | 添加包含正确令牌的Authorization头  |
| "IP地址未授权访问"              | 客户端IP不在白名单中     | 将客户端IP添加到服务器的IP白名单中      |
| "JWT认证错误: 无效的发行者"        | 令牌发行者与配置不匹配     | 确保令牌的iss字段与服务器配置匹配       |
| "JWT认证错误: 无效的受众"         | 令牌受众与配置不匹配      | 确保令牌的aud字段与服务器配置匹配       |

### 3.2 JWT令牌调试

使用[jwt.io](https://jwt.io/)在线工具可以帮助调试JWT令牌：

1. 访问[jwt.io](https://jwt.io/)网站
2. 将JWT令牌粘贴到"Encoded"文本框中
3. 网站会自动解码并显示令牌的头部和载荷内容
4. 可以在"Verify Signature"部分粘贴公钥和私钥以验证签名

### 3.3 日志分析

启用调试级别日志查看认证过程详细信息：

```bash
# 启动Odoo服务器时开启MCP服务器的调试日志
python odoo-bin --log-level=debug --log-handler=mcp_server:DEBUG
```

检查日志中的认证相关消息，以帮助排查问题：

```
2023-07-22 08:45:23,421 DEBUG mcp_server.services.fast_mcp_service: JWT认证: 开始验证令牌
2023-07-22 08:45:23,450 DEBUG mcp_server.services.fast_mcp_service: JWT认证: 验证失败 - 令牌已过期
```

## 4. 安全最佳实践

### 4.1 密钥管理

1. **私钥保护**：
    - JWT签名私钥应妥善保管，避免泄露
    - 考虑使用密钥管理系统或硬件安全模块(HSM)
    - 不要在代码或配置文件中明文存储私钥

2. **定期轮换密钥**：
    - API密钥：每90天更换一次
    - JWT密钥对：每180天更换一次

### 4.2 令牌安全性

1. **JWT最佳实践**：
    - 设置合理的过期时间（通常为几小时或一天）
    - 包含所有必要的声明（iss, sub, aud, exp, iat）
    - 避免在令牌中存储敏感信息

2. **传输安全**：
    - 始终通过HTTPS传输令牌
    - 避免在URL参数中传递令牌

### 4.3 其他安全措施

1. **IP白名单**：
    - 限制只有特定IP地址能访问服务
    - 定期审核和更新白名单

2. **监控与告警**：
    - 监控认证失败事件
    - 设置异常认证失败的告警阈值
