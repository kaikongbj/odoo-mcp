{
    'name': 'MCP Server',
    'version': '1.0',
    'category': 'Services/MCP',
    'summary': 'MCP服务器模块',
    'description': """
MCP服务器模块
===============
该模块提供MCP服务器功能。
    """,
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/mcp_server_views.xml',
        'data/mcp_server_data.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'author': 'Odoo',
    'website': 'https://www.odoo.com',
    'post_init_hook': 'post_init_hook',
}
