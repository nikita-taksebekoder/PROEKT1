// Cloudflare Worker (ES Module)
// Скопируйте полностью этот файл в Cloudflare Workers (Script) как модуль (ES Module).
// Не вставляйте HTML — ошибка "Unexpected token '<'" означает, что в скрипт вставили HTML.

const YCLIENTS_API_BASE = 'https://api.yclients.com';
const DEFAULT_TTL = 300; // seconds cache

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
      // (debug branch removed in production)
    // path without leading/trailing slashes
    const path = url.pathname.replace(/^\/+|\/+$/g, '') || '/';

    try {
      if (request.method === 'OPTIONS') return handleOptions(request, env);

  if (path === 'health' && request.method === 'GET') return new Response('ok', { status: 200 });
  if (path === 'reviews' && request.method === 'GET') return await handleReviews(request, env);
  if (path === 'webhook' && request.method === 'POST') return await handleWebhook(request, env);
    // Admin import endpoint: protected by X-Admin-Key == env.ADMIN_KEY
    if (path === 'admin/import' && request.method === 'POST') return await handleAdminImport(request, env);
    if (path === 'admin/list-ids' && request.method === 'GET') return await handleAdminListIds(request, env);
    if (path === 'admin/sync' && request.method === 'POST') return await handleAdminSync(request, env);
  // public event endpoints for Tilda/frontend
  if (path === 'events' && request.method === 'GET') return await handleListEvents(request, env);
  if (path.startsWith('event/') && request.method === 'GET') return await handleGetEvent(request, env, path.slice('event/'.length));

      return new Response('Not found', { status: 404 });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 500,
        headers: jsonHeaders(env)
      });
    }
  }
};

function jsonHeaders(env = {}, request) {
  // Build safe JSON response headers including CORS. If ALLOWED_ORIGINS contains
  // multiple values, parse them and echo back the request Origin only if it's allowed.
  const headers = { 'Content-Type': 'application/json' };
  const allowedRaw = (env.ALLOWED_ORIGINS || '*').toString();
  // split on commas or whitespace
  const allowed = allowedRaw.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);

  const reqOrigin = request && request.headers ? (request.headers.get('Origin') || request.headers.get('origin')) : null;

  // Default: be restrictive. If ALLOWED_ORIGINS explicitly contains '*', allow any origin.
  // If request Origin is present and included in allowed list, echo it back.
  // If a single origin is configured, use it. Otherwise, when Origin is not allowed,
  // set to 'null' so browsers will block cross-origin requests.
  let originToSet = 'null';
  if (allowed.length === 0) {
    originToSet = '*'; // no config -> permissive for backwards compatibility
  } else if (allowed.includes('*')) {
    originToSet = '*';
  } else if (reqOrigin && allowed.includes(reqOrigin)) {
    originToSet = reqOrigin;
  } else if (allowed.length === 1) {
    // single configured origin (used when no Origin header present on request)
    originToSet = allowed[0];
  } else {
    // multiple configured origins but request Origin not allowed -> deny via 'null'
    originToSet = 'null';
  }

  // sanitize: header value must be a string without control chars
  originToSet = String(originToSet).replace(/[\r\n\0]/g, '');

  headers['Access-Control-Allow-Origin'] = originToSet;
  headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS';
  headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-YCLIENTS-Signature,X-API-Key';
  return headers;
}

function handleOptions(request, env) {
  const headers = Object.assign({}, jsonHeaders(env, request));
  headers['Access-Control-Max-Age'] = '600';
  // OPTIONS should not have a body
  return new Response(null, { status: 204, headers });
}

