import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const refreshToken = request.cookies.get("refresh_token")?.value;

  if (refreshToken) {
    try {
      await fetch(`${BACKEND_URL}/api/auth/logout/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
