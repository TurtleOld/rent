import { describe, expect, it } from "vitest";
import { type Invoice } from "./api";
import { unknownAmountNote } from "./reports";

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
