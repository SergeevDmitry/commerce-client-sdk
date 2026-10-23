import json
from pathlib import Path
from dataclasses import replace
import unittest
import httpx
from agentic_commerce_ucp import UcpClient, UcpError, UCP_VERSION
from agentic_commerce_ucp.client import select_capabilities

ROOT = Path(__file__).resolve().parents[3]
OPS = json.loads((ROOT/'reference/operations.json').read_text())
CAPS = ['checkout', 'cart', 'catalog.search', 'catalog.lookup', 'order']
def profile(endpoint='https://merchant.example/api/v2'):
    return {'ucp': {'version': UCP_VERSION, 'services': {'dev.ucp.shopping': [{'version': UCP_VERSION, 'transport':'rest', 'endpoint':endpoint}]}, 'capabilities':{'dev.ucp.shopping.'+x:[{'version':UCP_VERSION}] for x in CAPS}}}
ENVELOPE = {'ucp':{'version':UCP_VERSION},'status':'requires_escalation','continue_url':'https://merchant.example/continue'}

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen=[]
        self.discovery=profile()
        self.reply=lambda req: httpx.Response(200,json=ENVELOPE)
        def handle(req):
            self.seen.append(req)
            if req.url.path=='/.well-known/ucp':return httpx.Response(200,json=self.discovery)
            return self.reply(req)
        self.http=httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.client=await UcpClient.connect('https://merchant.example',agent_profile_url='https://agent.example/profile.json',http_client=self.http)
    async def asyncTearDown(self):await self.http.aclose()
    async def test_official_operation_paths_methods_and_business_state(self):
        for name,op in OPS.items():
            if name=='get_product':continue
            with self.subTest(operation=name):
                p=self.client.prepare(name,None if op['method']=='GET' else {'label':'Kaffee ☕'},id='order/42')
                self.assertEqual(p.method,op['method'])
                self.assertEqual(p.url,'https://merchant.example/api/v2'+op['path'].replace('{id}','order%2F42'))
                result=await self.client.send(p)
                self.assertEqual(result.data,ENVELOPE)
                self.assertEqual(self.seen[-1].headers['ucp-agent'],'profile="https://agent.example/profile.json"')
                self.assertIn('/api/v2/',str(self.seen[-1].url))
    async def test_explicit_repeat_keeps_body_and_key(self):
        body={'line_items':[{'title':'ä'}]};p=self.client.prepare('create_cart',body);body['line_items'][0]['title']='changed'
        await self.client.send(p);await self.client.send(p)
        self.assertEqual(self.seen[-1].content,self.seen[-2].content)
        self.assertEqual(self.seen[-1].headers['idempotency-key'],p.idempotency_key)
        self.assertEqual(self.seen[-2].headers['idempotency-key'],p.idempotency_key)
    async def test_invalid_requests_do_not_reach_http(self):
        for args,kwargs in [(('unknown',),{}),(('get_cart',{}),{'id':'x'}),(('get_cart',),{'id':'..'})]:
            with self.assertRaises(UcpError):self.client.prepare(*args,**kwargs)
        p=self.client.prepare('get_cart',id='x')
        with self.assertRaises(UcpError):await self.client.send(replace(p,url='https://merchant.example/api/v2/../../outside'))
        self.assertEqual(len(self.seen),1)
    async def test_missing_capability_and_extension(self):
        del self.discovery['ucp']['capabilities']['dev.ucp.shopping.cart']
        client=await UcpClient.connect('https://merchant.example',agent_profile_url='https://agent.example/p',http_client=self.http)
        with self.assertRaises(UcpError):client.prepare('create_cart',{})
        self.discovery['ucp']['capabilities']['example.extension']=[{'version':UCP_VERSION,'extends':'missing'}]
        self.assertEqual(select_capabilities(self.discovery,['example.extension']),{})
    async def test_http_error_retains_response_and_prepared_request(self):
        self.reply=lambda req:httpx.Response(409,json={'code':'out_of_stock'})
        p=self.client.prepare('create_cart',{})
        with self.assertRaises(UcpError) as ctx:await self.client.send(p)
        self.assertEqual(ctx.exception.status,409);self.assertEqual(ctx.exception.data,{'code':'out_of_stock'});self.assertIs(ctx.exception.request,p)
        self.assertEqual(len(self.seen),2)
    async def test_network_failure_is_not_retried(self):
        def fail(req):raise httpx.ReadTimeout('timeout')
        self.reply=fail;p=self.client.prepare('create_cart',{})
        with self.assertRaises(UcpError) as ctx:await self.client.send(p)
        self.assertIs(ctx.exception.request,p);self.assertEqual(len(self.seen),2)
    async def test_discovery_redirect_is_not_followed(self):
        calls=[]
        def redirect(req):calls.append(req);return httpx.Response(302,headers={'location':'https://other.example'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(redirect),follow_redirects=True) as http:
            with self.assertRaises(UcpError) as ctx:await UcpClient.connect('https://merchant.example',agent_profile_url='https://agent.example/p',http_client=http)
        self.assertEqual(ctx.exception.status,302);self.assertEqual(len(calls),1)
    async def test_cross_origin_service_needs_allowlist(self):
        self.discovery=profile('https://api.example/v2')
        with self.assertRaises(UcpError):await UcpClient.connect('https://merchant.example',agent_profile_url='https://agent.example/p',http_client=self.http)
        client=await UcpClient.connect('https://merchant.example',agent_profile_url='https://agent.example/p',http_client=self.http,allowed_service_origins=['https://api.example'])
        self.assertEqual(client.endpoint,'https://api.example/v2')
    async def test_injected_http_client_remains_open(self):
        await self.client.aclose();self.assertFalse(self.http.is_closed)
