import { NextRequest, NextResponse } from "next/server";
import { setRefreshCookie } from "@/lib/authCookies";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const { refresh } = (await request.json()) as { refresh: string };
  const response = NextResponse.json({ ok: true });
  setRefreshCookie(response, refresh);
  return response;
}
