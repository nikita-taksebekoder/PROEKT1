// Cloudflare Worker (ES Module)
// Скопируйте полностью этот файл в Cloudflare Workers (Script) как модуль (ES Module).
// Не вставляйте HTML — ошибка "Unexpected token '<'" означает, что в скрипт вставили HTML.

const YCLIENTS_API_BASE = 'https://api.yclients.com';
const DEFAULT_TTL = 300; // seconds cache
// Dev fallbacks (only used if env vars are missing). Remove in production.
const DEV_PARTNER_FALLBACK = '7tcamp5dnn4ra74j5e29';
const DEV_USER_FALLBACK = '291d14e9b84cbd1e2faf8e3d0d63f29b';

// Known staff mapping for master_id -> name
const STAFF_MAP = {
  3269178: 'Роман Лунгу',
  2748512: 'Денис Храмов'
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/+|\/+$/g, '') || '/';
    try {
      if (request.method === 'OPTIONS') return handleOptions(request, env);
      if (path === 'health' && request.method === 'GET') return new Response('ok', { status: 200 });
      if (path === 'reviews' && request.method === 'GET') return await handleReviews(request, env);
  if (path === 'trainers' && request.method === 'GET') return await handleTrainers(request, env);
      if (path === 'webhook' && request.method === 'POST') return await handleWebhook(request, env);
      if (path === 'admin/import' && request.method === 'POST') return await handleAdminImport(request, env);
      if (path === 'admin/list-ids' && request.method === 'GET') return await handleAdminListIds(request, env);
      if (path === 'admin/enrich' && request.method === 'POST') return await handleAdminEnrich(request, env);
  if (path === 'admin/backfill' && request.method === 'POST') return await handleAdminBackfill(request, env);
      if (path === 'events' && request.method === 'GET') return await handleListEvents(request, env);
      if (path.startsWith('event/') && request.method === 'GET') return await handleGetEvent(request, env, path.slice('event/'.length));
      return new Response('Not found', { status: 404 });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: jsonHeaders(env) });
    }
  }
};

function jsonHeaders(env = {}, request) {
  const headers = { 'Content-Type': 'application/json' };
  headers['Access-Control-Allow-Origin'] = '*';
  headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS';
  headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization,X-YCLIENTS-Signature,X-API-Key';
  return headers;
}

function handleOptions(request, env) {
  // Return CORS preflight response
  const headers = Object.assign({}, jsonHeaders(env, request));
  headers['Access-Control-Max-Age'] = '600';
  return new Response(null, { status: 204, headers });
}

