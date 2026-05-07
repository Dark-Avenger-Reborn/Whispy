/**
 * Whispy Cloudflare Worker
 * ─────────────────────────────────────────────────────────────────────────
 * Sits in front of your origin Whispy server and provides:
 *   - Edge caching of package zips (immutable, 1-year TTL)
 *   - CORS headers for browser-based tools
 *   - Security headers
 *   - Request validation before hitting origin
 *   - Rate limiting via Cloudflare's built-in rules (set in dashboard)
 *
 * Deploy:
 *   1. npm install -g wrangler
 *   2. Set ORIGIN_URL in wrangler.toml
 *   3. wrangler deploy
 * ─────────────────────────────────────────────────────────────────────────
 */

const CACHEABLE_PATHS = ["/get_package", "/metadata/"];
const CACHE_TTL = 60 * 60 * 24 * 365; // 1 year for immutable package content

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // ── Security: block obviously bad requests ────────────────────────────
    const nameParam = url.searchParams.get("name") || "";
    if (nameParam && !/^[A-Za-z0-9_.\-]+$/.test(nameParam)) {
      return new Response(JSON.stringify({ error: "Invalid package name" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // ── CORS preflight ────────────────────────────────────────────────────
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    // ── Health / stats: pass through directly, no cache ──────────────────
    if (url.pathname === "/health" || url.pathname === "/stats") {
      const originResp = await fetch(buildOriginUrl(url, env), {
        headers: forwardHeaders(request),
      });
      return addSecurityHeaders(originResp);
    }

    // ── Cacheable routes ──────────────────────────────────────────────────
    const shouldCache = CACHEABLE_PATHS.some((p) => url.pathname.startsWith(p));

    if (shouldCache) {
      const cache = caches.default;
      const cacheKey = new Request(url.toString(), request);

      // Try cache first
      let cached = await cache.match(cacheKey);
      if (cached) {
        const resp = new Response(cached.body, cached);
        resp.headers.set("X-Whispy-Cache", "HIT");
        return addSecurityHeaders(resp);
      }

      // Cache miss — fetch from origin
      const originUrl = buildOriginUrl(url, env);
      const originResp = await fetch(originUrl, {
        headers: forwardHeaders(request),
      });

      if (!originResp.ok) {
        return addSecurityHeaders(originResp);
      }

      // Clone and cache for /get_package (package zips are immutable by version)
      const isPackageZip = url.pathname === "/get_package" && url.searchParams.get("version");
      if (isPackageZip && originResp.status === 200) {
        const respToCache = new Response(originResp.body, {
          status: originResp.status,
          headers: {
            ...Object.fromEntries(originResp.headers),
            "Cache-Control": `public, max-age=${CACHE_TTL}, immutable`,
            "X-Whispy-Cache": "MISS",
          },
        });
        ctx.waitUntil(cache.put(cacheKey, respToCache.clone()));
        return addSecurityHeaders(respToCache);
      }

      const resp = new Response(originResp.body, originResp);
      resp.headers.set("X-Whispy-Cache", "PASS");
      return addSecurityHeaders(resp);
    }

    // ── Default: proxy to origin ──────────────────────────────────────────
    const originResp = await fetch(buildOriginUrl(url, env), {
      headers: forwardHeaders(request),
    });
    return addSecurityHeaders(originResp);
  },
};

function buildOriginUrl(url, env) {
  const origin = env.ORIGIN_URL || "http://localhost:8000";
  return `${origin}${url.pathname}${url.search}`;
}

function forwardHeaders(request) {
  return {
    "User-Agent": request.headers.get("User-Agent") || "Whispy-Worker/1.0",
    "CF-Connecting-IP": request.headers.get("CF-Connecting-IP") || "",
    Accept: request.headers.get("Accept") || "*/*",
  };
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
  };
}

function addSecurityHeaders(response) {
  const resp = new Response(response.body, response);
  resp.headers.set("X-Content-Type-Options", "nosniff");
  resp.headers.set("X-Frame-Options", "DENY");
  resp.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  resp.headers.set(
    "Content-Security-Policy",
    "default-src 'none'; frame-ancestors 'none'"
  );
  // CORS
  resp.headers.set("Access-Control-Allow-Origin", "*");
  return resp;
}
