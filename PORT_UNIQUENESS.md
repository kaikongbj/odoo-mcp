# MCP服务器端口唯一性实现文档

## 功能概述

为确保每个MCP服务器实例都运行在唯一的端口上，我们实现了端口唯一性约束和验证机制，防止端口冲突导致服务器启动失败。

## 实现方式

### 1. 数据库级别唯一性约束

使用SQL约束确保数据库级别的端口唯一性：

```python
_sql_constraints = [
    ('server_port_unique', 'unique(server_port)', '服务器端口必须唯一！')
]
```

### 2. 应用级别验证

添加`@api.constrains`装饰器验证端口唯一性：

```python
@api.constrains('server_port')
def _check_server_port(self):
    """验证服务器端口唯一性"""
    for record in self:
        if not record.server_port:
            continue
            
        # 检查是否有其他记录使用相同的端口
        same_port_records = self.search([
            ('id', '!=', record.id),
            ('server_port', '=', record.server_port)
        ])
        
        if same_port_records:
            raise ValidationError(_(
                '端口 %s 已被服务器 "%s" 使用，请选择其他端口。'
            ) % (record.server_port, same_port_records[0].name))
```

### 3. 创建和更新时验证

在`create`和`write`方法中添加端口唯一性验证：

```python
@api.model
def create(self, vals):
    if 'server_port' in vals:
        # 检查端口是否已被使用
        same_port_records = self.search([('server_port', '=', vals['server_port'])])
        if same_port_records:
            raise ValidationError(_(
                '端口 %s 已被服务器 "%s" 使用，请选择其他端口。'
            ) % (vals['server_port'], same_port_records[0].name))
    # ...

def write(self, vals):
    if 'server_port' in vals:
        # 检查端口是否已被其他服务器使用
        same_port_records = self.search([
            ('id', 'not in', self.ids),
            ('server_port', '=', vals['server_port'])
        ])
        
        if same_port_records:
            raise ValidationError(_(
                '端口 %s 已被服务器 "%s" 使用，请选择其他端口。'
            ) % (vals['server_port'], same_port_records[0].name))
    # ...
```

### 4. 智能端口分配

改进`_get_next_available_port`方法，使用多种策略查找可用端口：

```python
def _get_next_available_port(self):
    """获取下一个可用的端口号"""
    import socket
    import random
    
    # 端口范围配置
    start_port = 10888
    max_port = 11000  # 最大端口范围
    
    # 获取已使用的端口
    used_ports = set()
    existing_servers = self.search([('server_port', '!=', False)])
    for server in existing_servers:
        if server.server_port:
            used_ports.add(server.server_port)
    
    # 首先尝试顺序查找
    for port in range(start_port, max_port):
        if port not in used_ports:
            # 检查端口是否真的可用
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(('127.0.0.1', port))
                sock.close()
                return port
            except OSError:
                continue
    
    # 如果顺序查找失败，尝试随机端口
    attempts = 0
    while attempts < 50:  # 最多尝试50次
        attempts += 1
        port = random.randint(20000, 65000)  # 使用高端口范围
        if port not in used_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(('127.0.0.1', port))
                sock.close()
                return port
            except OSError:
                continue
```

### 5. 端口可用性检查

添加端口可用性检查功能：

```python
def action_check_port_availability(self):
    """检查端口是否可用"""
    self.ensure_one()
    import socket
    
    try:
        # 检查端口是否被占用
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', self.server_port))
        sock.close()
        
        if result == 0:
            # 端口已被占用
            return notification('端口已被占用')
        else:
            # 端口可用
            return notification('端口可用')
    except Exception as e:
        return notification('检查错误')
```

## 用户界面改进

### 1. 端口字段突出显示

```xml
<field name="server_port" required="1" 
       options="{'bg_color': 'bg-primary', 'text_color': 'text-white'}"
       help="每个服务器必须使用唯一的端口，范围10888-65000"/>
```

### 2. 端口检查按钮

```xml
<button name="action_check_port_availability" string="检查端口" type="object" 
        class="btn-secondary" icon="fa-plug"
        help="检查端口是否可用"/>
```

## 错误处理

### 1. 创建/更新时的错误消息

当尝试使用已被占用的端口时，系统会显示清晰的错误消息：

```
端口 10888 已被服务器 "默认MCP服务器" 使用，请选择其他端口。
```

### 2. 端口检查结果

端口检查功能会返回以下结果之一：

- **成功**：端口可用
- **警告**：端口已被占用
- **错误**：检查过程中发生错误

## 使用指南

### 1. 创建新服务器

创建新服务器时，系统会自动分配一个可用端口。用户也可以手动指定端口，但必须确保该端口未被其他服务器使用。

### 2. 修改服务器端口

修改服务器端口时，系统会验证新端口是否可用。如果端口已被其他服务器使用，系统会显示错误消息。

### 3. 检查端口可用性

用户可以随时点击"检查端口"按钮，验证当前配置的端口是否可用。

## 最佳实践

1. **使用自动分配**：尽量使用系统自动分配的端口，避免手动指定
2. **避免低端口**：避免使用低于1024的端口，这些端口通常需要管理员权限
3. **定期检查**：定期使用"检查端口"功能验证端口可用性
4. **端口范围**：建议使用10888-65000范围内的端口
5. **停止未使用服务器**：不需要的服务器应停止运行，释放端口资源

## 技术说明

1. **SQL约束**：数据库级别的唯一性约束，防止重复端口
2. **API约束**：应用级别的验证，提供友好的错误消息
3. **端口检测**：使用socket连接测试端口是否被占用
4. **多级策略**：顺序查找和随机分配相结合的端口分配策略
5. **用户反馈**：清晰的错误消息和状态通知

## 版本信息

- **功能版本**: 1.0
- **更新日期**: 2025-07-22
- **兼容性**: Odoo 17.0+