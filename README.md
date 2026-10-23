# Agentic Commerce UCP clients

TypeScript/JavaScript and Python REST clients for Universal Commerce Protocol **2026-08-25**. Discover a merchant, select shared capabilities, and call catalog, cart, checkout and order operations through its advertised endpoint.

| Language | Package | Source |
| --- | --- | --- |
| TypeScript / JavaScript (Node.js 20+) | `@agentic-commerce-lab/ucp-client` | [Quick start](packages/typescript/README.md) |
| Python 3.10+ | `agentic-commerce-ucp-client` | [Quick start](packages/python/README.md) |

## What the clients provide

- Discovery at `/.well-known/ucp` with explicit protocol and REST binding selection.
- Twelve named operations for catalog search/lookup, carts, checkout sessions and orders.
- RFC 9421 request signing with Ed25519 or P-256, including the digest of the exact transmitted body.
- Prepared requests that retain the same body and idempotency key for a deliberate retry after an uncertain write.
- Structured HTTP errors with the original response and prepared request; business states and `continue_url` remain available to the caller.

Request and response payloads are JSON objects. Pair these transport clients with the [official UCP schemas and model SDKs](https://ucp.dev/2026-08-25/) for composed payload validation. The first release covers REST calls and outgoing request signatures; webhook verification, payment-handler execution and schema composition are separate integration work.

## Package availability

Version 0.1.0 is prepared for npm and PyPI. Until a registry release is visible, install the built tarball or wheel from a GitHub release, or build from source. The package names above are planned registry coordinates, not a claim that a registry publication already exists.

## Development

```sh
cd packages/typescript
npm ci
npm run build
npm test
cd ../..
python3 -m venv .venv
.venv/bin/pip install -e 'packages/python[signing]' -r tests/requirements.txt
.venv/bin/python -m unittest discover -s packages/python/tests -v
.venv/bin/python tests/test_signatures.py
```

Tests compare operation paths to the pinned upstream OpenAPI artifact, exercise HTTP request behavior, and verify both signers with the independent `http-message-signatures` library. These checks do not establish full UCP conformance or interoperability with every merchant.

See [release setup](docs/releases.md) and [scope and protocol reference](docs/protocol.md).

Own source is MIT licensed. The upstream reference artifact retains its Apache-2.0 license; see [reference attribution](reference/NOTICE).
