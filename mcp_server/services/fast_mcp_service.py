import asyncio
import logging
import os
import socket
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Any, Dict, Optional

import odoo
from fastmcp import FastMCP, Context
from odoo import api, fields, SUPERUSER_ID
from odoo.exceptions import AccessError, AccessDenied, UserError

_logger = logging.getLogger(__name__)


class SafeDatabaseManager:
    """提供在独立连接中安全获取 Odoo 环境的工具。"""

    def __init__(self, db_name: str, uid: int = SUPERUSER_ID, context: Optional[Dict[str, Any]] = None) -> None:
        self.db_name = db_name
        self.uid = uid
        self.context = context or {}

    @contextmanager
    def get_env(self):
        registry = odoo.registry(self.db_name)
        with registry.cursor() as cr:
            env = api.Environment(cr, self.uid, dict(self.context))
            yield env

    def with_user(self, uid: int) -> "SafeDatabaseManager":
        """创建一个使用指定用户 ID 的新实例"""
        return SafeDatabaseManager(self.db_name, uid, self.context)

    async def execute_with_env(self, operation, *args, **kwargs):
        """在独立的 Odoo 环境中执行一个同步 operation(operation 接收 env 作为第一个参数)。"""
        def runner():
            with self.get_env() as env:
                return operation(env, *args, **kwargs)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, runner)


