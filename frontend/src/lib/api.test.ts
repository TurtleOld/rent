import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getInvoice, login, uploadInvoice } from "./api";

function backendAnswers(status: number, body: unknown) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Response.json(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubWindow() {
  const win = { location: { href: "/login" } };
  vi.stubGlobal("window", win);
  return win;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("общий клиент API", () => {
  it.each([401, 429])("ошибка входа %i не перезагружает страницу входа", async (status) => {
    backendAnswers(status, { detail: "x" });
    const win = stubWindow();
    win.location.href = "/login?keep";

    await expect(login("a@b.ru", "wrong")).rejects.toMatchObject({ status });
    expect(win.location.href).toBe("/login?keep");
  });

  it("401 на остальных запросах ведёт на страницу входа", async () => {
    backendAnswers(401, { detail: "Unauthorized" });
    const win = stubWindow();
    win.location.href = "/dashboard";

    await expect(getInvoice(1)).rejects.toBeInstanceOf(ApiError);
    expect(win.location.href).toBe("/login");
  });

  it("загрузка PDF шлёт FormData без ручного Content-Type", async () => {
    const fetchMock = backendAnswers(201, { id: 7 });
    const file = new File(["%PDF"], "bill.pdf", { type: "application/pdf" });

    await expect(uploadInvoice(file)).resolves.toEqual({ id: 7 });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/invoices/upload/");
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("pdf_file")).toBeInstanceOf(File);
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
  });

  it("ошибка загрузки отдаёт статус и тело ответа", async () => {
    backendAnswers(400, { pdf_file: ["Файл больше 20 МБ"] });
    const file = new File(["%PDF"], "big.pdf", { type: "application/pdf" });

    await expect(uploadInvoice(file)).rejects.toMatchObject({
      status: 400,
      data: { pdf_file: ["Файл больше 20 МБ"] },
    });
  });
});
