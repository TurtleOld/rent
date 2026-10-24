import type { NextResponse } from "next/server";

const BASE = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

export function setAccessCookie(response: NextResponse, access: string): void {
  response.cookies.set("access_token", access, { ...BASE, maxAge: 60 * 60 });
}

export function setRefreshCookie(response: NextResponse, refresh: string): void {
  response.cookies.set("refresh_token", refresh, { ...BASE, maxAge: 60 * 60 * 24 * 7 });
}
