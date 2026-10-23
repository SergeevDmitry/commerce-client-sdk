export const UCP_VERSION = '2026-08-25';
export type Json = Record<string, unknown>;
export type Profile = { ucp: { version: string; services?: Record<string, Binding[]>; capabilities: Record<string, Capability[]> } };
export type Capability = { version: string; extends?: string | string[]; [key: string]: unknown };
export type Binding = { version: string; transport: string; endpoint?: string; [key: string]: unknown };
export type PreparedRequest = Readonly<{ operation: Operation; method: string; url: string; body?: string; headers: Readonly<Record<string, string>>; idempotencyKey?: string }>;
export type Signer = (request: PreparedRequest) => Promise<Record<string, string>> | Record<string, string>;
export type Result<T = Json> = { data: T; request: PreparedRequest; status: number };
export class UcpError extends Error {
  constructor(message: string, public readonly request?: PreparedRequest, public readonly status?: number, public readonly data?: unknown, options?: ErrorOptions) { super(message, options); this.name = 'UcpError'; }
}
const operations = {
  create_checkout: ['POST', '/checkout-sessions', 'checkout', true],
  get_checkout: ['GET', '/checkout-sessions/{id}', 'checkout', false],
  update_checkout: ['PUT', '/checkout-sessions/{id}', 'checkout', true],
  complete_checkout: ['POST', '/checkout-sessions/{id}/complete', 'checkout', true],
  cancel_checkout: ['POST', '/checkout-sessions/{id}/cancel', 'checkout', true],
  create_cart: ['POST', '/carts', 'cart', true],
  get_cart: ['GET', '/carts/{id}', 'cart', false],
  update_cart: ['PUT', '/carts/{id}', 'cart', true],
  cancel_cart: ['POST', '/carts/{id}/cancel', 'cart', true],
  search_catalog: ['POST', '/catalog/search', 'catalog.search', false],
  lookup_catalog: ['POST', '/catalog/lookup', 'catalog.lookup', false],
  get_order: ['GET', '/orders/{id}', 'order', false],
} as const;
export type Operation = keyof typeof operations;
const capabilityName = (short: string) => `dev.ucp.shopping.${short}`;
const defaultCapabilities = ['checkout', 'cart', 'catalog.search', 'catalog.lookup', 'order'].map(capabilityName);
export type ClientOptions = {
  agentProfileUrl: string;
  supportedCapabilities?: readonly string[];
  headers?: Record<string, string>;
  signer?: Signer;
  fetch?: typeof fetch;
  timeoutMs?: number;
  allowedServiceOrigins?: string[];
  allowHttpForDevelopment?: boolean;
};
function object(value: unknown): value is Json { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function url(value: string, allowHttp = false): URL {
  const parsed = new URL(value);
  if (parsed.username || parsed.password || parsed.hash || (parsed.protocol !== 'https:' && !(allowHttp && parsed.protocol === 'http:'))) throw new UcpError('Expected an HTTPS URL without credentials or fragment');
  return parsed;
}
function profile(value: unknown): Profile {
  if (!object(value) || !object(value.ucp) || value.ucp.version !== UCP_VERSION || !object(value.ucp.capabilities)) throw new UcpError(`Expected a UCP ${UCP_VERSION} discovery profile`);
  for (const entries of Object.values(value.ucp.capabilities)) if (!Array.isArray(entries) || entries.some(entry => !object(entry) || typeof entry.version !== 'string')) throw new UcpError('Invalid capability declarations');
  return value as Profile;
}
/** Select only declared versions; discard extensions whose parent is unavailable. */
export function selectCapabilities(merchant: Profile, supported: readonly string[]): Record<string, Capability> {
  const selected: Record<string, Capability> = {};
  for (const name of supported) {
    const entry = merchant.ucp.capabilities[name]?.find(entry => entry.version === UCP_VERSION);
    if (entry) selected[name] = entry;
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const [name, entry] of Object.entries(selected)) {
      const parents = typeof entry.extends === 'string' ? [entry.extends] : entry.extends ?? [];
      if (!Array.isArray(parents) || parents.some(parent => typeof parent !== 'string' || !selected[parent])) { delete selected[name]; changed = true; }
    }
  }
  return selected;
}
export class UcpClient {
  readonly capabilities: Readonly<Record<string, Capability>>;
  readonly merchantProfile: Profile;
  readonly endpoint: string;
  private readonly options: ClientOptions;
  private constructor(merchant: Profile, endpoint: string, options: ClientOptions) {
    this.merchantProfile = merchant; this.endpoint = endpoint; this.options = options;
    this.capabilities = Object.freeze(selectCapabilities(merchant, options.supportedCapabilities ?? defaultCapabilities));
  }
  /** Discover the merchant's advertised REST endpoint; preserve any endpoint path prefix. */
  static async connect(merchantUrl: string, options: ClientOptions): Promise<UcpClient> {
    const merchant = url(merchantUrl, options.allowHttpForDevelopment);
    url(options.agentProfileUrl, options.allowHttpForDevelopment);
    if (options.timeoutMs !== undefined && (!Number.isFinite(options.timeoutMs) || options.timeoutMs <= 0)) throw new UcpError('timeoutMs must be positive');
    const fetcher = options.fetch ?? globalThis.fetch;
    const headers = new Headers(options.headers); headers.set('accept', 'application/json');
    let response: Response;
    try { response = await fetcher(new URL('/.well-known/ucp', merchant), { headers, redirect: 'manual', signal: AbortSignal.timeout(options.timeoutMs ?? 10000) }); }
    catch (cause) { throw new UcpError('Merchant discovery failed', undefined, undefined, undefined, { cause }); }
    if (response.status !== 200) throw new UcpError('Merchant discovery did not return HTTP 200', undefined, response.status);
    let decoded: unknown;
    try { decoded = await response.json(); } catch (cause) { throw new UcpError('Discovery did not return JSON', undefined, response.status, undefined, { cause }); }
    const discovered = profile(decoded);
    const bindings = discovered.ucp.services?.['dev.ucp.shopping'];
    if (!Array.isArray(bindings)) throw new UcpError('Merchant does not advertise a shopping service');
    const binding = bindings.find(entry => object(entry) && entry.transport === 'rest' && entry.version === UCP_VERSION);
    if (!binding || typeof binding.endpoint !== 'string') throw new UcpError(`Merchant does not advertise a UCP ${UCP_VERSION} REST endpoint`);
    const endpoint = url(binding.endpoint, options.allowHttpForDevelopment);
    if (endpoint.search) throw new UcpError('REST endpoint must not contain a query');
    const origins = new Set([merchant.origin, ...(options.allowedServiceOrigins ?? []).map(origin => url(origin, options.allowHttpForDevelopment).origin)]);
    if (!origins.has(endpoint.origin)) throw new UcpError('REST endpoint origin must be explicitly allowed');
    return new UcpClient(discovered, endpoint.href.replace(/\/$/, ''), { ...options, fetch: fetcher });
  }
  /** Serialize once. Keep this request to repeat an uncertain write with the same key. */
  prepare(operation: Operation, body?: Json, options: { id?: string; idempotencyKey?: string } = {}): PreparedRequest {
    if (!Object.hasOwn(operations, operation)) throw new UcpError(`Unknown operation: ${operation}`);
    const [method, template, capability, mutates] = operations[operation];
    if (!method) throw new UcpError(`Unknown operation: ${operation}`);
    if (!this.capabilities[capabilityName(capability)]) throw new UcpError(`Merchant and client do not share ${capabilityName(capability)}`);
    if (template.includes('{id}') && (!options.id || options.id === '.' || options.id === '..')) throw new UcpError('This operation requires an ID');
    if (method === 'GET' && body !== undefined) throw new UcpError('GET operations do not accept a body');
    if (body !== undefined && !object(body)) throw new UcpError('Operation body must be a JSON object');
    const headers = new Headers(this.options.headers);
    for (const name of ['signature', 'signature-input', 'content-digest', 'idempotency-key']) headers.delete(name);
    headers.set('accept', 'application/json'); headers.set('request-id', crypto.randomUUID());
    headers.set('ucp-agent', `profile="${new URL(this.options.agentProfileUrl).href}"`);
    const serialized = body === undefined ? undefined : JSON.stringify(body);
    if (serialized !== undefined) headers.set('content-type', 'application/json');
    const idempotencyKey = mutates ? options.idempotencyKey ?? crypto.randomUUID() : undefined;
    if (idempotencyKey) headers.set('idempotency-key', idempotencyKey);
    const target = this.endpoint + template.replace('{id}', encodeURIComponent(options.id ?? ''));
    return Object.freeze({ operation, method, url: target, body: serialized, headers: Object.freeze(Object.fromEntries(headers)), idempotencyKey });
  }
  async send<T = Json>(request: PreparedRequest): Promise<Result<T>> {
    const target = new URL(request.url);
    if (!target.href.startsWith(this.endpoint + '/') || target.origin !== new URL(this.endpoint).origin) throw new UcpError('Request belongs to a different endpoint', request);
    const headers = new Headers(request.headers);
    if (this.options.signer) for (const [name, value] of Object.entries(await this.options.signer(request))) headers.set(name, value);
    let response: Response;
    try { response = await this.options.fetch!(request.url, { method: request.method, body: request.body, headers, redirect: 'manual', signal: AbortSignal.timeout(this.options.timeoutMs ?? 10000) }); }
    catch (cause) { throw new UcpError('Request failed; retain this prepared request for a deliberate retry', request, undefined, undefined, { cause }); }
    let data: unknown;
    try { data = await response.json(); } catch (cause) { throw new UcpError('Response did not contain JSON', request, response.status, undefined, { cause }); }
    if (!response.ok) throw new UcpError(`UCP request returned HTTP ${response.status}`, request, response.status, data);
    if (!object(data) || !object(data.ucp) || data.ucp.version !== UCP_VERSION) throw new UcpError('Response has an unexpected UCP envelope or version', request, response.status, data);
    return { data: data as T, request, status: response.status };
  }
  request<T = Json>(operation: Operation, body?: Json, options?: { id?: string; idempotencyKey?: string }): Promise<Result<T>> { return this.send<T>(this.prepare(operation, body, options)); }
  searchCatalog(query: Json) { return this.request('search_catalog', query); }
  lookupCatalog(query: Json) { return this.request('lookup_catalog', query); }
  createCart(payload: Json, idempotencyKey?: string) { return this.request('create_cart', payload, { idempotencyKey }); }
  getCart(id: string) { return this.request('get_cart', undefined, { id }); }
  updateCart(id: string, payload: Json, idempotencyKey?: string) { return this.request('update_cart', payload, { id, idempotencyKey }); }
  cancelCart(id: string, payload: Json = {}, idempotencyKey?: string) { return this.request('cancel_cart', payload, { id, idempotencyKey }); }
  createCheckout(payload: Json, idempotencyKey?: string) { return this.request('create_checkout', payload, { idempotencyKey }); }
  getCheckout(id: string) { return this.request('get_checkout', undefined, { id }); }
  updateCheckout(id: string, payload: Json, idempotencyKey?: string) { return this.request('update_checkout', payload, { id, idempotencyKey }); }
  completeCheckout(id: string, payload: Json, idempotencyKey?: string) { return this.request('complete_checkout', payload, { id, idempotencyKey }); }
  cancelCheckout(id: string, payload: Json = {}, idempotencyKey?: string) { return this.request('cancel_checkout', payload, { id, idempotencyKey }); }
  getOrder(id: string) { return this.request('get_order', undefined, { id }); }
}
