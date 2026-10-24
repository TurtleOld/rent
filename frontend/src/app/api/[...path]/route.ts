import { NextRequest, NextResponse } from "next/server";
import { setAccessCookie, setRefreshCookie } from "@/lib/authCookies";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

// content-length/transfer-encoding: fetch recomputes them for the buffered body.
const SKIPPED_REQUEST_HEADERS = new Set(["host", "cookie", "content-length", "transfer-encoding"]);

type Tokens = { access: string; refresh?: string };

async function refreshTokens(refresh: string): Promise<Tokens | null> {
  const res = await fetch(`${BACKEND_URL}/api/auth/refresh/`, {
    method: "POST",
    // Without it Django's SECURE_SSL_REDIRECT answers 301 to https://backend.
    headers: { "Content-Type": "application/json", "X-Forwarded-Proto": "https" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) return null;
  return (await res.json()) as Tokens;
}

// Refresh tokens rotate and the old one is blacklisted, so parallel 401s must share one
// refresh call instead of racing (the loser would get 401 and log the user out).
// shortcut: per-process memory, fine for the single frontend container; with several
// replicas move this to Redis.
const REUSE_MS = 30_000;
const refreshes = new Map<string, { result: Promise<Tokens | null>; expires: number }>();

function refreshOnce(refresh: string): Promise<Tokens | null> {
  const now = Date.now();
  for (const [token, entry] of refreshes) {
    if (entry.expires < now) refreshes.delete(token);
  }
  const cached = refreshes.get(refresh);
  if (cached) return cached.result;

  const result = refreshTokens(refresh).catch(() => null);
  refreshes.set(refresh, { result, expires: now + REUSE_MS });
  // Do not cache failures: a network blip must not block the next attempt.
  void result.then((tokens) => {
    if (!tokens) refreshes.delete(refresh);
  });
  return result;
}

async function proxy(request: NextRequest, params: { path: string[] }): Promise<NextResponse> {
  const { path } = params;
  const search = request.nextUrl.search;
  const joined = path.join("/");
  const url = `${BACKEND_URL}/api/${joined}/${search}`;

  const forwardedHeaders = new Headers();
  request.headers.forEach((value, key) => {
    if (!SKIPPED_REQUEST_HEADERS.has(key.toLowerCase())) {
      forwardedHeaders.set(key, value);
    }
  });

  // Buffered (not streamed) so the request can be replayed after a token refresh.
  const body =
    request.method !== "GET" && request.method !== "HEAD" ? await request.arrayBuffer() : undefined;

  const send = (accessToken: string | undefined) => {
    const headers = new Headers(forwardedHeaders);
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    return fetch(url, { method: request.method, headers, body });
  };

  let backendRes = await send(request.cookies.get("access_token")?.value);
  let refreshed: Tokens | null = null;

  if (backendRes.status === 401 && !joined.startsWith("auth/")) {
    const refreshToken = request.cookies.get("refresh_token")?.value;
    refreshed = refreshToken ? await refreshOnce(refreshToken) : null;
    if (!refreshed) {
      const response = NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
      response.cookies.delete("access_token");
      response.cookies.delete("refresh_token");
      return response;
    }
    backendRes = await send(refreshed.access);
  }

  const responseBody = backendRes.status === 204 ? null : await backendRes.arrayBuffer();
  const response = new NextResponse(responseBody, {
    status: backendRes.status,
    statusText: backendRes.statusText,
  });

  backendRes.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (lower !== "transfer-encoding" && lower !== "content-encoding") {
      response.headers.set(key, value);
    }
  });

  if (refreshed) {
    setAccessCookie(response, refreshed.access);
    if (refreshed.refresh) setRefreshCookie(response, refreshed.refresh);
  }

  return response;
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return proxy(req, await ctx.params);
}
export async function POST(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return proxy(req, await ctx.params);
}
export async function PUT(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return proxy(req, await ctx.params);
}
export async function PATCH(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return proxy(req, await ctx.params);
}
export async function DELETE(req: NextRequest, ctx: RouteContext): Promise<NextResponse> {
  return proxy(req, await ctx.params);
}
