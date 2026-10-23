# agentic-commerce-ucp-client

An async UCP 2026-08-25 REST client for Python 3.10+. Discover merchants, select capabilities, search catalogs, and manage carts, checkout sessions and orders.

## Install

Version 0.1.0 is prepared for PyPI publication. Before that release, build the wheel from this repository and install the resulting file:

```sh
python -m build packages/python
pip install 'packages/python/dist/agentic_commerce_ucp_client-0.1.0-py3-none-any.whl[signing]'
```

## Connect and search

```python
import asyncio
from agentic_commerce_ucp import UcpClient

async def main():
    async with await UcpClient.connect(
        "https://merchant.example",
        agent_profile_url="https://agent.example/profile.json",
    ) as client:
        result = await client.search_catalog({"query": "coffee"})
        print(result.data)

asyncio.run(main())
```

Host a UCP platform profile at `agent_profile_url` advertising the capabilities and signing keys your application actually implements. Set `supported_capabilities` to restrict your platform's capabilities. Response data retains business status and continuation URLs.

## Sign requests

```python
from pathlib import Path
from agentic_commerce_ucp.signing import create_signer

signer = create_signer(key_id="agent-key-1", private_key=Path("private-key.pem").read_bytes())
client = await UcpClient.connect(
    "https://merchant.example",
    agent_profile_url="https://agent.example/profile.json",
    signer=signer,
)
```

Install the `signing` extra for cryptography support. The matching public key belongs in your platform profile. Ed25519 and P-256 are supported. Use `headers` for merchant-specific authentication. Discovery and API redirects are returned without following them. Cross-origin REST endpoints require `allowed_service_origins`. HTTPS is the default; local HTTP fixtures can opt into `allow_http_for_development=True`.

## Repeat an uncertain write

```python
request = client.prepare("create_cart", {"line_items": []})
result = await client.send(request)
# If the outcome is uncertain, retain request and deliberately repeat client.send(request).
```

Prepared requests retain the exact serialized body and idempotency key; signatures refresh on send. There are no automatic retries. `UcpError` exposes `request`, `status` and `data`. The default timeout is ten seconds; configure `timeout` in seconds. Close the client with `aclose()` or use its async context manager. Injected `httpx.AsyncClient` instances remain owned by the caller.

Methods: `search_catalog`, `lookup_catalog`, `create_cart`, `get_cart`, `update_cart`, `cancel_cart`, `create_checkout`, `get_checkout`, `update_checkout`, `complete_checkout`, `cancel_checkout`, `get_order`. IDs are encoded as one path segment. Payloads are dictionaries; use official UCP models for composed schema validation.

[Source and issues](https://github.com/agentic-commerce-lab/commerce-client-sdk) · [UCP guide](https://www.agentic-commerce.sh/protokolle/ucp/)