async function handleReviews(request, env) {
  try {
    const url = new URL(request.url);
    const qp = url.searchParams;
    const companyId = qp.get('company_id') || env.YCLIENTS_COMPANY_ID;
    if (!companyId) return new Response(JSON.stringify({ success: false, message: 'company_id is required' }), { status: 400, headers: jsonHeaders(env, request) });

    // Optional API key guard to mirror /events (only if configured)
    const reqApiKey = request.headers.get('X-API-Key') || request.headers.get('x-api-key');
    if (env.YCLIENTS_READ_KEY && String(reqApiKey || '') !== String(env.YCLIENTS_READ_KEY)) {
      return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
    }

    const staffParam = qp.get('staff_id') || qp.get('staff_ids') || '';
    const page = qp.get('page') || '1';
    const count = qp.get('count') || '20';
    const ttl = Number(qp.get('ttl') || DEFAULT_TTL);

  const partner = env.YCLIENTS_PARTNER_TOKEN || env.YCLIENTS_PARTNER || env.YCLIENTS_API_KEY || DEV_PARTNER_FALLBACK;
  const user = env.YCLIENTS_USER_TOKEN || env.YCLIENTS_AUTHORIZATION || env.YCLIENTS_USER || DEV_USER_FALLBACK; // optional
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
    const cacheUrl = `https://workers-cache.local/${encodeURIComponent(cacheKey)}`;
    const cache = caches.default;

    try {
      const cached = await cache.match(cacheUrl);
      if (cached) {
        const cloned = cached.clone();
        const headers = new Headers(cloned.headers);
        headers.set('Access-Control-Allow-Origin', env.ALLOWED_ORIGINS || '*');
        headers.set('Access-Control-Allow-Methods', 'GET,OPTIONS');
        headers.set('X-Cache', 'HIT');
        headers.set('Cache-Control', `public, max-age=${ttl}`);
        return new Response(await cloned.arrayBuffer(), { status: cloned.status, headers });
      }
    } catch (e) {
      // cache read failure is non-fatal
    }

    const upstreamHeaders = {
      'Accept': 'application/vnd.yclients.v2+json',
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${partner}` + (user ? `, User ${user}` : '')
    };

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    let yResp;
    try {
      yResp = await fetch(target.toString(), { method: 'GET', headers: upstreamHeaders, signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }

    const upstreamText = await yResp.text();
    const respHeaders = new Headers(jsonHeaders(env, request));
    const status = yResp.status;

    if (status >= 200 && status < 300) {
      let parsed = null;
      try { parsed = JSON.parse(upstreamText); } catch (_) { parsed = null; }
      let dataArr = [];
      let totalGuess = 0;
      let meta = {};
      if (parsed && Array.isArray(parsed.data)) { dataArr = parsed.data; meta = parsed.meta || {}; }
      else if (Array.isArray(parsed)) { dataArr = parsed; }
      else if (parsed && Array.isArray(parsed.comments)) { dataArr = parsed.comments; }
      totalGuess = Number((meta && (meta.total || meta.count || meta.items_total)) || (parsed && (parsed.total || parsed.count)) || 0) || dataArr.length;
      const pageNum = Number(page);
      const countNum = Number(count);

      const items = dataArr.map(d => {
        const compact = {
          event: 'api.comments',
          text: (d.text || '').trim(),
          date: d.date || null,
          id: d.id || null,
          rating: (typeof d.rating !== 'undefined') ? d.rating : null,
          author_name: d.user_name || null,
          author_surname: null,
          master_id: (typeof d.master_id !== 'undefined') ? d.master_id : null,
          master_name: (typeof d.master_id !== 'undefined' && d.master_id != null) ? (STAFF_MAP[d.master_id] || null) : null
        };
        let ts = null;
        try { ts = compact.date ? Date.parse(compact.date) : null; if (!Number.isFinite(ts)) ts = null; } catch (_) { ts = null; }
        return { id: String(d.id || ''), ts, compact, body: { event: 'api.comments', data: d } };
      });

      const outJson = JSON.stringify({ items, total: totalGuess, page: pageNum, limit: countNum });
      respHeaders.set('X-Cache-TTL', String(ttl));
      respHeaders.set('Cache-Control', `public, max-age=${ttl}`);
      respHeaders.set('X-Cache', 'MISS');

      try {
        const responseForCache = new Response(outJson, { status: 200, headers: respHeaders });
        const cacheRequest = new Request(cacheUrl);
        await cache.put(cacheRequest, responseForCache.clone());
      } catch (_) {
        // ignore cache write failure
      }
      return new Response(outJson, { status: 200, headers: respHeaders });
    }

    // pass through upstream errors
    return new Response(upstreamText, { status, headers: respHeaders });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'reviews_failed', detail: e && e.message ? e.message : String(e) }), { status: 500, headers: jsonHeaders(env, request) });
  }
}


async function handleWebhook(request, env) {
  if (!env.YCLIENTS_WEBHOOK_SECRET) return new Response('Webhook secret not configured', { status: 500 });

  const raw = await request.arrayBuffer();
  let bodyText = new TextDecoder().decode(raw);

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
  // Prefer a stable key when the payload contains a source id (to avoid duplicates
  // created by imports vs webhooks). Fall back to a timestamp-random id.
  let eventId;
  let parsedBody = null;
  try { parsedBody = JSON.parse(bodyText); } catch (e) { parsedBody = null; }
  console.log('Incoming webhook body:', parsedBody); // Log full incoming data from Yclients

  if (!parsedBody || !parsedBody.data) return new Response(JSON.stringify({ ok: true, skipped: 'no data' }), { status: 200, headers: jsonHeaders(env, request) });

  // Enrichment: fetch full comment data from Yclients API if missing client/staff/rating
  const compact = compactEvent(parsedBody);
  if (compact && compact.text && (!compact.author_name || !compact.master_name || compact.rating === null)) {
    try {
      const partnerToken = env.YCLIENTS_PARTNER_TOKEN || '7tcamp5dnn4ra74j5e29'; // temp for test
      const authToken = env.YCLIENTS_AUTHORIZATION || '291d14e9b84cbd1e2faf8e3d0d63f29b'; // temp for test
      const companyId = env.YCLIENTS_COMPANY_ID || '453962'; // temp for test
      if (partnerToken && authToken && companyId && parsedBody.data.id) {
        // Enrich with available data
        if (parsedBody.data.user_name) {
          parsedBody.data.client = { name: parsedBody.data.user_name };
        }
        if (parsedBody.data.master_id) {
          const staffName = STAFF_MAP[parsedBody.data.master_id] || 'Trainer ' + parsedBody.data.master_id;
          parsedBody.data.staff = { name: staffName };
        }
        // Update bodyText for storage
        bodyText = JSON.stringify(parsedBody);
      }
    } catch (e) {
      console.warn('Enrichment error:', e);
    }
  }
  try {
    if (parsedBody && parsedBody.data) {
      const srcId = parsedBody.data.id || parsedBody.data.source_id || parsedBody.data.sourceId || parsedBody.data.client_id;
      if (srcId) {
        eventId = `yclients:${String(srcId)}`;
      }
    }
  } catch (e) {
    // ignore parsing errors
  }
  if (!eventId) eventId = `${Date.now()}-${Math.floor(Math.random()*1e9)}`;

  // Check if review is not empty and has more than 2 words before storing
  const compactCheck = compactEvent(parsedBody);
  if (!compactCheck || !compactCheck.text) {
    return new Response(JSON.stringify({ ok: true, id: eventId, skipped: 'empty review' }), { status: 200, headers: jsonHeaders(env, request) });
  }
  
  // Filter out reviews with 2 or fewer words
  const words = compactCheck.text.split(/\s+/).filter(w => w.length > 0);
  if (words.length <= 2) {
    return new Response(JSON.stringify({ ok: true, id: eventId, skipped: 'too short review' }), { status: 200, headers: jsonHeaders(env, request) });
  }

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

// Admin: enrich existing reviews with full data from Yclients API
async function handleAdminEnrich(request, env) {
  const adminKey = env.ADMIN_KEY || env.YCLIENTS_ADMIN_KEY || 'secure_key'; // temp for test
  const provided = request.headers.get('X-Admin-Key') || request.headers.get('x-admin-key');
  if (!adminKey || String(provided || '') !== String(adminKey)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }

  if (!env.WEBHOOK_KV || typeof env.WEBHOOK_KV.list !== 'function' || typeof env.WEBHOOK_KV.get !== 'function' || typeof env.WEBHOOK_KV.put !== 'function') {
    return new Response(JSON.stringify({ error: 'WEBHOOK_KV not bound or missing methods' }), { status: 500, headers: jsonHeaders(env, request) });
  }

  const partnerToken = env.YCLIENTS_PARTNER_TOKEN || '7tcamp5dnn4ra74j5e29';
  const authToken = env.YCLIENTS_AUTHORIZATION || '291d14e9b84cbd1e2faf8e3d0d63f29b';
  const companyId = env.YCLIENTS_COMPANY_ID || '453962';
  if (!partnerToken || !authToken || !companyId) {
    return new Response(JSON.stringify({ error: 'Yclients API keys not configured' }), { status: 500, headers: jsonHeaders(env, request) });
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

    let enriched = 0;
    let skipped = 0;
    let errors = 0;

    for (const key of allKeys) {
      try {
        const v = await env.WEBHOOK_KV.get(key);
        if (!v) continue;
        const parsed = JSON.parse(v);
        if (!parsed || !parsed.data || !parsed.data.id) continue;

        const compact = compactEvent(parsed);
        if (!compact || !compact.text) continue;

        // Check if already enriched
        if (compact.author_name && compact.master_name && compact.rating !== null) {
          skipped++;
          continue;
        }

        // Enrich with available data
        if (parsed.data.user_name) {
          parsed.data.client = { name: parsed.data.user_name };
        }
        if (parsed.data.master_id) {
          const staffName = STAFF_MAP[parsed.data.master_id] || 'Trainer ' + parsed.data.master_id;
          parsed.data.staff = { name: staffName };
        }
        const updatedBody = JSON.stringify(parsed);
        await env.WEBHOOK_KV.put(key, updatedBody);
        enriched++;
      } catch (e) {
        console.warn(`Error enriching ${key}:`, e);
        errors++;
      }
    }

    // Update version to invalidate cache
    await env.WEBHOOK_KV.put('events:version', String(Date.now()));

    return new Response(JSON.stringify({ enriched, skipped, errors, total: allKeys.length }), { status: 200, headers: jsonHeaders(env, request) });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'enrich_failed', detail: e.message }), { status: 500, headers: jsonHeaders(env, request) });
  }
}
// Admin: fetch all comments from Yclients and store into WEBHOOK_KV (backfill)
async function handleAdminBackfill(request, env) {
  const adminKey = env.ADMIN_KEY || env.YCLIENTS_ADMIN_KEY;
  const provided = request.headers.get('X-Admin-Key') || request.headers.get('x-admin-key');
  if (!adminKey || String(provided || '') !== String(adminKey)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }

  if (!env.WEBHOOK_KV || typeof env.WEBHOOK_KV.put !== 'function') {
    return new Response(JSON.stringify({ error: 'WEBHOOK_KV not bound' }), { status: 500, headers: jsonHeaders(env, request) });
  }

  const partner = env.YCLIENTS_PARTNER_TOKEN || DEV_PARTNER_FALLBACK;
  const user = env.YCLIENTS_USER_TOKEN || DEV_USER_FALLBACK;
  const companyId = env.YCLIENTS_COMPANY_ID || '453962';
  if (!partner || !companyId) return new Response(JSON.stringify({ error: 'YCLIENTS tokens missing' }), { status: 500, headers: jsonHeaders(env, request) });

  const perPage = 100;
  let page = 1;
  let totalImported = 0;
  let errors = 0;
  try {
    while (true) {
      const target = new URL(`${YCLIENTS_API_BASE}/api/v1/comments/${encodeURIComponent(companyId)}/`);
      target.searchParams.set('page', String(page));
      target.searchParams.set('count', String(perPage));
      const upstreamHeaders = {
        'Accept': 'application/vnd.yclients.v2+json',
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${partner}` + (user ? `, User ${user}` : '')
      };
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 20000);
      let yResp;
      try { yResp = await fetch(target.toString(), { method: 'GET', headers: upstreamHeaders, signal: controller.signal }); }
      finally { clearTimeout(timeout); }

      if (!yResp.ok) {
        const txt = await yResp.text().catch(()=>'');
        return new Response(JSON.stringify({ error: 'upstream_error', status: yResp.status, detail: txt }), { status: 502, headers: jsonHeaders(env, request) });
      }
      const txt = await yResp.text();
      let parsed = null;
      try { parsed = JSON.parse(txt); } catch (_) { parsed = null; }
      let items = [];
      if (parsed && Array.isArray(parsed.data)) items = parsed.data;
      else if (Array.isArray(parsed)) items = parsed;
      else if (parsed && Array.isArray(parsed.comments)) items = parsed.comments;

      if (!items || items.length === 0) break;

      for (const d of items) {
        try {
          const id = d.id || (d && d.comment_id) || null;
          if (!id) continue;
          const key = `yclients:${String(id)}`;
          const body = JSON.stringify({ event: 'api.comments', data: d });
          await env.WEBHOOK_KV.put(key, body);
          totalImported++;
        } catch (e) { console.warn('put failed', e); errors++; }
      }

      // if less than perPage returned, finish
      if (items.length < perPage) break;
      page++;
    }

    // bump version
    try { await env.WEBHOOK_KV.put('events:version', String(Date.now())); } catch (e) { console.warn('version put failed', e); }

    return new Response(JSON.stringify({ imported: totalImported, errors }), { status: 200, headers: jsonHeaders(env, request) });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'backfill_failed', detail: e && e.message ? e.message : String(e) }), { status: 500, headers: jsonHeaders(env, request) });
  }
}
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
  const page = Math.max(1, Number(url.searchParams.get('page') || 1));
  let keys = [];
  // Caching: use caches.default with a cache key that includes a version stored in KV,
  // plus limit and api key (if any). Version is updated on webhook ingestion to
  // provide cheap invalidation without attempting to enumerate cached keys.
  const cacheTtl = Number(env.EVENTS_CACHE_TTL || 300); // seconds
  let version = 'v1';
  try {
    if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.get === 'function') {
      const ver = await env.WEBHOOK_KV.get('events:version');
      if (ver) version = String(ver);
    }
  } catch (e) {
    console.warn('version read failed', e);
  }
  const cacheKey = `events:ver:${version}:limit:${limit}:page:${page}:key:${reqApiKey || 'public'}`;
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
      headers.set('Cache-Control', `public, max-age=${cacheTtl}`);
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

  // take last N keys for the page
  // filter out internal keys (like events:version)
  const publicKeys = keys.filter(k => k && k !== 'events:version');
  // Collect all valid items
  const allItems = [];
  for (const k of publicKeys) {
    try {
      const v = await (env.WEBHOOK_KV ? env.WEBHOOK_KV.get(k) : null);
      const parsed = v ? JSON.parse(v) : null;
      const rawCompact = parsed ? compactEvent(parsed) : null;
      // Normalize/sanitize compact into a stable shape used by /reviews
      const compactNorm = (function(rc, raw) {
        const data = raw && raw.data ? raw.data : {};
        const text = (rc && rc.text) ? String(rc.text) : (data.text || data.message || '') ;
        if (!text || !String(text).trim()) return null; // skip empty

        const dateVal = (rc && rc.date) ? rc.date : (data.date || data.created_at || null);
        const idVal = (rc && rc.id) ? rc.id : (data.id || null);
        const ratingRaw = (rc && typeof rc.rating !== 'undefined') ? rc.rating : (data.rating || data.rate || data.score || data.stars || data.mark || data.value || null);
        const rating = (ratingRaw === null || typeof ratingRaw === 'undefined' || ratingRaw === '') ? null : (Number(ratingRaw) || 0);
        const author = (rc && rc.author_name) ? rc.author_name : (data.client && (data.client.name || data.client.full_name)) || data.user_name || data.client_name || data.author || null;
        const authorSurname = (rc && rc.author_surname) ? rc.author_surname : (data.author_surname || data.user_surname || null);
        const masterIdRaw = (rc && typeof rc.master_id !== 'undefined' && rc.master_id !== null) ? rc.master_id : (data.master_id || data.staff_id || (data.staff && data.staff.id) || null);
        const master_id = (masterIdRaw === null || typeof masterIdRaw === 'undefined' || masterIdRaw === '') ? null : (Number(masterIdRaw) || masterIdRaw);
        let master_name = (rc && rc.master_name) ? rc.master_name : (data.staff && (data.staff.name || data.staff.full_name)) || data.master_name || data.master || null;
        if (!master_name && master_id && STAFF_MAP && STAFF_MAP[String(master_id)]) master_name = STAFF_MAP[String(master_id)];

        return {
          event: rc && rc.event ? rc.event : (raw && raw.event ? raw.event : 'api.comments'),
          text: String(text).trim(),
          date: dateVal || null,
          id: idVal || null,
          rating: (rating === 0 && (ratingRaw === null || ratingRaw === '')) ? null : rating,
          author_name: author || null,
          author_surname: authorSurname || null,
          master_id: master_id || null,
          master_name: master_name || null
        };
      })(rawCompact, parsed);

      if (compactNorm) {
        // compute comparable timestamp for stable sorting (newest first)
        let d = null;
        try {
          const rawDate = compactNorm.date || (parsed && parsed.data && (parsed.data.date || parsed.data.created_at));
          d = rawDate ? Date.parse(rawDate) : null;
        } catch (_) { d = null; }
        if (!Number.isFinite(d)) d = null;
        allItems.push({ id: k, ts: d, compact: compactNorm, body: parsed });
      }
    } catch (e) {
      // skip
    }
  }
  // Sort by ts desc, fallback to numeric id desc if possible, else lexicographic desc
  allItems.sort((a, b) => {
    const at = a.ts ?? -Infinity; const bt = b.ts ?? -Infinity;
    if (at !== bt) return bt - at;
    const an = Number(a.compact && a.compact.id);
    const bn = Number(b.compact && b.compact.id);
    const aIsNum = Number.isFinite(an);
    const bIsNum = Number.isFinite(bn);
    if (aIsNum && bIsNum && an !== bn) return bn - an;
    return String(b.id).localeCompare(String(a.id));
  });

  // Apply server-side short-review filter to guarantee page fill behavior
  const filteredItems = allItems.filter(it => {
    const text = (it.compact && it.compact.text) ? String(it.compact.text).trim() : '';
    if (!text) return false;
    const words = text.split(/\s+/).filter(w => w.length > 0);
    return words.length > 2; // keep only reviews with more than 2 words
  });

  const total = filteredItems.length;
  const start = (page - 1) * limit;
  const end = start + limit;
  const items = filteredItems.slice(start, end);

  const respBody = JSON.stringify({ items, total, page, limit });
  const respHeaders = new Headers(jsonHeaders(env, request));
  respHeaders.set('X-Cache', 'MISS');
  respHeaders.set('X-Cache-TTL', String(cacheTtl));
  respHeaders.set('Cache-Control', `public, max-age=${cacheTtl}`);
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