async function handleReviews(request, env) {
  const url = new URL(request.url);
  const qp = url.searchParams;
  const companyId = qp.get('company_id') || env.YCLIENTS_COMPANY_ID;
  if (!companyId) return new Response(JSON.stringify({ success: false, message: 'company_id is required' }), { status: 400, headers: jsonHeaders(env, request) });

  const staffParam = qp.get('staff_id') || qp.get('staff_ids') || '';
  const page = qp.get('page') || '1';
  const count = qp.get('count') || '20';
  const ttl = Number(qp.get('ttl') || DEFAULT_TTL);

  const partner = env.YCLIENTS_PARTNER_TOKEN;
  const user = env.YCLIENTS_USER_TOKEN; // optional
  if (!partner) return new Response(JSON.stringify({ success: false, message: 'YCLIENTS_PARTNER_TOKEN not configured' }), { status: 500, headers: jsonHeaders(env, request) });

  const target = new URL(`${YCLIENTS_API_BASE}/api/v1/comments/${encodeURIComponent(companyId)}/`);
  target.searchParams.set('page', page);
  target.searchParams.set('count', count);
  if (staffParam) {
    const list = staffParam.split(',').map(s => s.trim()).filter(Boolean);
    if (list.length === 1) target.searchParams.set('staff_id', list[0]);
    else list.forEach(id => target.searchParams.append('staff_id', id));
  }

  const cacheKey = `yclients:comments:${companyId}:s:${staffParam || 'all'}:p:${page}:c:${count}`;
  // caches.default expects a Request or absolute URL string. Use a synthetic absolute URL
  // derived from the cacheKey so it won't throw when used with cache.match/put.
  const cacheUrl = `https://workers-cache.local/${encodeURIComponent(cacheKey)}`;
  const cache = caches.default;

  try {
  const cached = await cache.match(cacheUrl);
    if (cached) {
      const cloned = cached.clone();
      const headers = new Headers(cloned.headers);
      headers.set('Access-Control-Allow-Origin', env.ALLOWED_ORIGINS || '*');
      headers.set('Access-Control-Allow-Methods', 'GET,OPTIONS');
      return new Response(await cloned.arrayBuffer(), { status: cloned.status, headers });
    }
  } catch (e) {
    // ignore cache read errors
    console.warn('Cache read error', e);
  }

  const headers = {
    'Accept': 'application/vnd.yclients.v2+json',
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${partner}` + (user ? `, User ${user}` : '')
  };

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  let yResp;
  try {
    yResp = await fetch(target.toString(), { method: 'GET', headers, signal: controller.signal });
  } catch (err) {
    clearTimeout(timeout);
    return new Response(JSON.stringify({ success: false, message: 'upstream fetch error', detail: err.message }), { status: 502, headers: jsonHeaders(env) });
  }
  clearTimeout(timeout);

  const body = await yResp.arrayBuffer();
  const respHeaders = new Headers(jsonHeaders(env, request));
  const status = yResp.status;

  if (status >= 200 && status < 300) {
    try {
      const responseForCache = new Response(body, { status, headers: respHeaders });
      const cacheRequest = new Request(cacheUrl);
      await cache.put(cacheRequest, responseForCache.clone());
      respHeaders.set('X-Cache-TTL', String(ttl));
    } catch (e) {
      console.warn('Cache put error', e);
    }
  }

  return new Response(body, { status, headers: respHeaders });
}

async function handleWebhook(request, env) {
  if (!env.YCLIENTS_WEBHOOK_SECRET) return new Response('Webhook secret not configured', { status: 500 });

  const raw = await request.arrayBuffer();
  const bodyText = new TextDecoder().decode(raw);

  const signatureHeader =
    request.headers.get('X-YCLIENTS-Signature') ||
    request.headers.get('x-yclients-signature') ||
    request.headers.get('x-signature') ||
    request.headers.get('x-hub-signature');

  if (!signatureHeader) return new Response('Missing signature header', { status: 400, headers: jsonHeaders(env, request) });

  const ok = await verifyHmacSHA256(bodyText, env.YCLIENTS_WEBHOOK_SECRET, signatureHeader);
  if (!ok) return new Response('Invalid signature', { status: 401, headers: jsonHeaders(env, request) });

  // ACK quickly; in production enqueue processing in Durable Object/KV/Queue
  // Persist raw event to KV (if bound) and enqueue to Durable Object (if bound)
  const eventId = `${Date.now()}-${Math.floor(Math.random()*1e9)}`;
  try {
    // store in KV namespace if available (binding name: WEBHOOK_KV)
    if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.put === 'function') {
      // store raw body under eventId
      await env.WEBHOOK_KV.put(eventId, bodyText);
    }
  } catch (e) {
    // don't fail the webhook on storage errors, just log
    console.warn('KV put error', e);
  }

  // update events version key to invalidate /events cache (best-effort)
  try {
    if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.put === 'function') {
      await env.WEBHOOK_KV.put('events:version', String(Date.now()));
    }
  } catch (e) {
    console.warn('version put failed', e);
  }

  try {
    // enqueue to Durable Object (binding name: WEBHOOK_DO)
    // If binding exists, obtain stub by name and POST the event
    if (env.WEBHOOK_DO && typeof env.WEBHOOK_DO.idFromName === 'function') {
      const id = env.WEBHOOK_DO.idFromName('default');
      const stub = env.WEBHOOK_DO.get(id);
      // send event id and body to DO for reliable processing
      await stub.fetch('/enqueue', { method: 'POST', headers: { 'X-Event-Id': eventId, 'Content-Type': 'application/json' }, body: bodyText });
    }
  } catch (e) {
    console.warn('Durable Object enqueue error', e);
  }

  return new Response(JSON.stringify({ ok: true, id: eventId }), { status: 200, headers: jsonHeaders(env, request) });
}

// Admin import endpoint for bulk/backfill without requiring HMAC signing.
// Protect with an admin key set in env.ADMIN_KEY. Accepts either a single event
// object or an array of event objects (each object should be the webhook body).
async function handleAdminImport(request, env) {
  const adminKey = env.ADMIN_KEY || env.YCLIENTS_ADMIN_KEY;
  const provided = request.headers.get('X-Admin-Key') || request.headers.get('x-admin-key');
  if (!adminKey || String(provided || '') !== String(adminKey)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }

  let payload;
  try {
    payload = await request.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: 'invalid_json', detail: e.message }), { status: 400, headers: jsonHeaders(env, request) });
  }

  const items = Array.isArray(payload) ? payload : [payload];
  const results = [];
  const forceOverwrite = String(request.headers.get('X-Admin-Force') || '').toLowerCase() === 'true';

  for (const item of items) {
    try {
      const bodyText = typeof item === 'string' ? item : JSON.stringify(item);
      const eventId = item && (item.id || (item.data && item.data.id)) ? String(item.id || item.data && item.data.id) : `${Date.now()}-${Math.floor(Math.random()*1e9)}`;

      // idempotency: skip if already exists unless X-Admin-Force header is set
      try {
        if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.get === 'function') {
          const existing = await env.WEBHOOK_KV.get(eventId);
          if (existing && !forceOverwrite) {
            // already present; skip writing to avoid duplicates
            results.push({ id: eventId, ok: true, skipped: true });
            continue;
          }
        }
      } catch (e) {
        console.warn('admin KV get failed', e);
        // fall through and attempt to write
      }

      // store in KV if available (put/overwrite)
      try {
        if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.put === 'function') {
          await env.WEBHOOK_KV.put(eventId, bodyText);
        }
      } catch (e) {
        console.warn('admin KV put failed', e);
      }

      // update events version key to invalidate cache
      try {
        if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.put === 'function') {
          await env.WEBHOOK_KV.put('events:version', String(Date.now()));
        }
      } catch (e) {
        console.warn('admin version put failed', e);
      }

      // enqueue to Durable Object if available
      try {
        if (env.WEBHOOK_DO && typeof env.WEBHOOK_DO.idFromName === 'function') {
          const id = env.WEBHOOK_DO.idFromName('default');
          const stub = env.WEBHOOK_DO.get(id);
          await stub.fetch('/enqueue', { method: 'POST', headers: { 'X-Event-Id': eventId, 'Content-Type': 'application/json' }, body: bodyText });
        }
      } catch (e) {
        console.warn('admin DO enqueue failed', e);
      }

      results.push({ id: eventId, ok: true });
    } catch (e) {
      results.push({ ok: false, error: e.message });
    }
  }

  return new Response(JSON.stringify({ imported: results.length, results }), { status: 200, headers: jsonHeaders(env, request) });
}

// Admin: list all keys in WEBHOOK_KV (paginated under the hood). Returns { keys: [id,...] }
async function handleAdminListIds(request, env) {
  const adminKey = env.ADMIN_KEY || env.YCLIENTS_ADMIN_KEY;
  const provided = request.headers.get('X-Admin-Key') || request.headers.get('x-admin-key');
  if (!adminKey || String(provided || '') !== String(adminKey)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }

  if (!env.WEBHOOK_KV || typeof env.WEBHOOK_KV.list !== 'function') {
    return new Response(JSON.stringify({ error: 'WEBHOOK_KV not bound' }), { status: 500, headers: jsonHeaders(env, request) });
  }

  try {
    const allKeys = [];
    let cursor = undefined;
    while (true) {
      const res = await env.WEBHOOK_KV.list({ limit: 1000, cursor });
      const names = res.keys.map(k => k.name || k).filter(n => n && n !== 'events:version');
      allKeys.push(...names);
      if (!res.cursor) break;
      cursor = res.cursor;
    }
    return new Response(JSON.stringify({ keys: allKeys }), { status: 200, headers: jsonHeaders(env, request) });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'list_failed', detail: e.message }), { status: 500, headers: jsonHeaders(env, request) });
  }
}

// Admin: sync/delete missing keys. Accepts { ids: [<id>...] } in JSON body and deletes KV keys not in the list.
// Protected by X-Admin-Key. Returns counts { deleted: N, kept: M }
async function handleAdminSync(request, env) {
  const adminKey = env.ADMIN_KEY || env.YCLIENTS_ADMIN_KEY;
  const provided = request.headers.get('X-Admin-Key') || request.headers.get('x-admin-key');
  if (!adminKey || String(provided || '') !== String(adminKey)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }

  if (!env.WEBHOOK_KV || typeof env.WEBHOOK_KV.list !== 'function' || typeof env.WEBHOOK_KV.delete !== 'function') {
    return new Response(JSON.stringify({ error: 'WEBHOOK_KV not bound or missing methods' }), { status: 500, headers: jsonHeaders(env, request) });
  }

  let payload;
  try {
    payload = await request.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: 'invalid_json', detail: e.message }), { status: 400, headers: jsonHeaders(env, request) });
  }

  const keepIds = Array.isArray(payload.ids) ? new Set(payload.ids.map(String)) : null;
  if (!keepIds) return new Response(JSON.stringify({ error: 'ids array required' }), { status: 400, headers: jsonHeaders(env, request) });

  try {
    let cursor = undefined;
    let deleted = 0;
    let kept = 0;
    while (true) {
      const res = await env.WEBHOOK_KV.list({ limit: 1000, cursor });
      const names = res.keys.map(k => k.name || k).filter(n => n && n !== 'events:version');
      for (const name of names) {
        if (!keepIds.has(String(name))) {
          try { await env.WEBHOOK_KV.delete(name); deleted++; } catch (e) { console.warn('delete failed', name, e); }
        } else {
          kept++;
        }
      }
      if (!res.cursor) break;
      cursor = res.cursor;
    }
    return new Response(JSON.stringify({ deleted, kept }), { status: 200, headers: jsonHeaders(env, request) });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'sync_failed', detail: e.message }), { status: 500, headers: jsonHeaders(env, request) });
  }
}

// Return a list of recent events (reads index from DO if available, else lists KV keys)
async function handleListEvents(request, env) {
  const url = new URL(request.url);
  // Simple API key protection: if YCLIENTS_READ_KEY is set, require X-API-Key header
  const reqApiKey = request.headers.get('X-API-Key') || request.headers.get('x-api-key');
  if (env.YCLIENTS_READ_KEY && String(reqApiKey || '') !== String(env.YCLIENTS_READ_KEY)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }
  const limit = Math.min(100, Number(url.searchParams.get('limit') || 20));
  let keys = [];
  // Caching: use caches.default with a cache key that includes a version stored in KV,
  // plus limit and api key (if any). Version is updated on webhook ingestion to
  // provide cheap invalidation without attempting to enumerate cached keys.
  const cacheTtl = Number(env.EVENTS_CACHE_TTL || 60); // seconds
  let version = 'v1';
  try {
    if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.get === 'function') {
      const ver = await env.WEBHOOK_KV.get('events:version');
      if (ver) version = String(ver);
    }
  } catch (e) {
    console.warn('version read failed', e);
  }
  const cacheKey = `events:ver:${version}:limit:${limit}:key:${reqApiKey || 'public'}`;
  const cacheUrl = `https://workers-cache.local/${encodeURIComponent(cacheKey)}`;
  const cache = caches.default;
  try {
    const cached = await cache.match(cacheUrl);
    if (cached) {
      const cloned = cached.clone();
      // ensure proper CORS headers
      const headers = new Headers(cloned.headers);
      headers.set('X-Cache', 'HIT');
      headers.set('X-Cache-TTL', String(cacheTtl));
      // surface current events version for debugging
      headers.set('X-Events-Version', version);
      return new Response(await cloned.arrayBuffer(), { status: cloned.status, headers });
    }
  } catch (e) {
    console.warn('Cache read error', e);
  }

  // Try Durable Object index first
  try {
    if (env.WEBHOOK_DO && typeof env.WEBHOOK_DO.idFromName === 'function') {
      const id = env.WEBHOOK_DO.idFromName('default');
      const stub = env.WEBHOOK_DO.get(id);
      const r = await stub.fetch('/', { method: 'GET' });
      if (r.ok) {
        const j = await r.json();
        if (Array.isArray(j.keys)) keys = j.keys;
      }
    }
  } catch (e) {
    console.warn('Failed to read DO index', e);
  }

  // Fallback: list keys from KV (may be unordered)
  // Use a paginated list to collect all keys (or up to available pages)
  // so that recently-written keys are not missed when the total number
  // of keys exceeds a single page.
  if (keys.length === 0 && env.WEBHOOK_KV && typeof env.WEBHOOK_KV.list === 'function') {
    try {
      const allKeys = [];
      let cursor = undefined;
      while (true) {
        const res = await env.WEBHOOK_KV.list({ limit: 1000, cursor });
        const names = (res.keys || []).map(k => k.name || k).filter(n => n && n !== 'events:version');
        allKeys.push(...names);
        if (!res.cursor) break;
        cursor = res.cursor;
      }
      keys = allKeys;
    } catch (e) {
      console.warn('KV list failed', e);
    }
  }

  // take last N keys
  // filter out internal keys (like events:version) and take last N
  const publicKeys = keys.filter(k => k && k !== 'events:version');
  const selected = publicKeys.slice(-limit).reverse();
  const items = [];
  for (const k of selected) {
    try {
      const v = await (env.WEBHOOK_KV ? env.WEBHOOK_KV.get(k) : null);
      const parsed = v ? (function () { try { return JSON.parse(v); } catch (e) { return v; } })() : null;
      const compact = parsed ? compactEvent(parsed) : null;
      items.push({ id: k, compact, body: parsed });
    } catch (e) {
      items.push({ id: k, error: 'read_failed' });
    }
  }

  const respBody = JSON.stringify({ items });
  const respHeaders = new Headers(jsonHeaders(env, request));
  respHeaders.set('X-Cache', 'MISS');
  respHeaders.set('X-Cache-TTL', String(cacheTtl));
  // expose the events version used for cache key / invalidation
  respHeaders.set('X-Events-Version', version);
  const resp = new Response(respBody, { status: 200, headers: respHeaders });

  // try to put into cache (best-effort)
  try {
    const cacheReq = new Request(cacheUrl);
    await cache.put(cacheReq, resp.clone());
  } catch (e) {
    console.warn('Cache put error', e);
  }

  return resp;
}

// Return a single event value from KV
async function handleGetEvent(request, env, id) {
  if (!id) return new Response(JSON.stringify({ error: 'id required' }), { status: 400, headers: jsonHeaders(env, request) });
  try {
    // API key protection
    const reqApiKey = request.headers.get('X-API-Key') || request.headers.get('x-api-key');
    if (env.YCLIENTS_READ_KEY && String(reqApiKey || '') !== String(env.YCLIENTS_READ_KEY)) {
      return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
    }
    if (!env.WEBHOOK_KV || typeof env.WEBHOOK_KV.get !== 'function') {
      return new Response(JSON.stringify({ error: 'WEBHOOK_KV not bound' }), { status: 500, headers: jsonHeaders(env, request) });
    }
    const v = await env.WEBHOOK_KV.get(id);
    if (!v) return new Response(JSON.stringify({ error: 'not found' }), { status: 404, headers: jsonHeaders(env, request) });
    // return parsed JSON body
    let parsed = null;
    try { parsed = JSON.parse(v); } catch (e) { parsed = v; }
    const compact = parsed ? compactEvent(parsed) : null;
    return new Response(JSON.stringify({ id, compact, body: parsed }), { status: 200, headers: jsonHeaders(env, request) });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'read_failed', detail: e.message }), { status: 500, headers: jsonHeaders(env, request) });
  }
}