class FastMCPService:
    """FastMCP 服务类：管理 FastMCP 服务器、工具与资源注册、以及数据库安全访问。"""

    _instance: Optional["FastMCPService"] = None

    @classmethod
    def get_instance(cls) -> "FastMCPService":
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self.mcp_servers: Dict[int, Any] = {}
        self.db_manager: Optional[SafeDatabaseManager] = None

        # 独立事件循环线程
        self.event_loop = asyncio.new_event_loop()

        def run_event_loop(loop: asyncio.AbstractEventLoop):
            asyncio.set_event_loop(loop)
            try:
                loop.run_forever()
            except Exception as e:
                _logger.error("事件循环运行异常: %s", str(e))
            finally:
                _logger.info("事件循环结束")
                try:
                    loop.close()
                except Exception:
                    pass

        self._event_loop_thread = threading.Thread(
            target=run_event_loop,
            args=(self.event_loop,),
            daemon=True,
            name="FastMCP-EventLoop",
        )
        self._event_loop_thread.start()

        # 等待事件循环启动
        time.sleep(0.5)
        _logger.info(
            "FastMCP事件循环已初始化并在后台运行，循环对象信息: %s, 运行状态: %s",
            self.event_loop,
            self.event_loop.is_running(),
        )


    def get_or_create_mcp_server(self, server_record):
        """获取或创建MCP服务器实例"""
        server_id = server_record.id
        _logger.info("尝试获取或创建MCP服务器实例，ID: %s, 名称: %s", server_id, server_record.name)

        if server_id in self.mcp_servers:
            _logger.info("找到现有的MCP服务器实例: %s", server_id)
            return self.mcp_servers.get(server_id)

        try:
            # 初始化数据库管理器（按需）
            if not self.db_manager:
                try:
                    db_name = server_record.env.cr.dbname
                except Exception:
                    db_name = odoo.tools.config.get("db_name")
                if not db_name:
                    raise RuntimeError("无法确定数据库名称用于初始化 SafeDatabaseManager")
                self.db_manager = SafeDatabaseManager(db_name=db_name)

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

    async def _safe_execute_with_env(self, operation, *args, uid: Optional[int] = None, **kwargs):
        """安全执行数据库操作的统一入口方法

        这个方法确保：
        1. 使用独立的数据库连接
        2. 自动资源清理和异常处理
        3. 事务管理和回滚机制
        4. 线程安全的操作

        Args:
            operation: 要执行的操作函数，第一个参数必须是env
            *args: 传递给操作函数的位置参数
            uid: 可选的用户 ID，如果指定则使用该用户身份执行
            **kwargs: 传递给操作函数的关键字参数

        Returns:
            操作函数的返回值
        """
        try:
            _logger.debug("开始安全数据库操作执行 (uid=%s)", uid or "SUPERUSER")
            if not self.db_manager:
                raise RuntimeError("SafeDatabaseManager 未初始化")

            # 如果指定了用户 ID，使用该用户的环境
            db_manager = self.db_manager.with_user(uid) if uid else self.db_manager
            result = await db_manager.execute_with_env(operation, *args, **kwargs)
            _logger.debug("安全数据库操作执行成功")
            return result
        except Exception as e:
            _logger.error("安全数据库操作执行失败: %s", str(e))
            # 重新抛出异常，让调用者处理
            raise

    def _query_odoo_model_impl(self, env, model_name, domain=None, fields=None, limit=100, offset=0, order=None):
        """查询Odoo模型的实现函数

        注意：不再使用 .sudo()，让 Odoo 的 ACL 和记录规则生效。
        如果需要管理员权限，应在调用时传入 SUPERUSER_ID。
        """
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取模型对象（不使用 sudo，让权限规则生效）
        model_obj = env[model_name]

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
        """获取Odoo记录的实现函数

        注意：不再使用 .sudo()，让 Odoo 的 ACL 和记录规则生效。
        """
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取记录（不使用 sudo，让权限规则生效）
        record = env[model_name].browse(record_id)
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
        """创建Odoo记录的实现函数

        注意：不再使用 .sudo()，让 Odoo 的 ACL 和记录规则生效。
        """
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 创建记录（不使用 sudo，让权限规则生效）
        model_obj = env[model_name]

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
        """更新Odoo记录的实现函数

        注意：不再使用 .sudo()，让 Odoo 的 ACL 和记录规则生效。
        """
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取记录（不使用 sudo，让权限规则生效）
        record = env[model_name].browse(record_id)
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
        """删除Odoo记录的实现函数

        注意：不再使用 .sudo()，让 Odoo 的 ACL 和记录规则生效。
        """
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取记录（不使用 sudo，让权限规则生效）
        record = env[model_name].browse(record_id)
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
        """获取Odoo模型元数据的实现函数

        注意：元数据查询使用 sudo() 获取完整字段信息，
        因为用户可能没有访问 ir.model 的权限。
        """
        # 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 获取模型对象（不使用 sudo，检查用户是否有访问权限）
        model_obj = env[model_name]

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

    def _execute_model_method_impl(self, env, model_name, method_name, record_ids, args=None, kwargs=None):
        """执行 Odoo 模型方法的实现函数

        支持调用任意模型上的业务方法，如 action_confirm、button_validate 等。
        权限由 Odoo ACL 和记录规则控制。

        Args:
            env: Odoo 环境
            model_name: 模型名称
            method_name: 方法名称
            record_ids: 记录 ID 列表
            args: 额外位置参数
            kwargs: 额外关键字参数

        Returns:
            执行结果字典
        """
        # 1. 验证模型是否存在
        if model_name not in env:
            raise ValueError(f"模型 '{model_name}' 不存在于Odoo中")

        # 2. 获取模型对象
        model_obj = env[model_name]

        # 3. 获取记录集
        if not record_ids:
            raise ValueError("record_ids 不能为空")

        records = model_obj.browse(record_ids)
        if not records.exists():
            missing_ids = set(record_ids) - set(records.ids)
            raise ValueError(f"记录不存在: {list(missing_ids)}")

        # 4. 记录执行前的状态（用于日志）
        _logger.info(
            "执行模型方法: model=%s, method=%s, record_ids=%s, args=%s, kwargs=%s",
            model_name, method_name, record_ids, args or [], kwargs or {}
        )

        # 5. 执行方法（使用 getattr，EAFP 风格）
        args = args or []
        kwargs = kwargs or {}

        try:
            method = getattr(records, method_name)
            result = method(*args, **kwargs)
        except AttributeError:
            raise ValueError(f"模型 '{model_name}' 没有方法 '{method_name}'")
        except Exception as e:
            _logger.error(
                "模型方法执行失败: model=%s, method=%s, record_ids=%s, error=%s",
                model_name, method_name, record_ids, str(e)
            )
            raise

        # 6. 处理返回值
        # Odoo 方法可能返回：
        # - None (void 方法)
        # - dict (如 action 返回值)
        # - recordset
        # - bool
        # - 其他类型

        result_data = {
            "model": model_name,
            "method": method_name,
            "record_ids": record_ids,
            "executed_on": len(records)
        }

        if result is None:
            result_data["result"] = None
            result_data["message"] = f"方法 '{method_name}' 执行成功"
        elif isinstance(result, dict):
            # 常见于 action 返回值
            result_data["result"] = result
            result_data["result_type"] = "action"
        elif hasattr(result, 'ids'):
            # recordset 返回值
            result_data["result"] = {
                "model": result._name,
                "ids": result.ids,
                "count": len(result)
            }
            result_data["result_type"] = "recordset"
        elif isinstance(result, bool):
            result_data["result"] = result
            result_data["result_type"] = "boolean"
        else:
            result_data["result"] = str(result)
            result_data["result_type"] = type(result).__name__

        return {
            "status": "success",
            "data": result_data
        }

    def _send_odoo_message_impl(self, env, body, channel_id=None, partner_ids=None, model=None, res_id=None, subject=None):
        """发送 Odoo 消息的实现函数"""
        import time
        
        message_values = {'body': body, 'message_type': 'comment'}
        if subject:
            message_values['subject'] = subject

        # 场景1：发送到频道/群聊
        if channel_id:
            if 'discuss.channel' not in env:
                raise ValueError("discuss.channel 模型不存在")
            channel = env['discuss.channel'].browse(channel_id)
            if not channel.exists():
                raise ValueError(f"频道不存在: {channel_id}")

            # 重试机制处理并发更新
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    env.clear()
                    message = channel.message_post(
                        body=body,
                        message_type='comment',
                        subtype_xmlid='mail.mt_note',
                        author_id=env.user.partner_id.id,
                    )
                    env.cr.commit()
                    return {
                        "status": "success",
                        "data": {
                            "message_id": message.id,
                            "channel_id": channel_id,
                            "channel_name": channel.name,
                            "message_type": "channel"
                        }
                    }
                except Exception as e:
                    last_error = e
                    if 'serialize' in str(e) and attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise

        # 场景2：在业务记录上留言
        if model and res_id:
            if model not in env:
                raise ValueError(f"模型 '{model}' 不存在")

            record = env[model].browse(res_id)
            if not record.exists():
                raise ValueError(f"记录不存在: {model}/#{res_id}")

            message = record.message_post(
                body=body,
                subject=subject,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
                author_id=env.user.partner_id.id,  # 使用调用者的身份
            )

            return {
                "status": "success",
                "data": {
                    "message_id": message.id,
                    "model": model,
                    "res_id": res_id,
                    "message_type": "record"
                }
            }

        # 场景3：发送给个人（通过 partner_ids）- 真正的私聊
        if partner_ids:
            # 使用 mail.message 直接发送消息
            target_partner_id = partner_ids[0]
            target_partner = env['res.partner'].browse(target_partner_id)

            if not target_partner.exists():
                raise ValueError(f"联系人不存在: {target_partner_id}")

            # 获取评论子类型
            subtype = env.ref('mail.mt_comment')

            # 创建消息记录
            message = env['mail.message'].create({
                'body': body,
                'message_type': 'comment',
                'subtype_id': subtype.id,
                'partner_ids': [(6, 0, partner_ids)],
                'model': 'res.partner',
                'res_id': target_partner_id,
                'author_id': env.user.partner_id.id,
            })

            # 通过 bus 发送实时通知
            try:
                for pid in partner_ids:
                    env['bus.bus']._sendone(
                        'res.partner/' + str(pid),
                        'mail.message/inbox',
                        message.message_format()[0] if hasattr(message, 'message_format') else {
                            'id': message.id,
                            'body': body,
                            'author_id': [env.user.partner_id.id, env.user.partner_id.name],
                        }
                    )
            except Exception:
                pass  # 实时通知失败不影响消息发送

            return {
                "status": "success",
                "data": {
                    "message_id": message.id,
                    "partner_ids": partner_ids,
                    "partner_name": target_partner.name,
                    "message_type": "private"
                }
            }

        raise ValueError("必须指定 channel_id、(model+res_id) 或 partner_ids 中至少一个参数")

    def _get_channel_messages_impl(self, env, channel_id, limit=50, before_id=None):
        """获取频道消息历史的实现函数

        只返回用户是成员的频道消息。

        Args:
            env: Odoo 环境
            channel_id: 频道 ID
            limit: 返回消息数量
            before_id: 获取此 ID 之前的消息

        Returns:
            消息列表字典
        """
        if 'discuss.channel' not in env:
            raise ValueError("discuss.channel 模型不存在，请安装 discuss 模块")

        channel = env['discuss.channel'].browse(channel_id)
        if not channel.exists():
            raise ValueError(f"频道不存在: {channel_id}")

        # 检查用户是否是频道成员
        current_partner = env.user.partner_id
        is_member = current_partner in channel.channel_member_ids.mapped('partner_id')

        if not is_member:
            raise ValueError(f"您不是频道 '{channel.name}' 的成员，无法访问消息")

        # 构建查询条件
        domain = [('model', '=', 'discuss.channel'), ('res_id', '=', channel_id)]
        if before_id:
            domain.append(('id', '<', before_id))

        # 查询消息，按 ID 降序（最新的在前）
        messages = env['mail.message'].search(
            domain,
            limit=limit,
            order='id DESC'
        )

        # 格式化消息
        result_messages = []
        for msg in messages:
            msg_data = {
                'id': msg.id,
                'author': {
                    'id': msg.author_id.id if msg.author_id else None,
                    'name': msg.author_id.name if msg.author_id else '系统'
                },
                'body': msg.body,
                'subject': msg.subject,
                'date': msg.date.isoformat() if msg.date else None,
                'message_type': msg.message_type,
            }
            result_messages.append(msg_data)

        return {
            "status": "success",
            "data": {
                "channel_id": channel_id,
                "channel_name": channel.name,
                "channel_type": channel.channel_type,
                "count": len(result_messages),
                "messages": result_messages
            }
        }

    def _get_partner_chat_impl(self, env, partner_id, limit=50, before_id=None):
        """获取与指定联系人私聊消息的实现函数

        只返回当前用户参与的私聊。

        Args:
            env: Odoo 环境
            partner_id: 联系人 ID
            limit: 返回消息数量
            before_id: 获取此 ID 之前的消息

        Returns:
            消息列表字典
        """
        if 'discuss.channel' not in env:
            raise ValueError("discuss.channel 模型不存在，请安装 discuss 模块")

        # 验证联系人存在
        partner = env['res.partner'].browse(partner_id)
        if not partner.exists():
            raise ValueError(f"联系人不存在: {partner_id}")

        # 获取当前用户
        current_partner = env.user.partner_id

        # 查找当前用户与该联系人的私聊频道
        # 必须同时包含当前用户和目标联系人才是有效的私聊
        channel = env['discuss.channel'].search([
            ('channel_type', '=', 'chat'),
            ('channel_member_ids.partner_id', '=', current_partner.id),
            ('channel_member_ids.partner_id', '=', partner_id),
        ], limit=1)

        # 验证频道确实包含两个成员
        if channel:
            member_ids = channel.channel_member_ids.mapped('partner_id').ids
            if current_partner.id not in member_ids or partner_id not in member_ids:
                channel = None

        if not channel:
            # 没有私聊记录，返回空结果
            return {
                "status": "success",
                "data": {
                    "partner_id": partner_id,
                    "partner_name": partner.name,
                    "channel_id": None,
                    "count": 0,
                    "messages": [],
                    "message": f"与 {partner.name} 暂无私聊记录"
                }
            }

        # 构建查询条件
        domain = [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id)]
        if before_id:
            domain.append(('id', '<', before_id))

        # 查询消息
        messages = env['mail.message'].search(
            domain,
            limit=limit,
            order='id DESC'
        )

        # 格式化消息
        result_messages = []
        for msg in messages:
            msg_data = {
                'id': msg.id,
                'author': {
                    'id': msg.author_id.id if msg.author_id else None,
                    'name': msg.author_id.name if msg.author_id else '系统'
                },
                'body': msg.body,
                'subject': msg.subject,
                'date': msg.date.isoformat() if msg.date else None,
                'message_type': msg.message_type,
            }
            result_messages.append(msg_data)

        return {
            "status": "success",
            "data": {
                "partner_id": partner_id,
                "partner_name": partner.name,
                "channel_id": channel.id,
                "channel_name": channel.name,
                "count": len(result_messages),
                "messages": result_messages
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

    def _authenticate_user_impl(self, env, username: str, password: str) -> Optional[int]:
        """验证用户凭据，返回用户 ID
        使用 Odoo 18 的密码验证机制
        """
        try:
            # 查找用户
            user = env['res.users'].sudo().search([('login', '=', username)], limit=1)
            if not user:
                _logger.warning("MCP 认证失败: 用户不存在 - %s", username)
                return None
            
            # 获取存储的密码哈希
            env.cr.execute("SELECT COALESCE(password, '') FROM res_users WHERE id=%s", [user.id])
            [hashed] = env.cr.fetchone()
            
            if not hashed:
                _logger.warning("MCP 认证失败: 用户没有设置密码 - %s", username)
                return None
            
            # 使用 Odoo 的 CryptContext 验证密码
            # Odoo 18 使用 pbkdf2_sha512
            ctx = env['res.users']._crypt_context()
            try:
                valid = ctx.verify(password, hashed)
            except Exception as verify_err:
                _logger.error("密码验证异常: %s", str(verify_err))
                valid = False
            
            if valid:
                _logger.info("MCP 认证成功: username=%s, user_id=%s", username, user.id)
                return user.id
            else:
                _logger.warning("MCP 认证失败: 密码错误 - %s", username)
                return None
        except Exception as e:
            _logger.error("MCP 认证异常: %s", str(e))
            return None
            
            # 获取存储的密码哈希
            env.cr.execute("SELECT COALESCE(password, '') FROM res_users WHERE id=%s", [user.id])
            [hashed] = env.cr.fetchone()
            
            if not hashed:
                _logger.warning("MCP 认证失败: 用户没有设置密码 - %s", username)
                return None
            
            # 使用 passlib 验证密码
            ctx = CryptContext(schemes=['pbkdf2_sha512', 'plaintext'])
            try:
                valid = ctx.verify(password, hashed)
            except Exception:
                valid = False
            
            if valid:
                _logger.info("MCP 认证成功: username=%s, user_id=%s", username, user.id)
                return user.id
            else:
                _logger.warning("MCP 认证失败: 密码错误 - %s", username)
                return None
        except Exception as e:
            _logger.error("MCP 认证异常: %s", str(e))
            return None
            
            # 获取存储的密码哈希
            env.cr.execute("SELECT COALESCE(password, '') FROM res_users WHERE id=%s", [user.id])
            [hashed] = env.cr.fetchone()
            
            if not hashed:
                _logger.warning("MCP 认证失败: 用户没有设置密码 - %s", username)
                return None
            
            # 使用 Odoo 的密码验证
            valid, replacement = env.cr._crypt_context.verify_and_update(password, hashed)
            
            if valid:
                _logger.info("MCP 认证成功: username=%s, user_id=%s", username, user.id)
                return user.id
            else:
                _logger.warning("MCP 认证失败: 密码错误 - %s", username)
                return None
        except Exception as e:
            _logger.error("MCP 认证异常: %s", str(e))
            return None
        except Exception as e:
            _logger.error("MCP 认证异常: %s", str(e))
            return None
    def _authorize_api_key_impl(self, env, api_key: Optional[str], server_id: int) -> bool:
        """授权检查实现：校验 api_key 是否匹配给定服务器

        要求：
        - api_key 必填且与目标 mcp.server 记录的 api_key 一致
        - 服务器必须 active=True
        """
        _logger.debug("🔐 开始授权检查: server_id=%s, token=%s", server_id,
                      f"***{api_key[-4:]}" if api_key and len(api_key) > 4 else "None")
        _logger.debug("🎫 认证令牌来源: %s", "serverAuthToken" if api_key else "无令牌")

        if not api_key:
            _logger.warning("授权失败: API Key 为空 (server_id=%s)", server_id)
            raise ValueError("Unauthorized")

        # 查找服务器记录
        srv = env['mcp.server'].sudo().browse(server_id)
        if not srv.exists():
            _logger.warning("授权失败: 服务器记录不存在 (server_id=%s)", server_id)
            raise ValueError("Unauthorized")

        if not srv.active:
            _logger.warning("授权失败: 服务器未激活 (server_id=%s, name='%s')", server_id, srv.name)
            raise ValueError("Unauthorized")

        # 记录服务器信息（用于调试）
        _logger.debug("找到服务器记录: id=%s, name='%s', active=%s", srv.id, srv.name, srv.active)

        # 精确匹配该服务器的 api_key
        expected_key = str(srv.api_key or '')
        provided_key = str(api_key)

        if provided_key != expected_key:
            _logger.warning("授权失败: API Key 不匹配 (server_id=%s, name='%s', provided=%s, expected=%s)",
                            server_id, srv.name,
                            f"***{provided_key[-4:]}" if len(provided_key) > 4 else provided_key,
                            f"***{expected_key[-4:]}" if len(expected_key) > 4 else "empty")
            raise ValueError("Unauthorized")

        _logger.info("授权成功: server_id=%s, name='%s'", server_id, srv.name)
        return True

    def _log_client_connection_info(self, ctx: Optional[Context]) -> None:
        """记录客户端连接信息，包括所有环境变量和上下文数据"""
        if not ctx:
            return

        try:
            _logger.info("=== 客户端连接信息开始 ===")
            _logger.info("Context类型: %s", type(ctx).__name__)
            _logger.info("Context对象: %s", ctx)

            # 详细检查 Context 对象的所有属性
            _logger.info("🔍 Context 对象完整属性检查:")
            all_attrs = dir(ctx)
            _logger.info("所有属性/方法: %s", [attr for attr in all_attrs if not attr.startswith('_')])

            # 记录所有可用的上下文属性
            available_attrs = []
            all_checked_attrs = ("metadata", "meta", "env", "environment", "params", "client_info", "headers")
            for attr in all_checked_attrs:
                if hasattr(ctx, attr):
                    attr_value = getattr(ctx, attr, None)
                    if attr_value is not None:
                        available_attrs.append(f"{attr}({type(attr_value).__name__})")
                        _logger.info("属性 %s 存在且非空: %s", attr, type(attr_value).__name__)
                    else:
                        _logger.info("属性 %s 存在但为空", attr)
                else:
                    _logger.info("属性 %s 不存在", attr)

            _logger.info("可用属性: %s", ", ".join(available_attrs) if available_attrs else "无")

            # 尝试直接访问 Context 的字典内容（如果它是字典类型的）
            if hasattr(ctx, '__dict__'):
                _logger.info("Context.__dict__: %s", ctx.__dict__)
            if hasattr(ctx, 'keys') and callable(getattr(ctx, 'keys')):
                try:
                    keys = ctx.keys()
                    _logger.info("Context.keys(): %s", list(keys))
                except Exception as e:
                    _logger.info("Context.keys() 调用失败: %s", e)
            if hasattr(ctx, 'items') and callable(getattr(ctx, 'items')):
                try:
                    items = ctx.items()
                    _logger.info("Context.items(): %s", list(items))
                except Exception as e:
                    _logger.info("Context.items() 调用失败: %s", e)

            # 详细记录环境变量
            for attr_name in ("env", "environment"):
                attr_value = getattr(ctx, attr_name, None)
                if isinstance(attr_value, dict) and attr_value:
                    _logger.info("--- %s 环境变量 ---", attr_name.upper())
                    for key, value in sorted(attr_value.items()):
                        # 敏感信息掩码处理
                        if any(sensitive in key.lower() for sensitive in
                               ['key', 'token', 'password', 'secret', 'auth']):
                            masked_value = f"***{str(value)[-4:]}" if value and len(str(value)) > 4 else "***"
                            _logger.info("  %s = %s [已掩码]", key, masked_value)
                        else:
                            _logger.info("  %s = %s", key, value)

            # 专门检查 serverAuthToken 的存在情况
            _logger.info("🔍 serverAuthToken 检查:")
            serverauth_found = False

            # 首先检查 HTTP Headers（主要方式）
            headers = getattr(ctx, "headers", None)
            if isinstance(headers, dict):
                # 检查 Authorization Bearer token
                auth_header = headers.get("Authorization") or headers.get("authorization")
                if auth_header and str(auth_header).startswith("Bearer "):
                    token = str(auth_header)[7:]
                    masked_token = f"***{token[-4:]}" if len(token) > 4 else "***"
                    _logger.info("  ✅ 在 HTTP Headers.Authorization 中找到 Bearer token: %s", masked_token)
                    serverauth_found = True

                # 检查自定义认证 headers
                for header_name, header_value in headers.items():
                    if any(token_hint in header_name.lower() for token_hint in ['token', 'auth', 'key']):
                        if header_name.lower() not in ['authorization']:
                            masked_token = f"***{str(header_value)[-4:]}" if len(str(header_value)) > 4 else "***"
                            _logger.info("  ✅ 在 HTTP Headers.%s 中找到自定义认证令牌: %s", header_name, masked_token)
                            serverauth_found = True

            # 其次检查上下文属性
            for attr_name in ("metadata", "meta", "params", "client_info"):
                attr_value = getattr(ctx, attr_name, None)
                if isinstance(attr_value, dict) and "serverAuthToken" in attr_value:
                    token_value = attr_value["serverAuthToken"]
                    masked_token = f"***{str(token_value)[-4:]}" if token_value and len(str(token_value)) > 4 else "***"
                    _logger.info("  ✅ 在 %s 中找到 serverAuthToken: %s", attr_name, masked_token)
                    serverauth_found = True

            if not serverauth_found:
                _logger.warning("  ❌ 未在 HTTP Headers 或上下文属性中找到 serverAuthToken")

            # 记录其他上下文信息
            for attr_name in ("metadata", "meta", "params", "client_info", "headers"):
                attr_value = getattr(ctx, attr_name, None)
                if isinstance(attr_value, dict) and attr_value:
                    _logger.info("--- %s ---", attr_name.upper())
                    for key, value in sorted(attr_value.items()):
                        # 特别标记 Authorization header (Bearer token)
                        if key.lower() == "authorization" and str(value).startswith("Bearer "):
                            token = str(value)[7:]  # 移除 "Bearer " 前缀
                            masked_value = f"Bearer ***{token[-4:]}" if len(token) > 4 else "Bearer ***"
                            _logger.info("  🔐 %s = %s [HTTP Bearer Token]", key, masked_value)
                        # 特别标记 serverAuthToken
                        elif key == "serverAuthToken":
                            masked_value = f"***{str(value)[-4:]}" if value and len(str(value)) > 4 else "***"
                            _logger.info("  🔑 %s = %s [MCP标准认证]", key, masked_value)
                        # 其他认证相关 headers
                        elif attr_name == "headers" and any(
                                token_hint in key.lower() for token_hint in ['token', 'auth', 'key']):
                            masked_value = f"***{str(value)[-4:]}" if value and len(str(value)) > 4 else "***"
                            _logger.info("  🎫 %s = %s [自定义认证Header]", key, masked_value)
                        # 其他敏感信息掩码处理
                        elif any(sensitive in key.lower() for sensitive in
                                 ['key', 'token', 'password', 'secret', 'auth']):
                            masked_value = f"***{str(value)[-4:]}" if value and len(str(value)) > 4 else "***"
                            _logger.info("  %s = %s [已掩码]", key, masked_value)
                        else:
                            _logger.info("  %s = %s", key, value)

            _logger.info("=== 客户端连接信息结束 ===")

        except Exception as e:
            _logger.debug("记录客户端连接信息时出错: %s", str(e))

    def _extract_api_key_from_ctx(self, ctx: Optional[Context]) -> Optional[str]:
        """仅从 HTTP 请求头中提取 api_key。

        安全准则：不从服务器自身进程环境变量读取，避免"未提供 api_key 也能通过"的风险。

        使用 FastMCP 的 get_http_headers() 函数获取 HTTP 请求头。
        """
        _logger.info("🚀 开始从 HTTP 请求头提取 API Key")

        # 方法1：使用 FastMCP 的 get_http_headers() 获取请求头
        try:
            from fastmcp.server.dependencies import get_http_headers
            headers = get_http_headers(include_all=True)
            _logger.info("✅ 获取到 HTTP Headers: %s", list(headers.keys()))

            # 检查 Authorization Bearer token
            auth_header = headers.get("authorization") or headers.get("Authorization")
            if auth_header and str(auth_header).startswith("Bearer "):
                token = str(auth_header)[7:]
                _logger.info("✅ 从 Authorization Bearer header 提取到 API Key: %s", f"***{token[-4:]}")
                return token

            # 检查自定义认证 header (serverAuthToken)
            server_auth = headers.get("serverauthtoken") or headers.get("serverAuthToken")
            if server_auth:
                _logger.info("✅ 从 serverAuthToken header 提取到 API Key: %s", f"***{server_auth[-4:]}")
                return str(server_auth)

            # 检查其他可能的认证 header
            for header_name, header_value in headers.items():
                if any(token_hint in header_name.lower() for token_hint in ['token', 'auth', 'key']):
                    if header_name.lower() not in ['authorization']:
                        _logger.info("✅ 从自定义 header '%s' 提取到 API Key", header_name)
                        return str(header_value)

        except Exception as e:
            _logger.debug("获取 HTTP Headers 失败: %s", str(e))

        _logger.warning("⚠️  未在 HTTP Headers 中找到 API Key")
        return None

    async def _ensure_authorized_ctx(self, ctx: Optional[Context], server_id: int, username: str, password: str) -> tuple[bool, Optional[int]]:
        """
        统一授权入口

        Args:
            ctx: FastMCP Context
            server_id: MCP 服务器 ID
            username: Odoo 用户名（必填）
            password: Odoo 密码（必填）

        Returns:
            (is_authorized, user_id)
            - (True, 5): 用户认证成功，用户 ID=5
            - (True, 1): 管理员模式（未提供用户凭据，使用 API Key）
            - (False, None): 认证失败
        """
        _logger.debug("🚀 开始统一授权检查: server_id=%s, username=%s", server_id, username or "None")

        try:
            # 1. 如果提供了用户凭据，验证用户
            if username and password:
                _logger.debug("🔐 使用用户名/密码认证")
                user_id = await self._safe_execute_with_env(
                    self._authenticate_user_impl, username, password
                )
                if user_id:
                    _logger.info("🎉 用户认证成功: server_id=%s, username=%s, user_id=%s", server_id, username, user_id)
                    return (True, user_id)
                else:
                    _logger.warning("💥 用户认证失败: username=%s", username)
                    return (False, None)

            # 2. 未提供用户凭据，验证服务器 API Key（管理员模式）
            _logger.debug("🔐 使用 API Key 认证（管理员模式）")
            key = self._extract_api_key_from_ctx(ctx)
            if key:
                _logger.debug("✅ 成功提取到认证令牌: %s", f"***{key[-4:]}" if len(key) > 4 else "***")
            else:
                _logger.warning("❌ 未能提取到有效的 serverAuthToken")

            ok = await self._safe_execute_with_env(self._authorize_api_key_impl, key, server_id)
            if ok:
                _logger.info("🎉 API Key 授权成功: server_id=%s (管理员模式)", server_id)
                return (True, SUPERUSER_ID)
            else:
                _logger.error("💥 API Key 授权失败: server_id=%s", server_id)
                return (False, None)
        except Exception as e:
            _logger.error("授权检查异常: %s", str(e))
            _logger.debug("授权检查异常详情: %s", traceback.format_exc())

            if ctx:
                try:
                    await ctx.error("Unauthorized")
                except Exception as ctx_err:
                    _logger.debug("发送错误消息到上下文失败: %s", str(ctx_err))

            return (False, None)

    async def _graphql_impl(self, server_id: int, query: str, variables: Optional[Dict[str, Any]], ctx: Optional[Context], username: str, password: str) -> Dict[str, Any]:
        """GraphQL 执行实现，供工具委托调用"""
        try:
            is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_id, username, password)
            if not is_authorized:
                return {"errors": ["Unauthorized"], "code": 401}
            from .graphql_schema import build_schema
            schema = build_schema()

            def sync_op(env):
                return schema.execute(
                    query,
                    variable_values=(variables or {}),
                    context_value={"env": env},
                )

            result = await self._safe_execute_with_env(lambda env: sync_op(env), uid=user_id)
            payload: Dict[str, Any] = {}
            if getattr(result, "errors", None):
                payload["errors"] = [str(e) for e in result.errors]
            if getattr(result, "data", None) is not None:
                payload["data"] = result.data

            if ctx:
                if payload.get("errors"):
                    await ctx.error(f"GraphQL 执行出现 {len(payload['errors'])} 个错误")
                else:
                    await ctx.info("GraphQL 查询执行成功")
            return payload
        except AccessError as e:
            error_msg = f"权限不足: {str(e)}"
            if ctx:
                await ctx.error(error_msg)
            _logger.warning("权限错误: %s", str(e))
            return {"errors": [error_msg], "code": 403}
        except Exception as e:
            _logger.error("GraphQL 执行失败: %s", str(e))
            if ctx:
                try:
                    await ctx.error(f"GraphQL 执行失败: {str(e)}")
                except Exception:
                    pass
            return {"errors": [str(e)]}

    def _register_default_tools(self, mcp_server, server_record):
        """注册默认工具到FastMCP服务器"""

        # ===== Odoo数据访问工具 =====
        @mcp_server.tool()
        async def query_odoo_model(username: str,
            password: str,
            
            model_name: str,
            domain: Optional[str] = None,
            fields: Optional[str] = None,
            limit: int = 100,
            offset: int = 0,
            order: Optional[str] = None,
            ctx: Context = None,
        ) -> Dict[str, Any]:
            """查询任意Odoo模型的数据

            Args:
                model_name: Odoo模型名称 (例如 'res.partner', 'product.template')
                domain: 搜索域JSON字符串 (例如 '[["is_company", "=", true]]')
                fields: 要获取的字段JSON字符串 (例如 '["name", "email", "phone"]')
                limit: 最大返回记录数
                offset: 记录偏移量
                order: 排序字段和方向 (例如 'name ASC')
                username: Odoo 用户名（可选，不提供则使用管理员权限）
                password: Odoo 密码（可选，与 username 配合使用）

            Returns:
                包含查询结果的字典
            """
            try:
                # 授权校验
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                if ctx:
                    await ctx.info(f"开始查询模型 '{model_name}' (user_id={user_id})")

                # 使用安全执行方法（指定用户 ID）
                result = await self._safe_execute_with_env(
                    self._query_odoo_model_impl,
                    model_name, domain, fields, limit, offset, order,
                    uid=user_id
                )

                if ctx:
                    data = result.get('data', {})
                    count = data.get('count', 0)
                    total_count = data.get('total_count', 0)
                    await ctx.info(f"从 '{model_name}' 查询到 {count} 条记录 (共 {total_count} 条)")

                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"查询Odoo模型失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def get_odoo_record(username: str,
            password: str,
            
            model_name: str,
            record_id: int,
             ctx: Context = None
        ) -> Dict[str, Any]:
            """获取Odoo中指定记录的详细信息

            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                record_id: 记录ID
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含记录详细信息的字典
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._get_odoo_record_impl,
                    model_name, record_id,
                    uid=user_id
                )
                if ctx:
                    await ctx.info(f"成功获取模型 '{model_name}' 中ID为 {record_id} 的记录")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"获取Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def create_odoo_record(username: str,
            password: str,
            
            model_name: str,
            values: Dict[str, Any],
             ctx: Context = None
        ) -> Dict[str, Any]:
            """在Odoo中创建新记录

            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                values: 要创建的记录的字段值
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含新创建记录信息的字典
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._create_odoo_record_impl,
                    model_name, values,
                    uid=user_id
                )
                if ctx:
                    data = result.get('data', {})
                    record_id = data.get('id', 'unknown')
                    await ctx.info(f"在模型 '{model_name}' 中成功创建了新记录，ID: {record_id}")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"创建Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def update_odoo_record(username: str,
            password: str,
            
            model_name: str,
            record_id: int,
            values: Dict[str, Any],
             ctx: Context = None
        ) -> Dict[str, Any]:
            """更新Odoo中的记录

            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                record_id: 要更新的记录ID
                values: 要更新的字段值
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含更新后记录信息的字典
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._update_odoo_record_impl,
                    model_name, record_id, values,
                    uid=user_id
                )
                if ctx:
                    await ctx.info(f"成功更新了模型 '{model_name}' 中ID为 {record_id} 的记录")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"更新Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def delete_odoo_record(username: str,
            password: str,
            
            model_name: str,
            record_id: int,
             ctx: Context = None
        ) -> Dict[str, Any]:
            """删除Odoo中的记录

            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                record_id: 要删除的记录ID
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                删除操作的结果
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._delete_odoo_record_impl,
                    model_name, record_id,
                    uid=user_id
                )
                if ctx:
                    data = result.get('data', {})
                    record_name = data.get('record_name', f'ID: {record_id}')
                    await ctx.info(f"成功删除了模型 '{model_name}' 中的记录: {record_name}")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"删除Odoo记录失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def get_odoo_model_metadata(username: str,
            password: str,
            
            model_name: str,
             ctx: Context = None
        ) -> Dict[str, Any]:
            """获取Odoo模型的元数据信息，包括字段定义等

            Args:
                model_name: Odoo模型名称 (例如 'res.partner')
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含模型元数据信息的字典
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._get_odoo_model_metadata_impl,
                    model_name,
                    uid=user_id
                )
                if ctx:
                    await ctx.info(f"成功获取模型 '{model_name}' 的元数据信息")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"获取Odoo模型元数据失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        # ===== MCP资源管理工具 =====
        @mcp_server.tool()
        async def list_resources(
            username: str, password: str, ctx: Context = None
        ) -> Dict[str, Any]:
            """列出当前MCP服务器上的所有可用资源

            Args:
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._list_resources_impl,
                    server_record.id,
                    uid=user_id
                )
                if ctx:
                    data = result.get('data', [])
                    await ctx.info(f"获取到 {len(data)} 个资源")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                if ctx:
                    await ctx.error(f"获取资源列表失败: {str(e)}")
                _logger.error("FastMCP工具list_resources失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        @mcp_server.tool()
        async def get_resource_content(
            resource_uri: str,
            username: str, password: str, ctx: Context = None
        ) -> Dict[str, Any]:
            """获取指定URI的资源内容

            Args:
                resource_uri: 资源URI
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                result = await self._safe_execute_with_env(
                    self._get_resource_content_impl,
                    server_record.id,
                    resource_uri,
                    uid=user_id
                )
                if ctx:
                    data = result.get('data', {})
                    resource_name = data.get('name', resource_uri)
                    await ctx.info(f"成功获取资源: {resource_name}")
                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                if ctx:
                    await ctx.error(f"获取资源内容失败: {str(e)}")
                _logger.error("FastMCP工具get_resource_content失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        # ===== 模型方法调用工具 =====
        @mcp_server.tool()
        async def execute_model_method(username: str,
            password: str,
            
            model_name: str,
            method_name: str,
            record_ids: list,
            args: Optional[list] = None,
            kwargs: Optional[Dict[str, Any]] = None,
            ctx: Context = None,
        ) -> Dict[str, Any]:
            """执行 Odoo 模型的业务方法

            Args:
                model_name: Odoo 模型名称 (例如 'sale.order', 'stock.picking')
                method_name: 要调用的方法名称 (例如 'action_confirm', 'button_validate')
                record_ids: 要操作的记录 ID 列表
                args: 传递给方法的额外位置参数（可选）
                kwargs: 传递给方法的额外关键字参数（可选）
                username: Odoo 用户名（可选，不提供则使用管理员权限）
                password: Odoo 密码（可选，与 username 配合使用）

            Returns:
                包含方法执行结果的字典

            Examples:
                # 确认销售订单
                execute_model_method('sale.order', 'action_confirm', [1, 2])

                # 验证库存移动
                execute_model_method('stock.picking', 'button_validate', [5])

                # 带参数的方法调用
                execute_model_method('account.move', 'action_post', [10])
            """
            try:
                # 授权校验
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}
                if ctx:
                    await ctx.info(f"开始执行方法 '{model_name}.{method_name}' (user_id={user_id})")

                # 使用安全执行方法
                result = await self._safe_execute_with_env(
                    self._execute_model_method_impl,
                    model_name, method_name, record_ids, args, kwargs,
                    uid=user_id
                )

                if ctx:
                    await ctx.info(f"成功执行方法 '{model_name}.{method_name}'")

                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("权限错误: %s", str(e))
                return {"status": "error", "code": 403, "message": error_msg}
            except UserError as e:
                error_msg = f"业务错误: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.warning("业务错误: %s", str(e))
                return {"status": "error", "code": 400, "message": error_msg}
            except Exception as e:
                error_msg = f"执行模型方法失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        # ===== 消息发送工具 =====
        @mcp_server.tool()
        async def send_odoo_message(username: str,
            password: str,
            
            body: str,
            channel_id: Optional[int] = None,
            partner_ids: Optional[list] = None,
            model: Optional[str] = None,
            res_id: Optional[int] = None,
            subject: Optional[str] = None,
            ctx: Context = None,
        ) -> Dict[str, Any]:
            """发送 Odoo 消息/通知

            Args:
                body: 消息内容（支持 HTML 格式）
                channel_id: 频道/群组 ID（可选，发送到群聊）
                partner_ids: 收件人 ID 列表（可选，发送给个人）
                model: 关联模型名称（可选，在业务记录上留言）
                res_id: 关联记录 ID（可选，与 model 配合使用）
                subject: 消息主题（可选）
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含发送结果的字典

            Examples:
                # 发送到群聊
                send_odoo_message(body="通知内容", channel_id=1)

                # 发送给个人
                send_odoo_message(body="消息内容", partner_ids=[13, 46])

                # 在销售订单上留言
                send_odoo_message(body="备注内容", model="sale.order", res_id=1)
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}

                if ctx:
                    target = f"频道 {channel_id}" if channel_id else f"用户 {partner_ids}" if partner_ids else "系统消息"
                    await ctx.info(f"开始发送消息到 {target}")

                result = await self._safe_execute_with_env(
                    self._send_odoo_message_impl,
                    body, channel_id, partner_ids, model, res_id, subject,
                    uid=user_id
                )

                if ctx:
                    await ctx.info("消息发送成功")

                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"发送消息失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        # ===== 消息历史工具 =====
        @mcp_server.tool()
        async def get_channel_messages(
            username: str,
            password: str,
            channel_id: int,
            limit: int = 50,
            before_id: Optional[int] = None,
            ctx: Context = None,
        ) -> Dict[str, Any]:
            """获取 Odoo 频道/群聊/私聊的消息历史

            Args:
                channel_id: 频道 ID（可以是群聊频道或私聊频道）
                limit: 返回消息数量（默认 50）
                before_id: 获取此 ID 之前的消息（可选，用于分页）
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含消息列表的字典

            Examples:
                # 获取频道最近 50 条消息
                get_channel_messages(channel_id=1)

                # 获取私聊消息（团团频道 ID: 16）
                get_channel_messages(channel_id=16)

                # 分页获取
                get_channel_messages(channel_id=1, limit=20, before_id=1000)
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}

                if ctx:
                    await ctx.info(f"开始获取频道 {channel_id} 的消息历史")

                result = await self._safe_execute_with_env(
                    self._get_channel_messages_impl,
                    channel_id, limit, before_id,
                    uid=user_id
                )

                if ctx:
                    count = result.get("data", {}).get("count", 0)
                    await ctx.info(f"获取到 {count} 条消息")

                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"获取消息历史失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        @mcp_server.tool()
        async def get_partner_chat(
            username: str,
            password: str,
            partner_id: int,
            limit: int = 50,
            before_id: Optional[int] = None,
            ctx: Context = None,
        ) -> Dict[str, Any]:
            """获取与指定联系人的私聊消息历史

            Args:
                partner_id: 联系人 ID（如团团=14，冯总=13）
                limit: 返回消息数量（默认 50）
                before_id: 获取此 ID 之前的消息（可选，用于分页）
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）

            Returns:
                包含消息列表的字典

            Examples:
                # 获取与团团（partner_id=14）的私聊
                get_partner_chat(partner_id=14)

                # 获取与冯总（partner_id=13）的私聊
                get_partner_chat(partner_id=13)

                # 分页获取
                get_partner_chat(partner_id=14, limit=20, before_id=5000)
            """
            try:
                is_authorized, user_id = await self._ensure_authorized_ctx(ctx, server_record.id, username, password)
                if not is_authorized:
                    return {"status": "error", "code": 401, "message": "Unauthorized"}

                if ctx:
                    await ctx.info(f"开始获取与联系人 {partner_id} 的私聊消息")

                result = await self._safe_execute_with_env(
                    self._get_partner_chat_impl,
                    partner_id, limit, before_id,
                    uid=user_id
                )

                if ctx:
                    count = result.get("data", {}).get("count", 0)
                    channel_name = result.get("data", {}).get("partner_name", "未知")
                    await ctx.info(f"获取到与 {channel_name} 的 {count} 条消息")

                return result
            except AccessError as e:
                error_msg = f"权限不足: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                return {"status": "error", "code": 403, "message": error_msg}
            except Exception as e:
                error_msg = f"获取私聊消息失败: {str(e)}"
                if ctx:
                    await ctx.error(error_msg)
                _logger.error(error_msg)
                return {"status": "error", "message": error_msg}

        # ===== GraphQL 工具 =====
        @mcp_server.tool()
        async def graphql(
            username: str,
            password: str,
            query: str,
            variables: Optional[Dict[str, Any]] = None,
            ctx: Context = None
        ) -> Dict[str, Any]:
            """执行 GraphQL 查询
            
            Args:
                query: GraphQL 查询字符串
                variables: 查询变量
                username: Odoo 用户名（必填）
                password: Odoo 密码（必填）
            """
            return await self._graphql_impl(server_record.id, query, variables, ctx, username, password)

    def _register_default_resources(self, mcp_server, server_record):
        """注册默认资源到FastMCP服务器"""

        @mcp_server.resource("server://info")
        def get_server_info():
            """获取服务器基本信息"""
            try:
                if not self.db_manager:
                    raise RuntimeError("SafeDatabaseManager 未初始化")
                with self.db_manager.get_env() as env:
                    return self._get_server_info_impl(env, server_record.id)
            except Exception as e:
                _logger.error("获取服务器信息失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        @mcp_server.resource("resources://list")
        def get_resources_list():
            """获取所有资源列表"""
            try:
                if not self.db_manager:
                    raise RuntimeError("SafeDatabaseManager 未初始化")
                with self.db_manager.get_env() as env:
                    return self._list_resources_impl(env, server_record.id)
            except Exception as e:
                _logger.error("获取资源列表失败: %s", str(e))
                return {"status": "error", "message": str(e)}

        @mcp_server.resource("resource://{resource_id}")
        def get_resource(resource_id: int):
            """获取指定ID的资源"""
            try:
                if not self.db_manager:
                    raise RuntimeError("SafeDatabaseManager 未初始化")
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

        # 若已在监听且当前进程已注册该实例，则不重复启动
        try:
            pre_health = self.health_check(server_record)
            data = pre_health.get('data', {}) if isinstance(pre_health, dict) else {}
            listening = bool(data.get('listening', False))
            registered = bool(data.get('registered', False))
            if pre_health.get('status') == 'success' and listening and registered:
                _logger.info("检测到服务器已在运行且已注册，跳过重复启动: %s:%s", data.get('host'), data.get('port'))
                server_record.sudo().write({
                    'state': 'active',
                    'last_connection': fields.Datetime.now()
                })
                return True
            elif listening and not registered:
                _logger.warning(
                    "检测到端口 %s 正在监听，但当前进程未注册服务器 '%s'，可能由其他进程占用，跳过启动以避免冲突",
                    data.get('port'), server_record.name)
                # 不改变状态，交由管理员处理端口冲突
                return False
        except Exception as _e:
            _logger.debug("启动前健康检查异常，忽略继续启动: %s", _e)

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
                result = future.result(timeout=5.0)
                _logger.info("服务器启动任务结果: %s", result)
            except asyncio.TimeoutError:
                _logger.info("启动协程未在超时时间内完成，进行健康回退检测")
                result = {'success': False, 'error': 'timeout'}
            except asyncio.CancelledError as ce:  # type: ignore
                _logger.warning("启动协程被取消: %s，执行健康回退检测", ce)
                result = {'success': False, 'error': 'cancelled'}
            except Exception as inner_e:
                _logger.warning("获取服务器启动状态时出现警告: %s，执行健康回退检测", inner_e)
                result = {'success': False, 'error': str(inner_e) or 'unknown'}

            # 统一健康回退：
            # 即使协程报告失败/超时，也以实时健康检查（端口监听）为准，避免"实际已启动但 future 超时"导致的误报。
            health = self.health_check(server_record)
            data_h = health.get('data', {}) if isinstance(health, dict) else {}
            ready = (
                    isinstance(health, dict)
                    and health.get('status') == 'success'
                    and bool(data_h.get('listening'))
            )
            server_record.sudo().write({
                'state': 'active' if ready else 'inactive',
                'last_connection': fields.Datetime.now()
            })
            if ready:
                if not result.get('success'):
                    _logger.info("协程结果非 success 但健康检查通过，视为启动成功 (fallback path)")
                return True
            else:
                _logger.error("FastMCP 启动失败：result=%s health=%s", result, health)
                return False
        except Exception as e:
            _logger.error("启动FastMCP服务器失败: %s", str(e))
            import traceback
            _logger.error("异常详情: %s", traceback.format_exc())
            return False

    async def _start_server_async(self, mcp_server, server_record):
        """异步启动MCP服务器（精简阻塞：端口监听后立即返回）。

        设计要点：
        - 仅负责触发底层线程 + 轮询端口监听；不等待完整"协议预热"流程。
        - 端口监听成功即返回 {'success': True}；后续预热在后台协程中异步执行。
        - 防止长时间 sleep 触发上层 future.result 超时，导致误判失败。
        """
        try:
            # 在异步函数开始时保存必要的信息，而不使用server_record对象
            server_id = server_record.id
            server_name = server_record.name

            _logger.info("开始异步启动MCP服务器: %s", server_name)
            # 使用模型配置的端口
            host = "0.0.0.0"  # 监听所有网络接口
            port = int(server_record.port or 10888)

            _logger.info("服务器配置 - 主机: %s, 端口: %s, 首选传输: %s (将自动回退不支持的传输)", host, port,
                         "streamable-http")

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
            from multiprocessing import Event
            server_started = Event()
            server_error = [None]

            # 创建启动FastMCP的函数
            def start_fastmcp_server():
                try:
                    _logger.info("在新线程中启动FastMCP服务器")

                    # 使用正确的方式启动FastMCP服务器
                    # 改用 streamable-http 传输模式
                    _logger.info("开始启动FastMCP服务器，transport=streamable-http, host=%s, port=%s", host, port)

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
                    try:
                        # 优先尝试支持 host/port 的签名
                        mcp_server.run(
                            transport="streamable-http",
                            host=host,
                            port=port
                        )
                    except TypeError:
                        # 某些版本的 FastMCP.run 不接受 host/port 关键字参数
                        # 回退方案：通过环境变量传递绑定信息
                        os.environ['FASTMCP_HOST'] = str(host)
                        os.environ['FASTMCP_PORT'] = str(port)
                        # 也兼容常见的 BIND 变量
                        os.environ['FASTMCP_BIND'] = f"{host}:{port}"
                        _logger.info("FastMCP.run 不支持 host/port 参数，已改用环境变量传递绑定: %s:%s", host, port)
                        mcp_server.run(
                            transport="streamable-http"
                        )
                    except ValueError as ve:
                        # 老版本 fastmcp 可能不支持 streamable-http 传输，降级为 sse
                        if "Unknown transport" in str(ve):
                            _logger.warning("streamable-http 不受当前 FastMCP 版本支持，降级使用 sse 传输模式")
                            try:
                                mcp_server.run(
                                    transport="sse",
                                    host=host,
                                    port=port
                                )
                            except TypeError:
                                os.environ['FASTMCP_HOST'] = str(host)
                                os.environ['FASTMCP_PORT'] = str(port)
                                os.environ['FASTMCP_BIND'] = f"{host}:{port}"
                                _logger.info("降级 sse 同样不支持 host/port 参数，改用环境变量绑定: %s:%s", host, port)
                                mcp_server.run(
                                    transport="sse"
                                )
                        else:
                            raise

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

            # 轮询端口（最短 0.5s，最长 ~5s）：一旦监听成功立即返回，不等待协议预热
            startup_successful = False
            for attempt in range(10):  # 10 * 0.5s = 5s
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    res = sock.connect_ex((host, port))
                    sock.close()
                    if res == 0:
                        _logger.info("FastMCP服务器已成功绑定端口 (attempt %d)", attempt + 1)
                        startup_successful = True
                        break
                except Exception as ce:
                    _logger.debug("端口检查异常: %s", ce)
                await asyncio.sleep(0.5)

            if server_error[0]:
                _logger.error("启动FastMCP服务器出错: %s", server_error[0])
                return {'success': False, 'error': server_error[0]}

            if not startup_successful:
                _logger.warning("端口在预期时间内未确认监听，返回失败")
                return {'success': False, 'error': 'port-not-listening'}

            # 异步启动预热任务（不阻塞返回）
            async def _warmup():
                try:
                    _logger.info("[Warmup] 开始协议与资源预热 ...")
                    # 轻量再探测几次，给外部日志提示
                    for i in range(3):
                        await asyncio.sleep(1.0)
                        _logger.debug("[Warmup] tick %d", i + 1)
                    _logger.info("[Warmup] 完成")
                except Exception as we:
                    _logger.debug("[Warmup] 异常: %s", we)

            try:
                self.event_loop.call_soon_threadsafe(
                    lambda: asyncio.run_coroutine_threadsafe(_warmup(), self.event_loop))
            except Exception:
                pass

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

    # ----------------------
    # 健康检查
    # ----------------------
    def health_check(self, server_record) -> Dict[str, Any]:
        """检查指定服务器的健康状态。

        返回示例：
        {
            'status': 'success',
            'data': {
                'server_id': 1,
                'name': 'Demo',
                'host': '127.0.0.1',
                'port': 10888,
                'listening': true,
                'registered': true
            }
        }
        """
        try:
            host = '127.0.0.1'
            port = int(server_record.port or 10888)

            listening = False
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                listening = (sock.connect_ex((host, port)) == 0)
            finally:
                try:
                    if sock:
                        sock.close()
                except Exception:
                    pass

            return {
                'status': 'success',
                'data': {
                    'server_id': server_record.id,
                    'name': server_record.name,
                    'host': host,
                    'port': port,
                    'listening': listening,
                    'registered': server_record.id in self.mcp_servers,
                }
            }
        except Exception as e:
            _logger.error("健康检查失败: %s", str(e))
            return {'status': 'error', 'message': str(e)}
