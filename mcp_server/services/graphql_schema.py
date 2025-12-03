import graphene
from graphene.types.json import JSONString


# ---- helper functions (module-level) ----
def _parse_domain(domain):
    if domain is None:
        return []
    if isinstance(domain, list):
        return domain
    if isinstance(domain, str) and domain.strip():
        import json
        try:
            return json.loads(domain)
        except Exception:
            return []
    return []


def _prep_values(model, values, env):
    # 允许传入 JSON 字符串或对象；并将 {field: {id, name}} 简化为 id
    if isinstance(values, str):
        import json
        try:
            values = json.loads(values)
        except Exception:
            values = {}
    if not isinstance(values, dict):
        values = {}
    model_obj = env[model].sudo()
    out = {}
    for k, v in values.items():
        if isinstance(v, dict) and 'id' in v:
            out[k] = v['id']
        else:
            out[k] = v
    return out


def _process_nested_fields(record_data, model_obj, nested_fields=None, max_depth=3, current_depth=0):
    """
    处理嵌套字段，支持 one2many, many2many 和深度嵌套
    
    Args:
        record_data: 记录数据字典
        model_obj: Odoo 模型对象
        nested_fields: 要嵌套加载的字段列表 ['field1', 'field2.subfield']
        max_depth: 最大嵌套深度
        current_depth: 当前深度
    """
    if current_depth >= max_depth:
        return record_data

    processed_data = record_data.copy()

    for field_name, field_value in record_data.items():
        if field_name not in model_obj._fields:
            continue

        field = model_obj._fields[field_name]

        # 处理 many2one 字段 (已有逻辑增强)
        if field.type == 'many2one' and isinstance(field_value, tuple) and len(field_value) == 2:
            processed_data[field_name] = {
                "id": field_value[0],
                "name": field_value[1]
            }

        # 处理 one2many 和 many2many 字段
        elif field.type in ('one2many', 'many2many') and field_value:
            if isinstance(field_value, list) and field_value:
                try:
                    related_model = model_obj.env[field.comodel_name].sudo()
                    related_records = related_model.browse(field_value)

                    nested_data = []
                    for rec in related_records:
                        if rec.exists():
                            # 获取基础字段（排除大字段）
                            exclude_types = ['binary', 'html', 'text']
                            basic_fields = [f for f, fld in rec._fields.items()
                                            if fld.type not in exclude_types][:10]  # 限制字段数量

                            rec_data = rec.read(basic_fields)[0]

                            # 递归处理嵌套（限制深度避免无限循环）
                            if current_depth < max_depth - 1:
                                rec_data = _process_nested_fields(
                                    rec_data, rec, nested_fields, max_depth, current_depth + 1
                                )

                            nested_data.append(rec_data)

                    processed_data[field_name] = nested_data
                except Exception as e:
                    # 如果嵌套加载失败，保持原值
                    processed_data[field_name] = field_value

    return processed_data


class MCPResourceType(graphene.ObjectType):
    id = graphene.Int()
    name = graphene.String()
    resource_uri = graphene.String()
    resource_type = graphene.String()
    description = graphene.String()
    last_fetch = graphene.DateTime()
    server_id = graphene.Int()
    server_name = graphene.String()


class MCPServerType(graphene.ObjectType):
    id = graphene.Int()
    name = graphene.String()
    port = graphene.Int()
    state = graphene.String()
    last_connection = graphene.DateTime()
    connection_count = graphene.Int()
    resource_count = graphene.Int()

    resources = graphene.List(MCPResourceType, active=graphene.Boolean(default_value=True))

    def resolve_resources(self, info, active=True):
        env = info.context.get('env')
        if env is None:
            return []
        domain = [('server_id', '=', self['id'])]
        if active is not None:
            domain.append(('active', '=', bool(active)))
        records = env['mcp.resource'].sudo().search(domain)
        out = []
        for r in records:
            out.append({
                'id': r.id,
                'name': r.name,
                'resource_uri': r.resource_uri,
                'resource_type': r.resource_type,
                'description': r.description,
                'last_fetch': r.last_fetch,
                'server_id': r.server_id.id,
                'server_name': r.server_id.name,
            })
        return out


