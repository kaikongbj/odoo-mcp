import graphene
from graphene.types.json import JSONString


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
    servers = graphene.List(MCPServerType, active=graphene.Boolean(default_value=True))
    server = graphene.Field(MCPServerType, id=graphene.Int(required=True))
    resources = graphene.List(MCPResourceType, server_id=graphene.Int(), active=graphene.Boolean(default_value=True))
    resource = graphene.Field(MCPResourceType, id=graphene.Int(required=True))

    # 通用 Odoo 访问，返回 JSON
    odoo = JSONString(
        model=graphene.String(required=True),
        domain=JSONString(),
        fields=graphene.List(graphene.String),
        limit=graphene.Int(),
        offset=graphene.Int(),
        order=graphene.String()
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

    def resolve_odoo(self, info, model, domain=None, fields=None, limit=100, offset=0, order=None):
        env = info.context.get('env')
        if env is None:
            return []
        model_obj = env[model].sudo()
        parsed_domain = domain or []
        if isinstance(parsed_domain, str) and parsed_domain.strip():
            import json
            try:
                parsed_domain = json.loads(parsed_domain)
            except Exception:
                parsed_domain = []
        records = model_obj.search_read(
            domain=parsed_domain,
            fields=fields or [],
            limit=limit or 100,
            offset=offset or 0,
            order=order or None,
        )
        return records


def build_schema():
    return graphene.Schema(query=Query)
