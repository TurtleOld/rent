import { NextRequest, NextResponse } from "next/server";
import { setAccessCookie, setRefreshCookie } from "@/lib/authCookies";
import { isJsonRequest, jsonRequired } from "@/lib/jsonOnly";
import { type Tokens, refreshOnce } from "@/lib/tokenRefresh";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

// content-length/transfer-encoding: fetch recomputes them for the buffered body.
const SKIPPED_REQUEST_HEADERS = new Set(["host", "cookie", "content-length", "transfer-encoding"]);

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

  const isLogin = joined === "auth/login";
  // Чужой сайт не отправит JSON без CORS-preflight, поэтому cookie ставит только вход JSON-ом.
  if (isLogin && !isJsonRequest(request)) return jsonRequired();

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

  if (isLogin && backendRes.ok) {
    // Токены сразу уходят в httpOnly-cookie и не попадают в JS браузера.
    const { access, refresh, ...rest } = (await backendRes.json()) as Required<Tokens>;
    const response = NextResponse.json(rest, { status: backendRes.status });
    setAccessCookie(response, access);
    setRefreshCookie(response, refresh);
    return response;
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
