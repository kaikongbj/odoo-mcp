# 导入错误修复文档

## 错误描述

在加载MCP服务器模块时出现以下错误：

```
NameError: name 'threading' is not defined
```

## 错误原因

在`mcp_server/models/mcp_server.py`文件中，`threading`模块的导入语句位置错误：

```python
# 错误的导入顺序
_logger = logging.getLogger(__name__)

# 全局标志，确保自动启动只执行一次
_auto_start_executed = False
_auto_start_lock = threading.Lock()  # ❌ threading未定义
import threading  # ❌ 导入太晚了
```

## 修复方案

将`import threading`移动到文件开头的导入部分：

```python
# 正确的导入顺序
import importlib
import logging
import secrets
import string
import threading  # ✅ 在使用前导入

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# 全局标志，确保自动启动只执行一次
_auto_start_executed = False
_auto_start_lock = threading.Lock()  # ✅ 现在可以正常使用
```

## 修复验证

### 1. 语法检查

```bash
python -m py_compile mcp_server/models/mcp_server.py
# 应该没有错误输出
```

### 2. 导入检查

确认以下导入都在文件开头：

- ✅ `import threading`
- ✅ `import importlib`
- ✅ `import logging`
- ✅ `import secrets`
- ✅ `import string`

### 3. 使用检查

确认`threading.Lock()`在导入后使用：

- ✅ `_auto_start_lock = threading.Lock()`

## 最佳实践

### Python导入顺序规范

1. **标准库导入**（按字母顺序）

```python
import importlib
import logging
import secrets
import string
import threading
```

2. **第三方库导入**

```python
# 如果有第三方库
```

3. **本地应用导入**

```python
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
```

### 避免导入错误的建议

1. **始终在文件开头导入**：不要在函数内部或类定义中导入全局使用的模块
2. **按规范排序**：标准库 → 第三方库 → 本地模块
3. **及时测试**：修改导入后立即进行语法检查
4. **使用IDE检查**：现代IDE会标记未定义的名称

## 修复日期

2025-07-22

## 相关文件

- `mcp_server/models/mcp_server.py` - 主要修复文件
- `AUTO_START_FIX.md` - 相关的自动启动修复文档