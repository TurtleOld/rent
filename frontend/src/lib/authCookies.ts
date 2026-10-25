import type { NextResponse } from "next/server";

const BASE = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

const DEFAULT_ACCESS_MINUTES = 60;
const DEFAULT_REFRESH_DAYS = 7;

// Значение читается при каждом вызове: имена и значения те же, что в Django SimpleJWT.
function envPositiveInt(name: string, fallback: number): number {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

export function accessCookieMaxAge(): number {
  return envPositiveInt("ACCESS_TOKEN_LIFETIME_MINUTES", DEFAULT_ACCESS_MINUTES) * 60;
}

export function refreshCookieMaxAge(): number {
  return envPositiveInt("REFRESH_TOKEN_LIFETIME_DAYS", DEFAULT_REFRESH_DAYS) * 60 * 60 * 24;
}

export function setAccessCookie(response: NextResponse, access: string): void {
  response.cookies.set("access_token", access, { ...BASE, maxAge: accessCookieMaxAge() });
}

export function setRefreshCookie(response: NextResponse, refresh: string): void {
  response.cookies.set("refresh_token", refresh, { ...BASE, maxAge: refreshCookieMaxAge() });
}