// Return a list of trainers (master_id and name) discovered in KV + STAFF_MAP fallback
async function handleTrainers(request, env) {
  // API key protection similar to events
  const reqApiKey = request.headers.get('X-API-Key') || request.headers.get('x-api-key');
  if (env.YCLIENTS_READ_KEY && String(reqApiKey || '') !== String(env.YCLIENTS_READ_KEY)) {
    return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: jsonHeaders(env, request) });
  }

  const trainers = new Map(); // master_id -> { id, name, count }

  // Seed with STAFF_MAP known entries
  try {
    Object.keys(STAFF_MAP).forEach(k => {
      const id = Number(k);
      if (!Number.isFinite(id)) return;
      trainers.set(String(id), { id: String(id), name: STAFF_MAP[id], count: 0 });
    });
  } catch (e) {
    // ignore
  }

  // If WEBHOOK_KV bound, scan all keys and collect master_id/master_name from stored events
  try {
    if (env.WEBHOOK_KV && typeof env.WEBHOOK_KV.list === 'function' && typeof env.WEBHOOK_KV.get === 'function') {
      let cursor = undefined;
      while (true) {
        const res = await env.WEBHOOK_KV.list({ limit: 1000, cursor });
        const names = (res.keys || []).map(k => k.name || k).filter(n => n && n !== 'events:version');
        for (const name of names) {
          try {
            const v = await env.WEBHOOK_KV.get(name);
            if (!v) continue;
            const parsed = JSON.parse(v);
            const compact = parsed ? compactEvent(parsed) : null;
            let mid = null; let mname = null;
            if (compact && compact.master_id) mid = String(compact.master_id);
            if (compact && compact.master_name) mname = compact.master_name;
            if (!mid && parsed && parsed.data) {
              mid = parsed.data.master_id ? String(parsed.data.master_id) : (parsed.data.staff && parsed.data.staff.id ? String(parsed.data.staff.id) : null);
              mname = mname || (parsed.data.staff && (parsed.data.staff.name || parsed.data.staff.full_name)) || parsed.data.master_name || parsed.data.master || null;
            }
            if (mid) {
              const entry = trainers.get(mid) || { id: mid, name: mname || (STAFF_MAP[mid] || `Тренер ${mid}`), count: 0 };
              entry.count = (entry.count || 0) + 1;
              if (!entry.name && parsed && parsed.data && parsed.data.staff && parsed.data.staff.name) entry.name = parsed.data.staff.name;
              trainers.set(mid, entry);
            }
          } catch (e) {
            // skip parse errors
          }
        }
        if (!res.cursor) break;
        cursor = res.cursor;
      }
    }
  } catch (e) {
    console.warn('trainers collect failed', e);
  }

  // Convert map to array and sort by name (fallback to id)
  const out = Array.from(trainers.values()).map(t => ({ id: String(t.id), name: t.name || `Тренер ${t.id}`, count: t.count || 0 }));
  out.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));

  return new Response(JSON.stringify({ trainers: out }), { status: 200, headers: jsonHeaders(env, request) });
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

    if (req.method === 'GET' && url.pathname === '/') {
      const idx = (await this.state.storage.get('__index')) || [];
      const keys = Array.isArray(idx) ? idx : [];
      return new Response(JSON.stringify({ keys }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    return new Response('Not found', { status: 404 });
  }
}

function compactEvent(parsed) {
  // parsed is expected to be an object like { event: 'comment.created', data: { text, date, id, ... } }
  try {
    const ev = parsed || {};
    const data = ev.data || {};
    // include a few frequently-needed fields so the frontend (Tilda widget)
    // can render reviews without reading the full body. Keep backward
    // compatible names and fallbacks for common YCLIENTS shapes.
    const text = (data.text || data.message || '').trim();
    return {
      event: ev.event || null,
      text: text || null,
      date: data.date || data.created_at || null,
      id: data.id || null,
      rating: (typeof data.rating !== 'undefined') ? data.rating : (data.rate || data.score || data.stars || data.mark || data.value || data.grade || null),
      author_name: data.client ? (data.client.name || data.client.full_name) : (data.user_name || data.client_name || data.author || data.name || data.user || (data.user && data.user.name) || (data.user && data.user.full_name) || null),
      author_surname: data.author_surname || data.user_surname || null,
      master_id: (typeof data.master_id !== 'undefined') ? data.master_id : (data.staff_id || null),
      master_name: data.staff ? (data.staff.name || data.staff.full_name) : (data.master_name || data.master || data.staff_name || data.trainer_name || data.staff || (data.staff && data.staff.name) || (data.staff && data.staff.full_name) || data.trainer || (data.trainer && data.trainer.name) || (data.trainer && data.trainer.full_name) || null)
    };
  } catch (e) {
    return null;
  }
}

