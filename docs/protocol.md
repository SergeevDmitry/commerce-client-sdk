# Protocol scope

Target: [UCP 2026-08-25](https://ucp.dev/2026-08-25/specification/overview/), [REST binding](https://ucp.dev/2026-08-25/services/shopping/rest.openapi.json), [signatures](https://ucp.dev/2026-08-25/specification/signatures/).

The checked-in OpenAPI artifact is used as an independent path/method reference. It also contains the legacy `get_product` operation, which these clients do not expose. Twelve current operations cover checkout, carts, catalog search/lookup and order retrieval.

Capabilities are selected by supported name and exact version. Extensions with unavailable parents are pruned. Service endpoint prefixes are preserved. Successful responses must retain the expected versioned UCP envelope. JSON payloads are deliberately exposed for applications to combine with the official schema/model libraries.

Transport tests and independent RFC 9421 verification cover the implemented scope. Full schema composition, payment-handler flows, webhook verification and a complete merchant checkout integration are not yet part of this release's verification.
