import { NextResponse } from "next/server";

export async function POST(): Promise<NextResponse> {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete("refresh_token");
  response.cookies.delete("access_token");
  return response;
}
