import { NextResponse } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessCookie, setRefreshCookie } from "./authCookies";

const ENV_KEYS = ["ACCESS_TOKEN_LIFETIME_MINUTES", "REFRESH_TOKEN_LIFETIME_DAYS"] as const;
const savedEnv: Partial<Record<(typeof ENV_KEYS)[number], string>> = {};

beforeEach(() => {
  for (const key of ENV_KEYS) {
    savedEnv[key] = process.env[key];
    delete process.env[key];
  }
});

afterEach(() => {
  vi.unstubAllEnvs();
  for (const key of ENV_KEYS) {
    if (savedEnv[key] === undefined) delete process.env[key];
    else process.env[key] = savedEnv[key];
  }
});

function cookieMaxAge(
  setCookie: (response: NextResponse, token: string) => void,
  cookieName: string,
  token: string,
): number | undefined {
  const response = NextResponse.json({});
  setCookie(response, token);
  return response.cookies.get(cookieName)?.maxAge;
}

function accessMaxAge(): number | undefined {
  return cookieMaxAge(setAccessCookie, "access_token", "access-jwt");
}

function refreshMaxAge(): number | undefined {
  return cookieMaxAge(setRefreshCookie, "refresh_token", "refresh-jwt");
}

describe("срок жизни cookie", () => {
  it("по умолчанию 60 минут для access и 7 дней для refresh", () => {
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
    vi.stubEnv("ACCESS_TOKEN_LIFETIME_MINUTES", "15abc");
    vi.stubEnv("REFRESH_TOKEN_LIFETIME_DAYS", "0");

    expect(accessMaxAge()).toBe(60 * 60);
    expect(refreshMaxAge()).toBe(60 * 60 * 24 * 7);
  });
});
