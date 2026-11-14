import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

function logout(contentType: string, refreshToken?: string) {
  const headers = new Headers({ "Content-Type": contentType });
  if (refreshToken) headers.set("Cookie", `refresh_token=${refreshToken}`);
  const request = new NextRequest("http://localhost/auth-cookie/logout", {
    method: "POST",
    headers,
    body: contentType === "application/json" ? "{}" : "refresh_token=stolen",
  });
  return POST(request);
}

function backendAnswers(status = 200) {
  const fetchMock = vi.fn(async () => Response.json({ detail: "ok" }, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function deletedCookies(response: Response): string[] {
  return response.headers
    .getSetCookie()
    .filter((cookie) => /^access_token=|^refresh_token=/.test(cookie))
    .map((cookie) => cookie.split("=")[0]);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("выход через /auth-cookie/logout", () => {
  it("не-JSON выход отклоняется с 415 без удаления cookie и без запроса к бэкенду", async () => {
    const fetchMock = backendAnswers();

    const response = await logout("application/x-www-form-urlencoded", "refresh-jwt");

    expect(response.status).toBe(415);
    expect(await response.json()).toEqual({ detail: "Ожидается JSON" });
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("JSON-выход отзывает refresh-токен на бэкенде и удаляет обе cookie", async () => {
    const fetchMock = backendAnswers();

    const response = await logout("application/json", "refresh-jwt");

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/auth/logout/");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ refresh: "refresh-jwt" });
    expect(deletedCookies(response)).toEqual(["access_token", "refresh_token"]);
  });
});
