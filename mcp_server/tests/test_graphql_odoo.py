# -*- coding: utf-8 -*-
import json

from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestGraphQLForOdoo(HttpCase):
    def setUp(self):
        super().setUp()
        # 创建一个测试用的 MCP 服务器记录用于 API Key 授权（任意 active 服务器即可）
        self.server = self.env['mcp.server'].sudo().create({
            'name': 'GraphQL Odoo Server',
            'server_url': 'https://mcp.example.com',
            'api_key': 'gql-odoo-key-001',
            'state': 'active',
            'active': True,
        })

    def _post_graphql(self, query, variables=None):
        body = json.dumps({'query': query, 'variables': variables or {}}).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Api-Key': self.server.api_key,
        }
        res = self.url_open('/api/mcp/graphql', data=body, headers=headers)
        if hasattr(res, 'data'):
            payload = res.data
        else:
            payload = res
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8')
        try:
            return json.loads(payload)
        except Exception:
            return {}

    def test_models_and_records_query(self):
        # 查询模型列表
        q1 = """
        query { models }
        """
        data = self._post_graphql(q1)
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('data', data)
        self.assertIn('models', data['data'])
        self.assertIsInstance(data['data']['models'], list)

        # 查询联系人前 3 条（可能为空，但应返回数组）
        q2 = """
        query {
          odooRecords(model: "res.partner", domain: "[]", fields: ["name"], limit: 3)
        }
        """
        data2 = self._post_graphql(q2)
        self.assertEqual(data2.get('status'), 'success')
        self.assertIn('data', data2)
        self.assertIn('odooRecords', data2['data'])
        self.assertIsInstance(data2['data']['odooRecords'], list)

    def test_crud_mutations(self):
        # 创建
        m_create = """
        mutation($vals: JSONString!) {
          createRecord(model: "res.partner", values: $vals)
        }
        """
        vals = {"name": "GQL Test Partner"}
        r_create = self._post_graphql(m_create, variables={"vals": json.dumps(vals)})
        self.assertEqual(r_create.get('status'), 'success')
        partner = r_create['data']['createRecord']
        self.assertTrue(partner and partner.get('id'))

        pid = int(partner['id'])

        # 更新
        m_update = """
        mutation($id: Int!, $vals: JSONString!) {
          updateRecord(model: "res.partner", id: $id, values: $vals)
        }
        """
        r_update = self._post_graphql(m_update, variables={"id": pid, "vals": json.dumps({"phone": "123456"})})
        self.assertEqual(r_update.get('status'), 'success')
        self.assertEqual(r_update['data']['updateRecord']['id'], pid)

        # 删除
        m_delete = """
        mutation($id: Int!) {
          deleteRecord(model: "res.partner", id: $id)
        }
        """
        r_delete = self._post_graphql(m_delete, variables={"id": pid})
        self.assertEqual(r_delete.get('status'), 'success')
        self.assertTrue(r_delete['data']['deleteRecord'])
