import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/auth-cookie", "/api"];

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // An expired access cookie is fine while the refresh one lives: the /api proxy refreshes it.
  if (!request.cookies.has("access_token") && !request.cookies.has("refresh_token")) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
