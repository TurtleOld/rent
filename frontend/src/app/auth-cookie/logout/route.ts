import { NextRequest, NextResponse } from "next/server";
import { forgetRefresh } from "@/lib/tokenRefresh";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const refreshToken = request.cookies.get("refresh_token")?.value;

  if (refreshToken) {
    forgetRefresh(refreshToken);
    try {
      await fetch(`${BACKEND_URL}/api/auth/logout/`, {
        method: "POST",
        // Without it Django's SECURE_SSL_REDIRECT answers 301 and the token is never blacklisted.
        headers: { "Content-Type": "application/json", "X-Forwarded-Proto": "https" },
        body: JSON.stringify({ refresh: refreshToken }),
      });
    } catch {
      // Proceed with cookie deletion even if backend call fails
    }
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.delete("access_token");
  response.cookies.delete("refresh_token");
  return response;
}
