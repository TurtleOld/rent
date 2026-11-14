import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  getInvoice,
  login,
  loginErrorMessage,
  manualAmountDueErrorMessage,
  setManualAmountDue,
  uploadErrorMessage,
  uploadInvoice,
} from "./api";

function backendAnswers(status: number, body: unknown) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => Response.json(body, { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function stubWindow(href: string) {
  const win = { location: { href } };
  vi.stubGlobal("window", win);
  return win;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("общий клиент API", () => {
  it.each([401, 429])("ошибка входа %i не перезагружает страницу входа", async (status) => {
    backendAnswers(status, { detail: "x" });
    const win = stubWindow("/login?keep");

    await expect(login("a@b.ru", "wrong")).rejects.toMatchObject({ status });
    expect(win.location.href).toBe("/login?keep");
  });

  it("429 при входе даёт сообщение о лимите попыток, остальное — о неверных данных", () => {
    expect(loginErrorMessage(new ApiError(429, "x"))).toBe("Слишком много попыток входа. Попробуйте позже.");
    expect(loginErrorMessage(new ApiError(401, "x"))).toBe("Неверный email или пароль");
    expect(loginErrorMessage(new TypeError("Failed to fetch"))).toBe("Неверный email или пароль");
  });

  it("401 на остальных запросах ведёт на страницу входа", async () => {
    backendAnswers(401, { detail: "Unauthorized" });
    const win = stubWindow("/dashboard");

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

  it("ошибка загрузки берёт причину из pdf_file", () => {
    const err = new ApiError(400, "x", { pdf_file: ["Допускаются только PDF-файлы."] });

    expect(uploadErrorMessage(err)).toBe("Допускаются только PDF-файлы.");
  });

  it("ошибка загрузки берёт причину из detail", () => {
    const err = new ApiError(400, "x", { detail: "Файл не является валидным PDF" });

    expect(uploadErrorMessage(err)).toBe("Файл не является валидным PDF");
  });

  it.each([
    [new TypeError("Failed to fetch")],
    [new ApiError(500, "x", null)],
    [new ApiError(413, "x", "<html>413 Request Entity Too Large</html>")],
    [new ApiError(400, "x", { other_field: ["что-то"] })],
    [new ApiError(400, "x", { pdf_file: [42] })],
  ])("ошибка загрузки %o → общий текст", (err) => {
    expect(uploadErrorMessage(err)).toBe("Ошибка при загрузке файла");
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

describe("ручная сумма к оплате", () => {
  it.each([["1234.50"], [null]])("PUT шлёт %s в manual_amount_due", async (value) => {
    const fetchMock = backendAnswers(200, { id: 3 });

    await setManualAmountDue(3, value);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/invoices/3/manual-amount-due/");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({ manual_amount_due: value });
  });

  it.each([
    [new ApiError(409, "x", { detail: "Только для обработанной" }), "Только для обработанной"],
    [new ApiError(400, "x", { manual_amount_due: ["Не более 2 знаков"] }), "Не более 2 знаков"],
    [new ApiError(500, "x", null), "Не удалось сохранить сумму к оплате"],
    [new TypeError("Failed to fetch"), "Не удалось сохранить сумму к оплате"],
  ])("ошибка %o → «%s»", (err, message) => {
    expect(manualAmountDueErrorMessage(err)).toBe(message);
  });
});
