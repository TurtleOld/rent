import { describe, expect, it } from "vitest";
import { type Invoice, type LineItem } from "./api";
import { buildTariffRows, unknownAmountNote } from "./reports";

const inv = (amount_due: string | null) => ({ amount_due }) as Invoice;

describe("пометка о квитанциях без суммы к оплате", () => {
  it("нет пометки, когда все суммы известны", () => {
    expect(unknownAmountNote([inv("100.00"), inv("0.00")])).toBeNull();
  });

  it.each([
    [1, "без учёта 1 квитанции"],
    [2, "без учёта 2 квитанций"],
    [11, "без учёта 11 квитанций"],
    [21, "без учёта 21 квитанции"],
  ])("%i без суммы → «%s»", (n, note) => {
    const invoices = [inv("100.00"), ...Array.from({ length: n }, () => inv(null))];
    expect(unknownAmountNote(invoices)).toBe(note);
  });
});

const line = (over: Partial<LineItem> = {}): LineItem =>
  ({
    id: 1,
    service_name: "Холодная вода",
    service: 1,
    unit: "куб.м",
    quantity: null,
    tariff: "80.0000",
    amount_charged: null,
    recalculation: null,
    debt: null,
    amount: null,
    provider: null,
    meter_id: null,
    previous_reading: null,
    current_reading: null,
    ...over,
  }) as LineItem;

const invoice = (
  month: number,
  lines: LineItem[],
  { account = "A-1", year = 2026, id = month } = {},
): Invoice =>
  ({
    id,
    account_number: account,
    status: "processed",
    period_month: month,
    period_year: year,
    created_at: `${year}-${String(month).padStart(2, "0")}-10T00:00:00Z`,
    line_items: lines,
    warnings: [],
  }) as unknown as Invoice;

describe("сравнение тарифов по расчётным периодам", () => {
  it("соседние месяцы: текущий и предыдущий тариф с подписями периодов", () => {
    const rows = buildTariffRows(
      [invoice(1, [line({ tariff: "80.0000" })]), invoice(2, [line({ tariff: "90.0000" })])],
      "A-1",
    );

    expect(rows).toHaveLength(1);
    expect(rows[0].current).toEqual({ periodLabel: "Фев 26", tariff: 90, ambiguous: false });
    expect(rows[0].previous).toEqual({ periodLabel: "Янв 26", tariff: 80, ambiguous: false });
    expect(rows[0].changePct).toBe(12.5);
    expect(rows[0].note).toBeNull();
  });

  it("пропущенный месяц: сравнивается фактический предыдущий период, а не апрель", () => {
    const rows = buildTariffRows(
      [invoice(2, [line({ tariff: "80.0000" })]), invoice(5, [line({ tariff: "90.0000" })])],
      "A-1",
    );

    expect(rows[0].current.periodLabel).toBe("Май 26");
    expect(rows[0].previous?.periodLabel).toBe("Фев 26");
    expect(rows[0].changePct).toBe(12.5);
  });

  it("несколько строк услуги за период с одинаковым тарифом не дают ложного изменения", () => {
    const rows = buildTariffRows(
      [
        invoice(1, [line({ tariff: "80.0000" })]),
        invoice(
          2,
          [
            line({ id: 2, tariff: "90.0000", provider: "Поставщик 1" }),
            line({ id: 3, tariff: "90.0000", provider: "Поставщик 2" }),
          ],
          { id: 2 },
        ),
      ],
      "A-1",
    );

    expect(rows).toHaveLength(1);
    expect(rows[0].current).toEqual({ periodLabel: "Фев 26", tariff: 90, ambiguous: false });
    expect(rows[0].changePct).toBe(12.5);
  });

  it("разные тарифы за один период показывают неоднозначность вместо последней строки", () => {
    const rows = buildTariffRows(
      [
        invoice(1, [line({ tariff: "80.0000" })]),
        invoice(2, [line({ id: 2, tariff: "90.0000" }), line({ id: 3, tariff: "100.0000" })], {
          id: 2,
        }),
      ],
      "A-1",
    );

    expect(rows[0].current).toEqual({ periodLabel: "Фев 26", tariff: null, ambiguous: true });
    expect(rows[0].changePct).toBeNull();
    expect(rows[0].note).toBe("тариф за текущий период неоднозначен");
  });

  it("разные единицы измерения не сравниваются", () => {
    const rows = buildTariffRows(
      [
        invoice(1, [line({ unit: "куб.м", tariff: "80.0000" })]),
        invoice(2, [line({ unit: "Гкал", tariff: "90.0000" })]),
      ],
      "A-1",
    );

    expect(rows[0].current.tariff).toBe(90);
    expect(rows[0].previous?.tariff).toBe(80);
    expect(rows[0].changePct).toBeNull();
    expect(rows[0].note).toBe("разные единицы измерения");
  });

  it("нулевой предыдущий тариф не даёт процента", () => {
    const rows = buildTariffRows(
      [invoice(1, [line({ tariff: "0.0000" })]), invoice(2, [line({ tariff: "90.0000" })])],
      "A-1",
    );

    expect(rows[0].previous?.tariff).toBe(0);
    expect(rows[0].changePct).toBeNull();
    expect(rows[0].note).toBe("предыдущий тариф равен нулю");
  });

  it("отсутствующий предыдущий тариф не даёт процента", () => {
    const rows = buildTariffRows(
      [invoice(1, [line({ tariff: null })]), invoice(2, [line({ tariff: "90.0000" })])],
      "A-1",
    );

    expect(rows[0].previous).toBeNull();
    expect(rows[0].changePct).toBeNull();
    expect(rows[0].note).toBe("нет предыдущего периода с тарифом");
  });

  it("сравниваются только услуги выбранного лицевого счёта", () => {
    const invoices = [
      invoice(1, [line({ tariff: "80.0000" })]),
      invoice(2, [line({ tariff: "90.0000" })]),
      invoice(1, [line({ tariff: "10.0000" })], { account: "B-2", id: 11 }),
      invoice(2, [line({ tariff: "20.0000" })], { account: "B-2", id: 12 }),
    ];

    const rows = buildTariffRows(invoices, "A-1");

    expect(rows).toHaveLength(1);
    expect(rows[0].previous?.tariff).toBe(80);
    expect(rows[0].current.tariff).toBe(90);
    expect(rows[0].changePct).toBe(12.5);
  });

  it("объединённые варианты названия одной услуги сравниваются как одна услуга", () => {
    const rows = buildTariffRows(
      [
        invoice(1, [line({ service: 7, service_name: "ХВС", tariff: "80.0000" })]),
        invoice(2, [line({ service: 7, service_name: "Холодная вода", tariff: "90.0000" })]),
      ],
      "A-1",
    );

    expect(rows).toHaveLength(1);
    expect(rows[0].serviceName).toBe("Холодная вода");
    expect(rows[0].changePct).toBe(12.5);
  });

  it("разные услуги не попадают в одну строку", () => {
    const rows = buildTariffRows(
      [
        invoice(1, [
          line({ service: 1, tariff: "80.0000" }),
          line({ id: 2, service: 2, service_name: "Отопление", unit: "Гкал", tariff: "2000.0000" }),
        ]),
        invoice(2, [
          line({ service: 1, tariff: "90.0000" }),
          line({ id: 2, service: 2, service_name: "Отопление", unit: "Гкал", tariff: "2200.0000" }),
        ]),
      ],
      "A-1",
    );

    expect(rows).toHaveLength(2);
    expect(rows.find((r) => r.serviceName === "Отопление")?.changePct).toBe(10);
  });
});
