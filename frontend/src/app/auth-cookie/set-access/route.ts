import { NextRequest, NextResponse } from "next/server";
import { setAccessCookie } from "@/lib/authCookies";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const { access } = (await request.json()) as { access: string };
  const response = NextResponse.json({ ok: true });
  setAccessCookie(response, access);
  return response;
}
