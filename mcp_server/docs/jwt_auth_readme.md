# FastMCP JWT 认证 - 简介

## 概述

FastMCP JWT认证模块扩展了标准的FastMCP服务器功能，提供了基于JWT (JSON Web Tokens) Bearer
Token的认证机制，在保持现有API密钥认证兼容性的同时，大幅提升了系统安全性和灵活性。

## 主要特性

- **双模式认证**：同时支持API密钥认证和JWT Bearer Token认证
- **完整的JWT验证**：签名验证、过期检查、发行者与受众验证
- **多种配置选项**：支持RSA公钥或JWKS URI验证方式
- **增强的安全性**：IP白名单过滤与认证事件日志
- **Odoo集成**：与Odoo管理界面完美整合，提供直观的配置体验

## 快速入门

### 配置JWT认证

1. 在Odoo后台进入 `MCP管理` > `服务器` > 选择一个服务器
2. 在`安全配置`标签页中：
    - 选择 `认证方式`: **JWT令牌认证**
    - 填写 `JWT公钥` 或 `JWKS URI`
    - 可选配置 `JWT发行者`、`JWT受众` 等字段

### 使用JWT认证

所有API请求需要在头部包含有效的JWT令牌：

```
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...
```

## 文档导航

详细信息请参考以下文档：

- [功能需求文档](jwt_auth_requirements.md) - 详细的功能规格与需求
- [架构设计文档](jwt_auth_architecture.md) - 系统设计与技术实现
- [使用指南](jwt_auth_usage.md) - 详细的配置与使用方法

## 系统要求

- Odoo 15.0+
- FastMCP 2.4.0+
- PyJWT 2.6.0+
- cryptography 41.0.0+

## 安装

确保已安装所需依赖：

```bash
pip install PyJWT>=2.6.0 cryptography>=41.0.0
```

## 兼容性与迁移

本模块完全向后兼容现有的API密钥认证方式。现有服务器实例可继续使用API密钥认证，无需任何迁移操作。如需升级到JWT认证，仅需在配置界面切换认证方式并提供所需参数。