class Query(graphene.ObjectType):
    # 兼容保留：服务器/资源（次要）
    servers = graphene.List(MCPServerType, active=graphene.Boolean(default_value=True))
    server = graphene.Field(MCPServerType, id=graphene.Int(required=True))
    resources = graphene.List(MCPResourceType, server_id=graphene.Int(), active=graphene.Boolean(default_value=True))
    resource = graphene.Field(MCPResourceType, id=graphene.Int(required=True))

    # Odoo 数据为一等公民：模型、字段、记录
    models = graphene.List(graphene.String, description="返回可用的 Odoo 模型名称（可过滤权限后扩展）")

    class OdooFieldType(graphene.ObjectType):
        name = graphene.String()
        type = graphene.String()
        string = graphene.String()
        required = graphene.Boolean()
        relation = graphene.String()
        # 新增字段元数据
        readonly = graphene.Boolean()
        help = graphene.String()
        selection_options = JSONString(description="选择字段的选项列表")

    # 嵌套数据查询输入类型
    class NestedFieldInput(graphene.InputObjectType):
        field = graphene.String(required=True, description="字段名称")
        sub_fields = graphene.List(graphene.String, description="子字段列表")
        max_records = graphene.Int(default_value=10, description="一对多/多对多字段最大记录数")

    # 增强的记录查询，支持更精细的嵌套控制
    odooRecordsNested = JSONString(
        model=graphene.String(required=True),
        domain=JSONString(),
        fields=graphene.List(graphene.String),
        nested_config=graphene.List(NestedFieldInput, description="嵌套字段配置"),
        limit=graphene.Int(),
        offset=graphene.Int(),
        order=graphene.String(),
        max_depth=graphene.Int(default_value=3),
        description="高级嵌套查询，支持精细化嵌套控制"
    )

    model_fields = graphene.List(OdooFieldType, model=graphene.String(required=True), description="返回指定模型的字段元数据")

    # 记录查询，使用 JSON 返回以增强通用性
    odooRecords = JSONString(
        model=graphene.String(required=True),
        domain=JSONString(),
        fields=graphene.List(graphene.String),
        limit=graphene.Int(),
        offset=graphene.Int(),
        order=graphene.String(),
        nested_fields=graphene.List(graphene.String, description="要嵌套加载的关系字段 ['field1', 'field2']"),
        max_depth=graphene.Int(default_value=3, description="最大嵌套深度，默认3层"),
        description="查询记录列表（返回 JSON 数组）支持嵌套数据"
    )

    odooRecord = JSONString(
        model=graphene.String(required=True),
        id=graphene.Int(required=True),
        fields=graphene.List(graphene.String),
        nested_fields=graphene.List(graphene.String, description="要嵌套加载的关系字段 ['field1', 'field2']"),
        max_depth=graphene.Int(default_value=3, description="最大嵌套深度，默认3层"),
        description="按 ID 获取单条记录（返回 JSON 对象）支持嵌套数据"
    )

    odooSearchCount = graphene.Int(
        model=graphene.String(required=True),
        domain=JSONString(),
        description="返回符合条件的记录数量"
    )

    def resolve_servers(self, info, active=True):
        env = info.context.get('env')
        if env is None:
            return []
        domain = []
        if active is not None:
            domain.append(('active', '=', bool(active)))
        records = env['mcp.server'].sudo().search(domain)
        out = []
        for s in records:
            out.append({
                'id': s.id,
                'name': s.name,
                'port': s.port,
                'state': s.state,
                'last_connection': s.last_connection,
                'connection_count': s.connection_count,
                'resource_count': s.resource_count,
            })
        return out

    def resolve_server(self, info, id):
        env = info.context.get('env')
        if env is None:
            return None
        s = env['mcp.server'].sudo().browse(int(id))
        if not s.exists():
            return None
        return {
            'id': s.id,
            'name': s.name,
            'port': s.port,
            'state': s.state,
            'last_connection': s.last_connection,
            'connection_count': s.connection_count,
            'resource_count': s.resource_count,
        }

    def resolve_resources(self, info, server_id=None, active=True):
        env = info.context.get('env')
        if env is None:
            return []
        domain = []
        if server_id:
            domain.append(('server_id', '=', int(server_id)))
        if active is not None:
            domain.append(('active', '=', bool(active)))
        records = env['mcp.resource'].sudo().search(domain)
        out = []
        for r in records:
            out.append({
                'id': r.id,
                'name': r.name,
                'resource_uri': r.resource_uri,
                'resource_type': r.resource_type,
                'description': r.description,
                'last_fetch': r.last_fetch,
                'server_id': r.server_id.id,
                'server_name': r.server_id.name,
            })
        return out

    def resolve_resource(self, info, id):
        env = info.context.get('env')
        if env is None:
            return None
        r = env['mcp.resource'].sudo().browse(int(id))
        if not r.exists():
            return None
        return {
            'id': r.id,
            'name': r.name,
            'resource_uri': r.resource_uri,
            'resource_type': r.resource_type,
            'description': r.description,
            'last_fetch': r.last_fetch,
            'server_id': r.server_id.id,
            'server_name': r.server_id.name,
        }

    def resolve_models(self, info):
        env = info.context.get('env')
        if env is None:
            return []
        # 返回注册模型名列表（可在此添加过滤逻辑）
        try:
            return sorted(list(env.registry.models.keys()))
        except Exception:
            return []

    def resolve_model_fields(self, info, model):
        env = info.context.get('env')
        if env is None:
            return []
        if model not in env:
            return []
        m = env[model].sudo()
        out = []
        for name, field in m._fields.items():
            field_info = {
                'name': name,
                'type': field.type,
                'string': getattr(field, 'string', name),
                'required': bool(getattr(field, 'required', False)),
                'relation': getattr(field, 'comodel_name', None),
                'readonly': bool(getattr(field, 'readonly', False)),
                'help': getattr(field, 'help', None),
            }

            # 处理选择字段的选项
            if hasattr(field, 'selection') and field.selection:
                try:
                    if callable(field.selection):
                        selection_options = field.selection(m)
                    else:
                        selection_options = field.selection
                    field_info['selection_options'] = [{"key": k, "value": v} for k, v in selection_options]
                except Exception:
                    field_info['selection_options'] = None

            out.append(field_info)
        return out

    def resolve_odooRecords(self, info, model, domain=None, fields=None, limit=100, offset=0, order=None,
                            nested_fields=None, max_depth=3):
        env = info.context.get('env')
        if env is None:
            return []
        if model not in env:
            return []

        model_obj = env[model].sudo()
        parsed_domain = _parse_domain(domain)

        # 如果指定了嵌套字段，需要包含在查询中
        query_fields = fields or []
        if nested_fields:
            # 添加嵌套字段到查询字段中
            for nested_field in nested_fields:
                base_field = nested_field.split('.')[0]  # 获取基础字段名
                if base_field not in query_fields:
                    query_fields.append(base_field)
        
        records = model_obj.search_read(
            domain=parsed_domain,
            fields=query_fields or [],
            limit=limit or 100,
            offset=offset or 0,
            order=order or None,
        )

        # 处理嵌套数据
        processed_records = []
        for rec_data in records:
            if nested_fields:
                # 获取记录对象用于嵌套处理
                record = model_obj.browse(rec_data['id'])
                processed_data = _process_nested_fields(
                    rec_data, record, nested_fields, max_depth, 0
                )
                processed_records.append(processed_data)
            else:
                # 原有的 many2one 处理逻辑
                for k, v in list(rec_data.items()):
                    if isinstance(v, tuple) and len(v) == 2:
                        rec_data[k] = {"id": v[0], "name": v[1]}
                processed_records.append(rec_data)

        return processed_records

    def resolve_odooRecord(self, info, model, id, fields=None, nested_fields=None, max_depth=3):
        env = info.context.get('env')
        if env is None:
            return None
        if model not in env:
            return None
        record = env[model].sudo().browse(int(id))
        if not record.exists():
            return None

        # 若未指定字段，读取所有非大字段
        if not fields:
            exclude_types = ['binary', 'html']
            fields = [f for f, fld in record._fields.items() if fld.type not in exclude_types]

        # 如果指定了嵌套字段，需要包含在查询中
        query_fields = fields or []
        if nested_fields:
            for nested_field in nested_fields:
                base_field = nested_field.split('.')[0]
                if base_field not in query_fields:
                    query_fields.append(base_field)

        data = record.read(query_fields)[0]

        # 处理嵌套数据
        if nested_fields:
            data = _process_nested_fields(data, record, nested_fields, max_depth, 0)
        else:
            # 原有的 many2one 处理逻辑
            for k, v in list(data.items()):
                if isinstance(v, tuple) and len(v) == 2:
                    data[k] = {"id": v[0], "name": v[1]}
        
        return data

    def resolve_odooRecordsNested(self, info, model, domain=None, fields=None, nested_config=None, limit=100, offset=0,
                                  order=None, max_depth=3):
        """高级嵌套查询，支持精细化配置"""
        env = info.context.get('env')
        if env is None:
            return []
        if model not in env:
            return []

        model_obj = env[model].sudo()
        parsed_domain = _parse_domain(domain)

        # 处理嵌套配置
        query_fields = fields or []
        if nested_config:
            for config in nested_config:
                if config.get('field') and config['field'] not in query_fields:
                    query_fields.append(config['field'])

        records = model_obj.search_read(
            domain=parsed_domain,
            fields=query_fields or [],
            limit=limit or 100,
            offset=offset or 0,
            order=order or None,
        )

        # 处理高级嵌套数据
        processed_records = []
        for rec_data in records:
            if nested_config:
                record = model_obj.browse(rec_data['id'])
                processed_data = rec_data.copy()

                for config in nested_config:
                    field_name = config.get('field')
                    sub_fields = config.get('sub_fields', [])
                    max_records = config.get('max_records', 10)

                    if field_name in record._fields:
                        field = record._fields[field_name]
                        field_value = rec_data.get(field_name)

                        if field.type in ('one2many', 'many2many') and field_value:
                            try:
                                related_model = env[field.comodel_name].sudo()
                                related_records = related_model.browse(field_value[:max_records])

                                nested_data = []
                                for rel_rec in related_records:
                                    if rel_rec.exists():
                                        if sub_fields:
                                            rel_data = rel_rec.read(sub_fields)[0]
                                        else:
                                            # 默认获取基础字段
                                            exclude_types = ['binary', 'html', 'text']
                                            basic_fields = [f for f, fld in rel_rec._fields.items()
                                                            if fld.type not in exclude_types][:8]
                                            rel_data = rel_rec.read(basic_fields)[0]

                                        # 处理嵌套记录的 many2one 字段
                                        for k, v in list(rel_data.items()):
                                            if isinstance(v, tuple) and len(v) == 2:
                                                rel_data[k] = {"id": v[0], "name": v[1]}

                                        nested_data.append(rel_data)

                                processed_data[field_name] = nested_data
                            except Exception:
                                processed_data[field_name] = field_value

                        elif field.type == 'many2one' and isinstance(field_value, tuple) and len(field_value) == 2:
                            processed_data[field_name] = {"id": field_value[0], "name": field_value[1]}

                processed_records.append(processed_data)
            else:
                # 基础处理
                for k, v in list(rec_data.items()):
                    if isinstance(v, tuple) and len(v) == 2:
                        rec_data[k] = {"id": v[0], "name": v[1]}
                processed_records.append(rec_data)

        return processed_records

    def resolve_odooSearchCount(self, info, model, domain=None):
        env = info.context.get('env')
        if env is None:
            return 0
        if model not in env:
            return 0
        parsed_domain = _parse_domain(domain)
        return env[model].sudo().search_count(parsed_domain)


