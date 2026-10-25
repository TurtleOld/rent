import { afterEach, describe, expect, it, vi } from "vitest";
import { clearTokens } from "./auth";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("clearTokens", () => {
  it("выходит JSON-запросом, иначе маршрут ответит 415", async () => {
    const fetchMock = vi.fn(async () => Response.json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await clearTokens();

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/auth-cookie/logout");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
    expect(init.body).toBe("{}");
  });
});
