import { describe, expect, it } from "vitest";
import { upsertInvoice } from "./invoiceList";

describe("список квитанций после загрузки", () => {
  it("новая квитанция встаёт в начало", () => {
    expect(upsertInvoice([{ id: 1 }], { id: 2 })).toEqual([{ id: 2 }, { id: 1 }]);
  });

  it("повторная загрузка заменяет карточку, а не добавляет вторую", () => {
    const invoices = [
      { id: 2, status: "processing" },
      { id: 1, status: "processed" },
    ];

    expect(upsertInvoice(invoices, { id: 2, status: "processed" })).toEqual([
      { id: 2, status: "processed" },
      { id: 1, status: "processed" },
    ]);
  });
});
