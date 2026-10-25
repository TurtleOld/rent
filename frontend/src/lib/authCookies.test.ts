import { NextResponse } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setAccessCookie, setRefreshCookie } from "./authCookies";

afterEach(() => {
  vi.unstubAllEnvs();
});

function accessMaxAge(): number | undefined {
  const response = NextResponse.json({});
  setAccessCookie(response, "access-jwt");
  return response.cookies.get("access_token")?.maxAge;
}

function refreshMaxAge(): number | undefined {
  const response = NextResponse.json({});
  setRefreshCookie(response, "refresh-jwt");
  return response.cookies.get("refresh_token")?.maxAge;
}

describe("срок жизни cookie", () => {
  it("по умолчанию 60 минут для access и 7 дней для refresh", () => {
    delete process.env.ACCESS_TOKEN_LIFETIME_MINUTES;
    delete process.env.REFRESH_TOKEN_LIFETIME_DAYS;

    expect(accessMaxAge()).toBe(60 * 60);
    expect(refreshMaxAge()).toBe(60 * 60 * 24 * 7);
  });

  it("берёт срок жизни из переменных окружения", () => {
    vi.stubEnv("ACCESS_TOKEN_LIFETIME_MINUTES", "15");
    vi.stubEnv("REFRESH_TOKEN_LIFETIME_DAYS", "30");

    expect(accessMaxAge()).toBe(15 * 60);
    expect(refreshMaxAge()).toBe(60 * 60 * 24 * 30);
  });

  it("при некорректном значении возвращается к значению по умолчанию", () => {
    vi.stubEnv("ACCESS_TOKEN_LIFETIME_MINUTES", "abc");
    vi.stubEnv("REFRESH_TOKEN_LIFETIME_DAYS", "0");

    expect(accessMaxAge()).toBe(60 * 60);
    expect(refreshMaxAge()).toBe(60 * 60 * 24 * 7);
  });
});
