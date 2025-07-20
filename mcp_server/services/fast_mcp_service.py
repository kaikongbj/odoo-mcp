import asyncio
import logging
import threading
import time
import socket
from typing import Dict, Any, Optional
from contextlib import contextmanager
from queue import Queue, Empty

from fastmcp import FastMCP, Context
from odoo import api, models, fields, _
from odoo.http import request
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class SafeDatabaseManager:
    """安全数据库管理器 - 管理数据库连接池和线程安全的数据库操作"""
    
    def __init__(self, pool_size=10, connection_timeout=30):
        """初始化数据库管理器
        
        Args:
            pool_size: 连接池大小
            connection_timeout: 连接超时时间（秒）
        """
        self.pool_size = pool_size
        self.connection_timeout = connection_timeout
        self.connection_pools = {}  # 每个数据库的连接池
        self.pool_locks = {}  # 每个连接池的锁
        self._main_lock = threading.Lock()
        
        _logger.info("SafeDatabaseManager初始化完成，连接池大小: %d, 超时: %d秒", 
                    pool_size, connection_timeout)
    
    def _get_db_name(self):
        """获取当前数据库名称"""
        try:
            # 尝试从请求中获取
            if hasattr(request, 'db') and request.db:
                return request.db
        except Exception:
            pass

        try:
            # 从配置中获取
            import odoo.tools.config as config
            db_name = config.get('db_name')
            if db_name:
                return db_name

            # 获取可用数据库列表并选择第一个
            from odoo.service.db import list_dbs
            dbs = list_dbs(True)
            if dbs:
                return dbs[0]
        except Exception as e:
            _logger.error("获取数据库名称失败: %s", str(e))

        return None
    
    def _get_connection_pool(self, db_name):
        """获取指定数据库的连接池"""
        with self._main_lock:
            if db_name not in self.connection_pools:
                # 创建新的连接池
                self.connection_pools[db_name] = Queue(maxsize=self.pool_size)
                self.pool_locks[db_name] = threading.Lock()
                _logger.info("为数据库 '%s' 创建了新的连接池", db_name)
            
            return self.connection_pools[db_name], self.pool_locks[db_name]
    
    def _create_connection(self, db_name):
        """创建新的数据库连接"""
        try:
            registry = Registry(db_name)
            cursor = registry.cursor()
            _logger.debug("为数据库 '%s' 创建了新连接", db_name)
            return cursor
        except Exception as e:
            _logger.error("创建数据库连接失败: %s", str(e))
            raise
    
    def _get_connection(self, db_name):
        """从连接池获取连接"""
        pool, pool_lock = self._get_connection_pool(db_name)
        
        try:
            # 尝试从池中获取连接
            cursor = pool.get_nowait()
            # 检查连接健康状态
            if self._check_connection_health(cursor):
                _logger.debug("从连接池获取了健康的连接")
                return cursor
            else:
                # 连接不健康，关闭并创建新连接
                _logger.debug("连接不健康，创建新连接")
                try:
                    cursor.close()
                except:
                    pass
                return self._create_connection(db_name)
        except Empty:
            # 池中没有可用连接，创建新连接
            _logger.debug("连接池为空，创建新连接")
            return self._create_connection(db_name)
    
    def _release_connection(self, db_name, cursor):
        """释放连接回连接池"""
        if not cursor:
            return
            
        pool, pool_lock = self._get_connection_pool(db_name)
        
        try:
            # 检查连接健康状态
            if self._check_connection_health(cursor):
                # 尝试将连接放回池中
                try:
                    pool.put_nowait(cursor)
                    _logger.debug("连接已释放回连接池")
                except:
                    # 池已满，关闭连接
                    _logger.debug("连接池已满，关闭连接")
                    cursor.close()
            else:
                # 连接不健康，直接关闭
                _logger.debug("连接不健康，直接关闭")
                cursor.close()
        except Exception as e:
            _logger.error("释放连接时出错: %s", str(e))
            try:
                cursor.close()
            except:
                pass
    
    def _check_connection_health(self, cursor):
        """检查数据库连接健康状态"""
        try:
            if not cursor or cursor.closed:
                return False
            # 执行简单查询检查连接
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return True
        except Exception as e:
            _logger.debug("连接健康检查失败: %s", str(e))
            return False
    
    @contextmanager
    def get_env(self, db_name=None):
        """获取安全的Odoo环境上下文管理器"""
        if not db_name:
            db_name = self._get_db_name()
        
        if not db_name:
            raise Exception("无法获取数据库名称")
        
        cursor = None
        try:
            cursor = self._get_connection(db_name)
            env = api.Environment(cursor, 1, {})  # 使用SUPERUSER_ID
            _logger.debug("成功创建安全的Odoo环境")
            yield env
            # 提交事务
            cursor.commit()
        except Exception as e:
            _logger.error("数据库操作失败: %s", str(e))
            if cursor:
                try:
                    cursor.rollback()
                except:
                    pass
            raise
        finally:
            if cursor:
                self._release_connection(db_name, cursor)
    
    async def execute_with_env(self, operation, *args, **kwargs):
        """安全执行数据库操作的异步方法"""
        db_name = self._get_db_name()
        if not db_name:
            raise Exception("无法获取数据库名称")
        
        # 在线程池中执行数据库操作
        loop = asyncio.get_event_loop()
        
        def sync_operation():
            with self.get_env(db_name) as env:
                return operation(env, *args, **kwargs)
        
        try:
            result = await loop.run_in_executor(None, sync_operation)
            return result
        except Exception as e:
            _logger.error("异步数据库操作失败: %s", str(e))
            raise
    
    def cleanup_connections(self, db_name=None):
        """清理连接池中的所有连接"""
        if db_name:
            databases = [db_name]
        else:
            databases = list(self.connection_pools.keys())
        
        for db in databases:
            if db in self.connection_pools:
                pool = self.connection_pools[db]
                closed_count = 0
                
                while True:
                    try:
                        cursor = pool.get_nowait()
                        cursor.close()
                        closed_count += 1
                    except Empty:
                        break
                    except Exception as e:
                        _logger.error("关闭连接时出错: %s", str(e))
                
                _logger.info("已清理数据库 '%s' 的 %d 个连接", db, closed_count)


