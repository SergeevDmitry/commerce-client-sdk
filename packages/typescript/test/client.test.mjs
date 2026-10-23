import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {UcpClient,UcpError,UCP_VERSION,selectCapabilities} from '../dist/index.js';
const ops=JSON.parse(readFileSync(new URL('../../../reference/operations.json',import.meta.url)));
const caps=['checkout','cart','catalog.search','catalog.lookup','order'];
const profile=endpoint=>({ucp:{version:UCP_VERSION,services:{'dev.ucp.shopping':[{version:UCP_VERSION,transport:'rest',endpoint}]},capabilities:Object.fromEntries(caps.map(x=>['dev.ucp.shopping.'+x,[{version:UCP_VERSION}]]))}});
const envelope={ucp:{version:UCP_VERSION},status:'requires_escalation',continue_url:'https://merchant.example/continue'};
async function fixture(fn){
  const seen=[]; let origin;
  const server=createServer(async(req,res)=>{const chunks=[];for await (const chunk of req) chunks.push(chunk);const body=Buffer.concat(chunks).toString();seen.push({path:req.url,method:req.method,headers:req.headers,body});res.setHeader('content-type','application/json');res.end(JSON.stringify(req.url==='/.well-known/ucp'?profile(origin+'/api/v2'):envelope));});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));origin=`http://127.0.0.1:${server.address().port}`;
  try{await fn(await UcpClient.connect(origin,{agentProfileUrl:origin+'/agent.json',allowHttpForDevelopment:true}),seen,origin);}finally{await new Promise(r=>server.close(r));}
}
test('all exposed operations use independently pinned OpenAPI method and prefixed path',async()=>fixture(async(client,seen,origin)=>{
  for(const [name,op] of Object.entries(ops).filter(([name])=>name!=='get_product')){
    const prepared=client.prepare(name,op.method==='GET'?undefined:{label:'Kaffee ☕'},{id:'order/42'});
    assert.equal(prepared.method,op.method);assert.equal(prepared.url,origin+'/api/v2'+op.path.replace('{id}','order%2F42'));
    const result=await client.send(prepared);assert.equal(result.data.status,'requires_escalation');assert.equal(result.data.continue_url,envelope.continue_url);
    assert.equal(seen.at(-1).path,'/api/v2'+op.path.replace('{id}','order%2F42'));
    assert.equal(seen.at(-1).headers['ucp-agent'],`profile="${origin}/agent.json"`);
  }
}));
test('prepared writes retain exact body and idempotency key on deliberate retry',async()=>fixture(async(client,seen)=>{
  const body={line_items:[{title:'ä'}]};const p=client.prepare('create_cart',body);body.line_items[0].title='changed';
  await client.send(p);await client.send(p);assert.equal(seen.at(-1).body,seen.at(-2).body);assert.equal(seen.at(-1).headers['idempotency-key'],p.idempotencyKey);assert.equal(seen.at(-2).headers['idempotency-key'],p.idempotencyKey);
}));
test('capability, operation, GET body and path checks fail before HTTP',async()=>fixture(async(client,seen,origin)=>{
  for(const f of [()=>client.prepare('toString'),()=>client.prepare('get_cart',{}, {id:'x'}),()=>client.prepare('get_cart',undefined,{id:'..'})])assert.throws(f,UcpError);
  await assert.rejects(client.send({...client.prepare('get_cart',undefined,{id:'x'}),url:origin+'/api/v2/../../outside'}),UcpError);
  assert.equal(seen.length,1);
}));
test('capability selection removes extensions with missing parents',()=>{
  const p=profile('https://merchant.example');p.ucp.capabilities['example.extension']=[{version:UCP_VERSION,extends:'missing.parent'}];
  assert.deepEqual(selectCapabilities(p,['example.extension']),{});
});
test('redirect discovery is not followed and cross-origin service needs allowlist',async()=>{
  let calls=0;const options={agentProfileUrl:'https://agent.example/profile.json',fetch:async()=>{calls++;return new Response('',{status:302,headers:{location:'https://other.example'}})}};
  await assert.rejects(UcpClient.connect('https://merchant.example',options),e=>e.status===302);assert.equal(calls,1);
  const fetch=async()=>Response.json(profile('https://api.example/v2'));
  await assert.rejects(UcpClient.connect('https://merchant.example',{...options,fetch}),/explicitly allowed/);
  assert.equal((await UcpClient.connect('https://merchant.example',{...options,fetch,allowedServiceOrigins:['https://api.example']})).endpoint,'https://api.example/v2');
});
test('HTTP error preserves original body and prepared request; network failure never retries',async()=>{
  let calls=0;const fetch=async(url)=>{if(String(url).endsWith('/.well-known/ucp'))return Response.json(profile('https://merchant.example/api'));calls++;return Response.json({code:'out_of_stock'},{status:409})};
  const client=await UcpClient.connect('https://merchant.example',{agentProfileUrl:'https://agent.example/p',fetch});const p=client.prepare('create_cart',{});
  await assert.rejects(client.send(p),e=>e.status===409&&e.data.code==='out_of_stock'&&e.request===p);assert.equal(calls,1);
  const failed=await UcpClient.connect('https://merchant.example',{agentProfileUrl:'https://agent.example/p',fetch:async(url)=>String(url).endsWith('/.well-known/ucp')?Response.json(profile('https://merchant.example/api')):Promise.reject(new Error('network'))});
  const q=failed.prepare('create_cart',{});await assert.rejects(failed.send(q),e=>e.request===q&&e.cause.message==='network');
});
