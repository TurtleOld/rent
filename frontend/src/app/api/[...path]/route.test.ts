import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const TOKENS = { access: "access-jwt", refresh: "refresh-jwt" };

function login(contentType: string, body: string) {
  const request = new NextRequest("http://localhost/api/auth/login/", {
    method: "POST",
    headers: { "Content-Type": contentType },
    body,
  });
  return POST(request, { params: Promise.resolve({ path: ["auth", "login"] }) });
}

function backendAnswers(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => Response.json(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("вход через /api прокси", () => {
  it("не-JSON вход отклоняется с 415 без cookie и без запроса к бэкенду", async () => {
    const fetchMock = backendAnswers(200, TOKENS);

    const response = await login("application/x-www-form-urlencoded", "email=a%40b.ru&password=x");

    expect(response.status).toBe(415);
    expect(response.cookies.getAll()).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("успешный JSON-вход ставит httpOnly-cookie, а тело без токенов", async () => {
    backendAnswers(200, TOKENS);

    const response = await login("application/json", JSON.stringify({ email: "a@b.ru", password: "x" }));

    expect(response.status).toBe(200);
    expect(response.cookies.get("access_token")).toMatchObject({ value: "access-jwt", httpOnly: true });
    expect(response.cookies.get("refresh_token")).toMatchObject({ value: "refresh-jwt", httpOnly: true });
    const text = await response.text();
    expect(text).not.toContain("access-jwt");
    expect(text).not.toContain("refresh-jwt");
  });

  it("неудачный вход возвращает статус бэкенда без cookie", async () => {
    backendAnswers(401, { detail: "No active account found with the given credentials" });

    const response = await login("application/json", JSON.stringify({ email: "a@b.ru", password: "bad" }));

    expect(response.status).toBe(401);
    expect(response.cookies.getAll()).toEqual([]);
  });
});