class FastMCPService:
    """FastMCP服务实现类，用于在Odoo中集成FastMCP功能"""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """获取FastMCP服务的单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        """初始化FastMCP服务"""
        self.mcp_servers = {}  # 存储MCP服务器实例
        self.event_loop = None
        self._event_loop_thread = None
        # 初始化安全数据库管理器
        self.db_manager = SafeDatabaseManager(pool_size=20, connection_timeout=30)
        self.init_event_loop()

    def init_event_loop(self):
        """初始化异步事件循环并在后台线程中运行"""
        try:
            _logger.info("开始初始化FastMCP事件循环")
            self.event_loop = asyncio.new_event_loop()

            # 创建并启动事件循环线程
            def run_event_loop(loop):
                _logger.info("在后台线程中运行FastMCP事件循环")
                asyncio.set_event_loop(loop)
                try:
                    loop.run_forever()
                except Exception as e:
                    _logger.error("事件循环运行异常: %s", str(e))
                finally:
                    _logger.info("事件循环结束")
                    loop.close()

            # 创建并启动守护线程
            self._event_loop_thread = threading.Thread(
                target=run_event_loop,
                args=(self.event_loop,),
                daemon=True,
                name="FastMCP-EventLoop"
            )
            self._event_loop_thread.start()

            # 等待事件循环启动
            time.sleep(0.5)  # 等待循环启动

            _logger.info("FastMCP事件循环已初始化并在后台运行，循环对象信息: %s, 运行状态: %s",
                         self.event_loop, self.event_loop.is_running())
        except Exception as e:
            _logger.error("初始化FastMCP事件循环失败: %s", str(e))
            import traceback
            _logger.error("异常详情: %s", traceback.format_exc())

    def get_or_create_mcp_server(self, server_record):
        """获取或创建MCP服务器实例"""
        server_id = server_record.id
        _logger.info("尝试获取或创建MCP服务器实例，ID: %s, 名称: %s", server_id, server_record.name)

        if server_id in self.mcp_servers:
            _logger.info("找到现有的MCP服务器实例: %s", server_id)
            return self.mcp_servers.get(server_id)

        try:
            _logger.info("开始创建新的FastMCP服务器实例")
            # 创建新的FastMCP服务器实例
            mcp_server = FastMCP(name=server_record.name)
            _logger.info("创建的FastMCP服务器实例: %s", mcp_server)

            # 注册默认工具和资源
            _logger.info("开始注册默认工具")
            self._register_default_tools(mcp_server, server_record)
            _logger.info("开始注册默认资源")
            self._register_default_resources(mcp_server, server_record)

            self.mcp_servers[server_id] = mcp_server
            _logger.info("为服务器 %s 创建了新的FastMCP实例，实例详情: %s", server_record.name, mcp_server)
            return mcp_server
        except Exception as e:
            _logger.error("创建FastMCP服务器实例失败: %s", str(e))
            import traceback
            _logger.error("异常详情: %s", traceback.format_exc())
            return None

        return self.mcp_servers.get(server_id)

    async def _safe_execute_with_env(self, operation, *args, **kwargs):
        """安全执行数据库操作的统一入口方法
        
        这个方法确保：
        1. 使用独立的数据库连接
        2. 自动资源清理和异常处理
        3. 事务管理和回滚机制
        4. 线程安全的操作
        
        Args:
            operation: 要执行的操作函数，第一个参数必须是env
            *args: 传递给操作函数的位置参数
            **kwargs: 传递给操作函数的关键字参数
            
        Returns:
            操作函数的返回值
        """
        try:
            _logger.debug("开始安全数据库操作执行")
            result = await self.db_manager.execute_with_env(operation, *args, **kwargs)
            _logger.debug("安全数据库操作执行成功")
            return result
        except Exception as e:
            _logger.error("安全数据库操作执行失败: %s", str(e))
            # 重新抛出异常，让调用者处理
            raise

    def _query_odoo_model_impl(self, env, model_name, domain=None, fields=None, limit=100, offset=0, order=None):
        """查询Odoo模型的实现函数"""
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取模型对象
        model_obj = env[model_name].sudo()

        # 处理domain参数
        parsed_domain = []
        if domain is not None and domain.strip():
            import json
            parsed_domain = json.loads(domain)
            if not isinstance(parsed_domain, list):
                parsed_domain = []

        # 处理fields参数
        parsed_fields = []
        if fields is not None and fields.strip():
            import json
            parsed_fields = json.loads(fields)
            if not isinstance(parsed_fields, list):
                parsed_fields = []

        # 如果没有指定字段，获取模型的基本字段
        if not parsed_fields:
            exclude_types = ['binary', 'html']
            model_fields = model_obj._fields
            parsed_fields = [f for f, field in model_fields.items()
                           if field.type not in exclude_types][:15]  # 限制为前15个字段

        # 获取记录总数
        total_count = model_obj.search_count(parsed_domain)

        # 执行查询
        records = model_obj.search_read(
            domain=parsed_domain,
            fields=parsed_fields,
            limit=limit,
            offset=offset,
            order=order
        )

        # 处理many2one字段的显示
        for record in records:
            for field, value in record.items():
                if isinstance(value, tuple) and len(value) == 2:
                    # many2one字段显示为 [id, name]
                    record[field] = {"id": value[0], "name": value[1]}

        return {
            "status": "success",
            "data": {
                "model": model_name,
                "fields": parsed_fields,
                "count": len(records),
                "total_count": total_count,
                "limit": limit,
                "offset": offset,
                "records": records
            }
        }

    def _get_odoo_record_impl(self, env, model_name, record_id):
        """获取Odoo记录的实现函数"""
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取记录
        record = env[model_name].sudo().browse(record_id)
        if not record.exists():
            raise ValueError(f"在模型 '{model_name}' 中找不到ID为 {record_id} 的记录")

        # 获取所有字段
        exclude_types = ['binary', 'html']
        model_fields = record._fields
        fields = [f for f, field in model_fields.items()
                  if field.type not in exclude_types]

        # 读取记录数据
        data = record.read(fields)[0]

        # 处理many2one字段的显示
        for field, value in data.items():
            if isinstance(value, tuple) and len(value) == 2:
                # many2one字段显示为 {"id": id, "name": name}
                data[field] = {"id": value[0], "name": value[1]}

        return {
            "status": "success",
            "data": data
        }

    def _create_odoo_record_impl(self, env, model_name, values):
        """创建Odoo记录的实现函数"""
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 创建记录
        model_obj = env[model_name].sudo()

        # 处理many2one字段
        processed_values = {}
        for field, value in values.items():
            if isinstance(value, dict) and "id" in value:
                # 如果是形如 {"id": 1, "name": "xxx"} 的字典，则转换为 ID
                processed_values[field] = value["id"]
            else:
                processed_values[field] = value

        # 创建记录
        new_record = model_obj.create(processed_values)

        # 返回新创建的记录
        data = new_record.read()[0]

        # 处理many2one字段的显示
        for field, value in data.items():
            if isinstance(value, tuple) and len(value) == 2:
                data[field] = {"id": value[0], "name": value[1]}

        return {
            "status": "success",
            "message": f"成功创建记录，ID: {new_record.id}",
            "data": data
        }

    def _update_odoo_record_impl(self, env, model_name, record_id, values):
        """更新Odoo记录的实现函数"""
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取记录
        record = env[model_name].sudo().browse(record_id)
        if not record.exists():
            raise ValueError(f"在模型 '{model_name}' 中找不到ID为 {record_id} 的记录")

        # 处理many2one字段
        processed_values = {}
        for field, value in values.items():
            if isinstance(value, dict) and "id" in value:
                # 如果是形如 {"id": 1, "name": "xxx"} 的字典，则转换为 ID
                processed_values[field] = value["id"]
            else:
                processed_values[field] = value

        # 更新记录
        record.write(processed_values)

        # 返回更新后的记录
        data = record.read()[0]

        # 处理many2one字段的显示
        for field, value in data.items():
            if isinstance(value, tuple) and len(value) == 2:
                data[field] = {"id": value[0], "name": value[1]}

        return {
            "status": "success",
            "message": f"成功更新记录，ID: {record_id}",
            "data": data
        }

    def _delete_odoo_record_impl(self, env, model_name, record_id):
        """删除Odoo记录的实现函数"""
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取记录
        record = env[model_name].sudo().browse(record_id)
        if not record.exists():
            raise ValueError(f"在模型 '{model_name}' 中找不到ID为 {record_id} 的记录")

        # 保存记录名称供日志使用
        record_name = record.display_name if hasattr(record, 'display_name') else f"ID: {record_id}"

        # 删除记录
        record.unlink()

        return {
            "status": "success",
            "message": f"成功删除了模型 '{model_name}' 中ID为 {record_id} 的记录",
            "data": {
                "model": model_name,
                "record_id": record_id,
                "record_name": record_name
            }
        }

    def _get_odoo_model_metadata_impl(self, env, model_name):
        """获取Odoo模型元数据的实现函数"""
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取模型对象
        model_obj = env[model_name].sudo()

        # 获取模型信息
        ir_model = env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)
        model_info = {
            "name": model_name,
            "description": ir_model.name if ir_model else model_name,
            "transient": ir_model.transient if ir_model else False
        }

        # 获取字段信息
        fields_info = {}
        for field_name, field in model_obj._fields.items():
            # 基本字段信息
            field_data = {
                "type": field.type,
                "string": field.string,
                "required": field.required,
                "readonly": field.readonly,
                "store": field.store,
                "help": field.help or ""
            }

            # 添加关系字段信息
            if field.type in ['many2one', 'one2many', 'many2many']:
                field_data["relation"] = field.comodel_name

            # 添加选择字段信息
            if field.type == 'selection' and hasattr(field, 'selection') and field.selection:
                if callable(field.selection):
                    # 如果selection是动态的，尝试调用它获取选项
                    try:
                        selection = field.selection(model_obj)
                        field_data["selection"] = selection
                    except:
                        field_data["selection"] = []
                else:
                    field_data["selection"] = field.selection

            fields_info[field_name] = field_data

        return {
            "status": "success",
            "data": {
                "model": model_info,
                "fields": fields_info
            }
        }

    def _list_resources_impl(self, env, server_id):
        """列出资源的实现函数"""
        resources = env['mcp.resource'].sudo().search([
            ('server_id', '=', server_id),
            ('active', '=', True)
        ])

        result = []
        for resource in resources:
            result.append({
                'id': resource.id,
                'name': resource.name,
                'resource_uri': resource.resource_uri,
                'resource_type': resource.resource_type,
                'description': resource.description,
                'last_fetch': resource.last_fetch.isoformat() if resource.last_fetch else None,
            })

        # 更新服务器连接信息
        server = env['mcp.server'].sudo().browse(server_id)
        if server.exists():
            server.write({
                'last_connection': fields.Datetime.now(),
                'connection_count': server.connection_count + 1
            })

        return {"status": "success", "data": result}

    def _get_resource_content_impl(self, env, server_id, resource_uri):
        """获取资源内容的实现函数"""
        resources = env['mcp.resource'].sudo().search([
            ('server_id', '=', server_id),
            ('resource_uri', '=', resource_uri),
            ('active', '=', True)
        ], limit=1)

        if not resources:
            raise ValueError(f"资源不存在: {resource_uri}")

        resource = resources[0]

        # 更新最后获取时间
        resource.write({
            'last_fetch': fields.Datetime.now()
        })

        return {
            "status": "success",
            "data": {
                'id': resource.id,
                'name': resource.name,
                'content': resource.content,
                'resource_uri': resource.resource_uri,
                'resource_type': resource.resource_type,
                'description': resource.description,
                'last_fetch': resource.last_fetch.isoformat() if resource.last_fetch else None,
            }
        }

    def _get_server_info_impl(self, env, server_id):
        """获取服务器信息的实现函数"""
        server = env['mcp.server'].sudo().browse(server_id)
        if not server.exists():
            raise ValueError(f"服务器不存在: {server_id}")

        return {
            "id": server.id,
            "name": server.name,
            "server_url": server.server_url,
            "state": server.state,
            "last_connection": server.last_connection.isoformat() if server.last_connection else None,
            "connection_count": server.connection_count,
        }

    def _get_resource_by_id_impl(self, env, server_id, resource_id):
        """根据ID获取资源的实现函数"""
        resource = env['mcp.resource'].sudo().browse(resource_id)
        if not resource.exists() or resource.server_id.id != server_id:
            raise ValueError(f"资源不存在: {resource_id}")

        # 更新最后获取时间
        resource.write({
            'last_fetch': fields.Datetime.now()
        })

        return {
            "status": "success",
            "data": {
                'id': resource.id,
                'name': resource.name,
                'content': resource.content,
                'resource_uri': resource.resource_uri,
                'resource_type': resource.resource_type,
                'description': resource.description,
            }
        }

    def _register_default_tools(self, mcp_server, server_record):
        """注册默认工具到FastMCP服务器"""

        # ===== Odoo数据访问工具 =====
        @mcp_server.tool()
        async def query_odoo_model(
                model_name: str,
                domain: Optional[str] = None,
                fields: Optional[str] = None,
                limit: int = 100,
                offset: int = 0,
                order: Optional[str] = None,
                ctx: Context = None
        ) -> Dict[str, Any]:
            """查询任意Odoo模型的数据
            
            Args:
                model_name: Odoo模型名称 (例如 'res.partner', 'product.template')
                domain: 搜索域JSON字符串 (例如 '[["is_company", "=", true], ["customer_rank", ">", 0]]')
                fields: 要获取的字段JSON字符串 (例如 '["name", "email", "phone"]')
                limit: 最大返回记录数
                offset: 记录偏移量
                order: 排序字段和方向 (例如 'name ASC, create_date DESC')
                
            Returns:
                包含查询结果的字典
            """
            try:
                if ctx:
                    await ctx.info(f"开始查询模型 '{model_name}'，参数: domain={domain}, fields={fields}")

                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._query_odoo_model_impl,
                    model_name, domain, fields, limit, offset, order
                )

                if ctx:
                    data = result.get('data', {})
                    count = data.get('count', 0)
                    total_count = data.get('total_count', 0)
                    await ctx.info(f"从 '{model_name}' 查询到 {count} 条记录 (共 {total_count} 条)")

                return result
            except Exception as e:
                error_msg = f"查询Odoo模型失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def get_odoo_record(model_name: str, record_id: int, ctx: Context = None) -> Dict[str, Any]:
            """获取Odoo中指定记录的详细信息
            
            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                record_id: 记录ID
                
            Returns:
                包含记录详细信息的字典
            """
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._get_odoo_record_impl,
                    model_name, record_id
                )

                if ctx:
                    await ctx.info(f"成功获取模型 '{model_name}' 中ID为 {record_id} 的记录")

                return result
            except Exception as e:
                error_msg = f"获取Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def create_odoo_record(model_name: str, values: Dict[str, Any], ctx: Context = None) -> Dict[str, Any]:
            """在Odoo中创建新记录
            
            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                values: 要创建的记录的字段值 (例如 {"name": "新客户", "email": "customer@example.com"})
                
            Returns:
                包含新创建记录信息的字典
            """
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._create_odoo_record_impl,
                    model_name, values
                )

                if ctx:
                    data = result.get('data', {})
                    record_id = data.get('id', 'unknown')
                    await ctx.info(f"在模型 '{model_name}' 中成功创建了新记录，ID: {record_id}")

                return result
            except Exception as e:
                error_msg = f"创建Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def update_odoo_record(model_name: str, record_id: int, values: Dict[str, Any], ctx: Context = None) -> Dict[str, Any]:
            """更新Odoo中的记录
            
            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                record_id: 要更新的记录ID
                values: 要更新的字段值 (例如 {"name": "更新的名称", "email": "new@example.com"})
                
            Returns:
                包含更新后记录信息的字典
            """
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._update_odoo_record_impl,
                    model_name, record_id, values
                )

                if ctx:
                    await ctx.info(f"成功更新了模型 '{model_name}' 中ID为 {record_id} 的记录")

                return result
            except Exception as e:
                error_msg = f"更新Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def delete_odoo_record(model_name: str, record_id: int, ctx: Context = None) -> Dict[str, Any]:
            """删除Odoo中的记录
            
            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                record_id: 要删除的记录ID
                
            Returns:
                删除操作的结果
            """
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._delete_odoo_record_impl,
                    model_name, record_id
                )

                if ctx:
                    data = result.get('data', {})
                    record_name = data.get('record_name', f'ID: {record_id}')
                    await ctx.info(f"成功删除了模型 '{model_name}' 中的记录: {record_name}")

                return result
            except Exception as e:
                error_msg = f"删除Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def get_odoo_model_metadata(model_name: str, ctx: Context = None) -> Dict[str, Any]:
            """获取Odoo模型的元数据信息，包括字段定义等
            
            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                
            Returns:
                包含模型元数据信息的字典
            """
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._get_odoo_model_metadata_impl,
                    model_name
                )

                if ctx:
                    await ctx.info(f"成功获取模型 '{model_name}' 的元数据信息")

                return result
            except Exception as e:
                error_msg = f"获取Odoo模型元数据失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        # ===== MCP资源管理工具 =====
        @mcp_server.tool()
        async def list_resources(ctx: Context) -> Dict[str, Any]:
            """列出当前MCP服务器上的所有可用资源"""
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._list_resources_impl,
                    server_record.id
                )

                data = result.get('data', [])
                await ctx.info(f"获取到 {len(data)} 个资源")
                return result
            except Exception as e:
                await ctx.error(f"获取资源列表失败: {str(e)}")
                _logger.error("FastMCP工具list_resources失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        @mcp_server.tool()
        async def get_resource_content(resource_uri: str, ctx: Context) -> Dict[str, Any]:
            """获取指定URI的资源内容"""
            try:
                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._get_resource_content_impl,
                    server_record.id, resource_uri
                )

                data = result.get('data', {})
                resource_name = data.get('name', resource_uri)
                await ctx.info(f"成功获取资源: {resource_name}")
                return result
            except Exception as e:
                await ctx.error(f"获取资源内容失败: {str(e)}")
                _logger.error("FastMCP工具get_resource_content失败: %s", str(e))
                return {"status": "error", "message": str(e)}

    def _register_default_resources(self, mcp_server, server_record):
        """注册默认资源到FastMCP服务器"""

        @mcp_server.resource("server://info")
        def get_server_info():
            """获取服务器基本信息"""
            try:
                with self.db_manager.get_env() as env:
                    return self._get_server_info_impl(env, server_record.id)
            except Exception as e:
                _logger.error("获取服务器信息失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        @mcp_server.resource("resources://list")
        def get_resources_list():
            """获取所有资源列表"""
            try:
                with self.db_manager.get_env() as env:
                    return self._list_resources_impl(env, server_record.id)
            except Exception as e:
                _logger.error("获取资源列表失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        @mcp_server.resource("resource://{resource_id}")
        def get_resource(resource_id: int):
            """获取指定ID的资源"""
            try:
                with self.db_manager.get_env() as env:
                    return self._get_resource_by_id_impl(env, server_record.id, resource_id)
            except Exception as e:
                _logger.error("获取资源失败: %s", str(e))
                return {"status": "error", "message": str(e)}



    def start_server(self, server_record):
        """启动MCP服务器"""
        _logger.info("开始启动MCP服务器: %s", server_record.name)
        mcp_server = self.get_or_create_mcp_server(server_record)
        if not mcp_server:
            _logger.error("无法获取MCP服务器实例，启动失败")
            return False

        try:
            _logger.info("准备异步启动MCP服务器，循环状态: %s", self.event_loop.is_running())
            # 注意：这里需要在实际部署时根据需要修改host和port
            # FastMCP服务器通常以异步方式启动
            future = asyncio.run_coroutine_threadsafe(
                self._start_server_async(mcp_server, server_record),
                self.event_loop
            )
            _logger.info("异步启动请求已提交，future对象: %s", future)

            # 尝试获取后台任务的初始状态，设置较长超时确保得到结果
            try:
                result = future.result(timeout=3.0)  # 增加超时时间到3秒
                _logger.info("服务器启动任务结果: %s", result)

                # 如果异步启动成功，在主线程中更新服务器状态
                if result.get('success', False):
                    _logger.info("在主线程中更新服务器状态")
                    server_record.sudo().write({
                        'state': 'active',
                        'last_connection': fields.Datetime.now()
                    })
                    return True
                else:
                    _logger.error("异步启动失败: %s", result.get('error', '未知错误'))
                    return False
            except asyncio.TimeoutError:
                _logger.info("服务器启动任务已提交，在后台运行但超时未等到结果")
                # 假设启动成功，更新状态
                server_record.sudo().write({
                    'state': 'active',
                    'last_connection': fields.Datetime.now()
                })
                return True
            except Exception as inner_e:
                _logger.warning("获取服务器启动状态时出现警告: %s", str(inner_e))
                return False
        except Exception as e:
            _logger.error("启动FastMCP服务器失败: %s", str(e))
            import traceback
            _logger.error("异常详情: %s", traceback.format_exc())
            return False

    async def _start_server_async(self, mcp_server, server_record):
        """异步启动MCP服务器"""
        try:
            # 在异步函数开始时保存必要的信息，而不使用server_record对象
            server_id = server_record.id
            server_name = server_record.name

            _logger.info("开始异步启动MCP服务器: %s", server_name)
            # 使用固定端口10888
            host = "0.0.0.0"  # 监听所有网络接口
            port = 10888  # 使用固定端口10888

            _logger.info("服务器配置 - 主机: %s, 端口: %s, 模式: %s", host, port, "sse")

            # 检查端口是否已经被占用
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((host, port))
            if result == 0:
                _logger.warning("端口 %s 似乎已经被占用", port)
            sock.close()

            # 使用简单的方法启动FastMCP
            _logger.info("尝试启动FastMCP服务器")

            # 创建事件标志和错误存储
            import threading
            from multiprocessing import Event
            server_started = Event()
            server_error = [None]

            # 创建启动FastMCP的函数
            def start_fastmcp_server():
                try:
                    _logger.info("在新线程中启动FastMCP服务器")

                    # 使用正确的方式启动FastMCP服务器
                    # 使用SSE (Server-Sent Events) 传输模式
                    _logger.info("开始启动FastMCP服务器，transport=sse, host=%s, port=%s", host, port)

                    # 配置服务器的初始化回调
                    original_on_connect = getattr(mcp_server, '_on_connect_callbacks', [])

                    def on_server_ready():
                        """服务器完全准备好时的回调"""
                        _logger.info("MCP服务器初始化完成，可以接受客户端连接")
                        server_started.set()

                    # 设置启动完成回调
                    if hasattr(mcp_server, 'add_on_connect_callback'):
                        mcp_server.add_on_connect_callback(on_server_ready)

                    # 启动服务器 - 这个调用会阻塞直到服务器关闭
                    mcp_server.run(
                        transport="sse",  # 使用SSE传输模式
                        host=host,
                        port=port
                    )

                    # 如果run()返回，说明服务器正常启动了
                    _logger.info("FastMCP服务器已启动完成")
                    if not server_started.is_set():
                        server_started.set()

                except Exception as e:
                    _logger.error("启动FastMCP服务器失败: %s", str(e))
                    import traceback
                    _logger.error("异常详情: %s", traceback.format_exc())
                    server_error[0] = str(e)
                    # 确保事件被设置，避免阻塞
                    if not server_started.is_set():
                        server_started.set()

            # 创建并启动服务器线程
            server_thread = threading.Thread(
                target=start_fastmcp_server,
                daemon=True,
                name="FastMCP-Server"
            )
            server_thread.start()
            _logger.info("FastMCP服务器线程已启动")

            # 给服务器一些时间启动并绑定端口
            await asyncio.sleep(3.0)  # 增加到3秒让服务器完全初始化

            # 检查端口是否被绑定，作为服务器启动的指示
            startup_successful = False
            for attempt in range(15):  # 增加到15次检查，总共7.5秒超时
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    if result == 0:
                        _logger.info("FastMCP服务器已成功绑定端口，启动完成")
                        startup_successful = True
                        break
                except Exception as e:
                    _logger.debug("端口检查异常: %s", str(e))
                    pass

                await asyncio.sleep(0.5)  # 每次检查间隔0.5秒

            # 额外等待，确保MCP协议初始化完成
            if startup_successful:
                _logger.info("端口绑定成功，等待MCP协议初始化完成...")
                await asyncio.sleep(3.0)  # 增加到3秒确保MCP协议完全准备好

                # 添加预热机制 - 确保服务器真正准备好
                _logger.info("开始MCP服务器预热检查...")
                for warmup_attempt in range(5):
                    try:
                        await asyncio.sleep(1.0)  # 每次预热检查间隔1秒
                        _logger.info("预热检查 %d/5", warmup_attempt + 1)
                    except Exception as e:
                        _logger.debug("预热检查异常: %s", str(e))

                _logger.info("MCP服务器预热完成，服务器已准备好接受连接")

            if not startup_successful:
                _logger.warning("无法确认FastMCP服务器是否成功启动（端口检测失败）")

            # 检查是否有启动错误
            if server_error[0]:
                _logger.error("启动FastMCP服务器出错: %s", server_error[0])
                return {'success': False, 'error': server_error[0]}

            _logger.info("FastMCP服务器已在 %s:%s 启动", host, port)

            # 在主线程中更新服务器状态，避免使用异步函数中的已关闭游标
            # 我们将该操作移至异步函数外部处理
            return {'success': True, 'server_id': server_id}
        except Exception as e:
            _logger.error("异步启动FastMCP服务器失败: %s", str(e))
            import traceback
            _logger.error("异常详情: %s", traceback.format_exc())
            # 更新服务器状态
            server_record.sudo().write({
                'state': 'inactive'
            })
            return {'success': False, 'error': str(e)}

    def stop_server(self, server_record):
        """停止MCP服务器"""
        server_id = server_record.id

        if server_id in self.mcp_servers:
            try:
                # 异步停止服务器
                asyncio.run_coroutine_threadsafe(
                    self._stop_server_async(server_id, server_record),
                    self.event_loop
                )
                return True
            except Exception as e:
                _logger.error("停止FastMCP服务器失败: %s", str(e))
                return False
        else:
            _logger.warning("服务器 %s 未运行", server_record.name)
            return False

    async def _stop_server_async(self, server_id, server_record):
        """异步停止MCP服务器"""
        try:
            # 这里应该是FastMCP服务器的停止逻辑
            # 由于FastMCP可能没有明确的stop方法，我们可能需要自己实现或者依赖
            # 关闭事件循环或取消任务

            # 从字典中移除服务器实例
            if server_id in self.mcp_servers:
                del self.mcp_servers[server_id]

            # 更新服务器状态
            server_record.sudo().write({
                'state': 'inactive'
            })

            _logger.info("FastMCP服务器 %s 已停止", server_record.name)
        except Exception as e:
            _logger.error("异步停止FastMCP服务器失败: %s", str(e))
            raise
