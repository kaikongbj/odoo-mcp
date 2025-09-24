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
    server_url = graphene.String()
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

    model_fields = graphene.List(OdooFieldType, model=graphene.String(required=True), description="返回指定模型的字段元数据")

    # 记录查询，使用 JSON 返回以增强通用性
    odooRecords = JSONString(
        model=graphene.String(required=True),
        domain=JSONString(),
        fields=graphene.List(graphene.String),
        limit=graphene.Int(),
        offset=graphene.Int(),
        order=graphene.String(),
        description="查询记录列表（返回 JSON 数组）"
    )

    odooRecord = JSONString(
        model=graphene.String(required=True),
        id=graphene.Int(required=True),
        fields=graphene.List(graphene.String),
        description="按 ID 获取单条记录（返回 JSON 对象）"
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
                'server_url': s.server_url,
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
            'server_url': s.server_url,
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
            out.append({
                'name': name,
                'type': field.type,
                'string': getattr(field, 'string', name),
                'required': bool(getattr(field, 'required', False)),
                'relation': getattr(field, 'comodel_name', None),
            })
        return out

    def resolve_odooRecords(self, info, model, domain=None, fields=None, limit=100, offset=0, order=None):
        env = info.context.get('env')
        if env is None:
            return []
        if model not in env:
            return []
        model_obj = env[model].sudo()
        parsed_domain = _parse_domain(domain)
        records = model_obj.search_read(
            domain=parsed_domain,
            fields=fields or [],
            limit=limit or 100,
            offset=offset or 0,
            order=order or None,
        )
        # 处理 many2one 元组为对象
        for rec in records:
            for k, v in list(rec.items()):
                if isinstance(v, tuple) and len(v) == 2:
                    rec[k] = {"id": v[0], "name": v[1]}
        return records

    def resolve_odooRecord(self, info, model, id, fields=None):
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
        data = record.read(fields)[0]
        for k, v in list(data.items()):
            if isinstance(v, tuple) and len(v) == 2:
                data[k] = {"id": v[0], "name": v[1]}
        return data

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
