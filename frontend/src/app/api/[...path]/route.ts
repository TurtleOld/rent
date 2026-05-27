import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

const SKIPPED_REQUEST_HEADERS = new Set(["host", "cookie"]);

async function proxy(request: NextRequest, params: { path: string[] }): Promise<NextResponse> {
  const { path } = await params;
  const search = request.nextUrl.search;
  const url = `${BACKEND_URL}/api/${path.join("/")}${search}`;

  const accessToken = request.cookies.get("access_token")?.value;

  const forwardedHeaders = new Headers();
  request.headers.forEach((value, key) => {
    if (!SKIPPED_REQUEST_HEADERS.has(key.toLowerCase())) {
      forwardedHeaders.set(key, value);
    }
  });
  if (accessToken) {
    forwardedHeaders.set("Authorization", `Bearer ${accessToken}`);
  }

  const contentType = request.headers.get("content-type") ?? "";
  const isMultipart = contentType.includes("multipart/form-data");

  const fetchOptions: RequestInit = {
    method: request.method,
    headers: forwardedHeaders,
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    if (isMultipart) {
      fetchOptions.body = request.body;
      // @ts-expect-error duplex is required for streaming request body
      fetchOptions.duplex = "half";
    } else {
      fetchOptions.body = await request.text();
    }
  }

  const backendRes = await fetch(url, fetchOptions);

  if (backendRes.status === 401) {
    const response = NextResponse.json(
      { detail: "Unauthorized" },
      { status: 401 },
    );
    response.cookies.delete("access_token");
    response.cookies.delete("refresh_token");
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
