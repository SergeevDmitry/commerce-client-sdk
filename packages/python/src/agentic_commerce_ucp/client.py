from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
import math
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping
from urllib.parse import quote
from uuid import uuid4

import httpx

UCP_VERSION = "2026-08-25"
OPERATIONS = {
    "create_checkout": ("POST", "/checkout-sessions", "checkout", True),
    "get_checkout": ("GET", "/checkout-sessions/{id}", "checkout", False),
    "update_checkout": ("PUT", "/checkout-sessions/{id}", "checkout", True),
    "complete_checkout": ("POST", "/checkout-sessions/{id}/complete", "checkout", True),
    "cancel_checkout": ("POST", "/checkout-sessions/{id}/cancel", "checkout", True),
    "create_cart": ("POST", "/carts", "cart", True),
    "get_cart": ("GET", "/carts/{id}", "cart", False),
    "update_cart": ("PUT", "/carts/{id}", "cart", True),
    "cancel_cart": ("POST", "/carts/{id}/cancel", "cart", True),
    "search_catalog": ("POST", "/catalog/search", "catalog.search", False),
    "lookup_catalog": ("POST", "/catalog/lookup", "catalog.lookup", False),
    "get_order": ("GET", "/orders/{id}", "order", False),
}
DEFAULT_CAPABILITIES = tuple("dev.ucp.shopping." + name for name in ("checkout", "cart", "catalog.search", "catalog.lookup", "order"))

@dataclass(frozen=True)
class PreparedRequest:
    operation: str
    method: str
    url: str
    body: str | None
    headers: Mapping[str, str]
    idempotency_key: str | None = None

@dataclass(frozen=True)
class Result:
    data: dict[str, Any]
    request: PreparedRequest
    status: int

class UcpError(Exception):
    def __init__(self, message: str, request: PreparedRequest | None = None, status: int | None = None, data: Any = None):
        super().__init__(message)
        self.request, self.status, self.data = request, status, data

Signer = Callable[[PreparedRequest], Mapping[str, str] | Awaitable[Mapping[str, str]]]

def _url(value: str, allow_http: bool = False) -> httpx.URL:
    try:
        parsed = httpx.URL(value)
        if not parsed.host or parsed.userinfo or parsed.fragment or parsed.scheme not in (("https", "http") if allow_http else ("https",)):
            raise ValueError()
        return parsed
    except (ValueError, httpx.InvalidURL) as error:
        raise UcpError("Expected an HTTPS URL without credentials or fragment") from error

def _origin(value: httpx.URL) -> tuple[str, str, int | None]:
    return value.scheme, value.host, value.port

def select_capabilities(profile: dict[str, Any], supported: tuple[str, ...] | list[str]) -> dict[str, Any]:
    selected = {}
    for name in supported:
        for entry in profile["ucp"]["capabilities"].get(name, []):
            if entry["version"] == UCP_VERSION:
                selected[name] = entry
                break
    changed = True
    while changed:
        changed = False
        for name, entry in list(selected.items()):
            parents = entry.get("extends", [])
            if isinstance(parents, str):
                parents = [parents]
            if not isinstance(parents, list) or any(not isinstance(parent, str) or parent not in selected for parent in parents):
                del selected[name]
                changed = True
    return selected