// Durable Object: simple queue that stores events in its durable storage
// To bind: add a Durable Object binding named WEBHOOK_DO and class name WebhookQueue in wrangler.toml or Dashboard
export class WebhookQueue {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  async fetch(req) {
    const url = new URL(req.url || 'https://do/');
    if (req.method === 'POST' && url.pathname === '/enqueue') {
      const eventId = req.headers.get('X-Event-Id') || `${Date.now()}-${Math.floor(Math.random()*1e9)}`;
      const body = await req.text();
      // store event in durable object storage
      await this.state.storage.put(eventId, body);
      // optional: maintain a simple queue list (append key to index)
      // keep an index of recent keys
      try {
        let idx = (await this.state.storage.get('__index')) || [];
        if (!Array.isArray(idx)) idx = [];
        idx.push(eventId);
        // trim to last 1000
        if (idx.length > 1000) idx = idx.slice(-1000);
        await this.state.storage.put('__index', idx);
      } catch (e) {
        console.warn('index update failed', e);
      }
      return new Response(JSON.stringify({ enqueued: true, id: eventId }), { status: 200 });
    }

    if (req.method === 'GET') {
      // return list of stored keys (small helper for debugging)
      const idx = (await this.state.storage.get('__index')) || [];
      return new Response(JSON.stringify({ keys: idx }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    return new Response('Not found', { status: 404 });
  }
}

async function verifyHmacSHA256(message, secret, signatureHeader) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sigBuffer = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  const computedHex = Array.from(new Uint8Array(sigBuffer)).map(b => b.toString(16).padStart(2, '0')).join('');
  const normalized = signatureHeader.replace(/^sha256=|^sha1=|^hmac=| /gi, '');
  return computedHex === normalized;
}

// Produce a compact representation suitable for frontend display
function compactEvent(parsed) {
  // parsed is expected to be an object like { event: 'comment.created', data: { text, date, id, ... } }
  try {
    const ev = parsed || {};
    const data = ev.data || {};
    // include a few frequently-needed fields so the frontend (Tilda widget)
    // can render reviews without reading the full body. Keep backward
    // compatible names and fallbacks for common YCLIENTS shapes.
    return {
      event: ev.event || null,
      text: data.text || data.message || null,
      date: data.date || data.created_at || null,
      id: data.id || null,
      rating: (typeof data.rating !== 'undefined') ? data.rating : (data.rate || null),
      author_name: data.author_name || data.user_name || data.client_name || null,
      author_surname: data.author_surname || data.user_surname || null,
      master_id: (typeof data.master_id !== 'undefined') ? data.master_id : (data.staff_id || null),
      master_name: data.master_name || data.master || null
    };
  } catch (e) {
    return null;
  }
}