class Mutation(graphene.ObjectType):
    createRecord = JSONString(
        model=graphene.String(required=True),
        values=JSONString(required=True),
        description="创建记录，返回创建后的记录 JSON"
    )
    updateRecord = JSONString(
        model=graphene.String(required=True),
        id=graphene.Int(required=True),
        values=JSONString(required=True),
        description="更新记录，返回更新后的记录 JSON"
    )
    deleteRecord = graphene.Boolean(
        model=graphene.String(required=True),
        id=graphene.Int(required=True),
        description="删除记录，返回是否成功"
    )

    def resolve_createRecord(self, info, model, values):
        env = info.context.get('env')
        if env is None or model not in env:
            return None
        vals = _prep_values(model, values, env)
        obj = env[model].sudo().create(vals)
        return obj.read()[0]

    def resolve_updateRecord(self, info, model, id, values):
        env = info.context.get('env')
        if env is None or model not in env:
            return None
        rec = env[model].sudo().browse(int(id))
        if not rec.exists():
            return None
        vals = _prep_values(model, values, env)
        rec.write(vals)
        return rec.read()[0]

    def resolve_deleteRecord(self, info, model, id):
        env = info.context.get('env')
        if env is None or model not in env:
            return False
        rec = env[model].sudo().browse(int(id))
        if not rec.exists():
            return False
        rec.unlink()
        return True


def build_schema():
    return graphene.Schema(query=Query, mutation=Mutation)