class UcpClient:
    def __init__(self, profile: dict[str, Any], endpoint: str, agent_profile_url: str, http: httpx.AsyncClient, owns_http: bool, supported: tuple[str, ...] | list[str], headers: dict[str, str], signer: Signer | None, timeout: float):
        self.merchant_profile, self.endpoint = profile, endpoint
        self.capabilities = MappingProxyType(select_capabilities(profile, supported))
        self.agent_profile_url, self._http, self._owns_http = agent_profile_url, http, owns_http
        self._headers, self._signer, self._timeout = headers.copy(), signer, timeout

    @classmethod
    async def connect(cls, merchant_url: str, *, agent_profile_url: str, supported_capabilities: tuple[str, ...] | list[str] = DEFAULT_CAPABILITIES, headers: dict[str, str] | None = None, signer: Signer | None = None, http_client: httpx.AsyncClient | None = None, timeout: float = 10, allowed_service_origins: list[str] | None = None, allow_http_for_development: bool = False) -> UcpClient:
        merchant = _url(merchant_url, allow_http_for_development)
        agent = _url(agent_profile_url, allow_http_for_development)
        if not math.isfinite(timeout) or timeout <= 0:
            raise UcpError("timeout must be positive")
        http = http_client or httpx.AsyncClient(follow_redirects=False)
        own = http_client is None
        request_headers = httpx.Headers(headers or {})
        request_headers["accept"] = "application/json"
        try:
            response = await http.get(merchant.copy_with(path="/.well-known/ucp", query=None), headers=request_headers, follow_redirects=False, timeout=timeout)
            if response.status_code != 200:
                raise UcpError("Merchant discovery did not return HTTP 200", status=response.status_code)
            try:
                profile = response.json()
            except ValueError as error:
                raise UcpError("Discovery did not return JSON", status=response.status_code) from error
            if not isinstance(profile, dict) or not isinstance(profile.get("ucp"), dict) or profile["ucp"].get("version") != UCP_VERSION or not isinstance(profile["ucp"].get("capabilities"), dict):
                raise UcpError(f"Expected a UCP {UCP_VERSION} discovery profile")
            for entries in profile["ucp"]["capabilities"].values():
                if not isinstance(entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("version"), str) for entry in entries):
                    raise UcpError("Invalid capability declarations")
            services = profile["ucp"].get("services", {})
            bindings = services.get("dev.ucp.shopping") if isinstance(services, dict) else None
            if not isinstance(bindings, list):
                raise UcpError("Merchant does not advertise a shopping service")
            binding = next((entry for entry in bindings if isinstance(entry, dict) and entry.get("transport") == "rest" and entry.get("version") == UCP_VERSION), None)
            if not binding or not isinstance(binding.get("endpoint"), str):
                raise UcpError(f"Merchant does not advertise a UCP {UCP_VERSION} REST endpoint")
            endpoint = _url(binding["endpoint"], allow_http_for_development)
            if endpoint.query:
                raise UcpError("REST endpoint must not contain a query")
            origins = {_origin(merchant)} | {_origin(_url(origin, allow_http_for_development)) for origin in allowed_service_origins or []}
            if _origin(endpoint) not in origins:
                raise UcpError("REST endpoint origin must be explicitly allowed")
            return cls(profile, str(endpoint).rstrip("/"), str(agent), http, own, supported_capabilities, headers or {}, signer, timeout)
        except Exception as error:
            if own:
                await http.aclose()
            if isinstance(error, UcpError):
                raise
            raise UcpError("Merchant discovery failed") from error

    def prepare(self, operation: str, body: dict[str, Any] | None = None, *, id: str | None = None, idempotency_key: str | None = None) -> PreparedRequest:
        if operation not in OPERATIONS:
            raise UcpError(f"Unknown operation: {operation}")
        method, template, capability, mutates = OPERATIONS[operation]
        if "dev.ucp.shopping." + capability not in self.capabilities:
            raise UcpError(f"Merchant and client do not share dev.ucp.shopping.{capability}")
        if "{id}" in template and (not id or id in (".", "..")):
            raise UcpError("This operation requires an ID")
        if method == "GET" and body is not None:
            raise UcpError("GET operations do not accept a body")
        if body is not None and not isinstance(body, dict):
            raise UcpError("Operation body must be a JSON object")
        headers = httpx.Headers(self._headers)
        for key in ("signature", "signature-input", "content-digest", "idempotency-key"):
            headers.pop(key, None)
        headers["accept"] = "application/json"
        headers["request-id"] = str(uuid4())
        headers["ucp-agent"] = f'profile="{self.agent_profile_url}"'
        serialized = None if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if serialized is not None:
            headers["content-type"] = "application/json"
        key = (idempotency_key or str(uuid4())) if mutates else None
        if key:
            headers["idempotency-key"] = key
        target = self.endpoint + template.replace("{id}", quote(id or "", safe=""))
        return PreparedRequest(operation, method, target, serialized, MappingProxyType(dict(headers)), key)

    async def send(self, request: PreparedRequest) -> Result:
        target = httpx.URL(request.url)
        if not str(target).startswith(self.endpoint + "/") or _origin(target) != _origin(httpx.URL(self.endpoint)):
            raise UcpError("Request belongs to a different endpoint", request)
        headers = httpx.Headers(request.headers)
        if self._signer:
            signed = self._signer(request)
            if inspect.isawaitable(signed):
                signed = await signed
            headers.update(signed)
        try:
            response = await self._http.request(request.method, request.url, content=request.body.encode("utf-8") if request.body is not None else None, headers=headers, follow_redirects=False, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise UcpError("Request failed; retain this prepared request for a deliberate retry", request) from error
        try:
            data = response.json()
        except ValueError as error:
            raise UcpError("Response did not contain JSON", request, response.status_code) from error
        if not response.is_success:
            raise UcpError(f"UCP request returned HTTP {response.status_code}", request, response.status_code, data)
        if not isinstance(data, dict) or not isinstance(data.get("ucp"), dict) or data["ucp"].get("version") != UCP_VERSION:
            raise UcpError("Response has an unexpected UCP envelope or version", request, response.status_code, data)
        return Result(data, request, response.status_code)

    async def request(self, operation: str, body: dict[str, Any] | None = None, **options: Any) -> Result:
        return await self.send(self.prepare(operation, body, **options))

    async def search_catalog(self, query: dict[str, Any]) -> Result: return await self.request("search_catalog", query)
    async def lookup_catalog(self, query: dict[str, Any]) -> Result: return await self.request("lookup_catalog", query)
    async def create_cart(self, payload: dict[str, Any], **options: Any) -> Result: return await self.request("create_cart", payload, **options)
    async def get_cart(self, id: str) -> Result: return await self.request("get_cart", id=id)
    async def update_cart(self, id: str, payload: dict[str, Any], **options: Any) -> Result: return await self.request("update_cart", payload, id=id, **options)
    async def cancel_cart(self, id: str, payload: dict[str, Any] | None = None, **options: Any) -> Result: return await self.request("cancel_cart", payload or {}, id=id, **options)
    async def create_checkout(self, payload: dict[str, Any], **options: Any) -> Result: return await self.request("create_checkout", payload, **options)
    async def get_checkout(self, id: str) -> Result: return await self.request("get_checkout", id=id)
    async def update_checkout(self, id: str, payload: dict[str, Any], **options: Any) -> Result: return await self.request("update_checkout", payload, id=id, **options)
    async def complete_checkout(self, id: str, payload: dict[str, Any], **options: Any) -> Result: return await self.request("complete_checkout", payload, id=id, **options)
    async def cancel_checkout(self, id: str, payload: dict[str, Any] | None = None, **options: Any) -> Result: return await self.request("cancel_checkout", payload or {}, id=id, **options)
    async def get_order(self, id: str) -> Result: return await self.request("get_order", id=id)

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> UcpClient: return self
    async def __aexit__(self, *args: Any) -> None: await self.aclose()
