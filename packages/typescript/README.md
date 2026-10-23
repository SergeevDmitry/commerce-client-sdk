# @agentic-commerce-lab/ucp-client

A UCP 2026-08-25 REST client for TypeScript and JavaScript on Node.js 20+. Discover merchants, select capabilities, search catalogs, and manage carts, checkout sessions and orders.

## Install

The 0.1.0 package is prepared for npm publication. Before that release, build with `npm ci && npm run build && npm pack` in this directory and install the resulting `.tgz` with `npm install ./agentic-commerce-lab-ucp-client-0.1.0.tgz`.

## Connect and search

```ts
import { UcpClient } from '@agentic-commerce-lab/ucp-client';

const client = await UcpClient.connect('https://merchant.example', {
  agentProfileUrl: 'https://agent.example/profile.json',
});
const result = await client.searchCatalog({ query: 'coffee' });
console.log(result.data);
```

Host a UCP platform profile at `agentProfileUrl` advertising the capabilities and signing keys your application actually implements. Set `supportedCapabilities` when your platform implements a smaller set. Response data stays in the UCP envelope, including business status and any continuation URL.

## Sign requests

```ts
import { readFileSync } from 'node:fs';
import { createSigner } from '@agentic-commerce-lab/ucp-client/signing';

const client = await UcpClient.connect('https://merchant.example', {
  agentProfileUrl: 'https://agent.example/profile.json',
  signer: createSigner({ keyId: 'agent-key-1', privateKey: readFileSync('private-key.pem', 'utf8') }),
});
```

The matching public key belongs in your platform profile. Ed25519 and P-256 keys are supported. Merchant-specific bearer authentication can be supplied through `headers`. Discovery and API redirects are returned without following them. Cross-origin REST endpoints require an explicit `allowedServiceOrigins` allowlist. HTTPS is the default; `allowHttpForDevelopment: true` enables local fixtures.

## Repeat an uncertain write

```ts
const request = client.prepare('create_cart', { line_items: [] });
try {
  const result = await client.send(request);
} catch (error) {
  // Persist request and decide whether to repeat it with client.send(request).
  // Its serialized body and idempotency key stay unchanged; signatures are refreshed.
  throw error;
}
```

There are no automatic retries. `UcpError` exposes `request`, `status` and `data`. The default timeout is ten seconds; configure `timeoutMs` per client.

Methods: `searchCatalog`, `lookupCatalog`, `createCart`, `getCart`, `updateCart`, `cancelCart`, `createCheckout`, `getCheckout`, `updateCheckout`, `completeCheckout`, `cancelCheckout`, `getOrder`. IDs are encoded as one path segment. Payloads use JSON objects; use the official UCP models for full schema validation.

[Source and issue tracker](https://github.com/agentic-commerce-lab/commerce-client-sdk) · [UCP guide](https://www.agentic-commerce.sh/protokolle/ucp/)
