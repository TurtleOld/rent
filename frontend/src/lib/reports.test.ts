import { describe, expect, it } from "vitest";
import { type Invoice } from "./api";
import { incompleteNote, unknownAmountNote } from "./reports";

const inv = (amount_due: string | null, status: Invoice["status"] = "processed") =>
  ({ amount_due, status }) as Invoice;

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

describe("пометка о неполных квитанциях, исключённых из итогов", () => {
  it("нет пометки, когда неполных квитанций нет", () => {
    expect(incompleteNote([inv("100.00"), inv(null)])).toBeNull();
  });

  it.each([
    [1, "1 неполная квитанция исключена из итогов и графиков"],
    [2, "2 неполные квитанции исключены из итогов и графиков"],
    [5, "5 неполных квитанций исключены из итогов и графиков"],
    [11, "11 неполных квитанций исключены из итогов и графиков"],
    [21, "21 неполная квитанция исключена из итогов и графиков"],
  ])("%i неполных → «%s»", (n, note) => {
    const invoices = [
      inv("100.00"),
      ...Array.from({ length: n }, () => inv("3600.00", "incomplete")),
    ];
    expect(incompleteNote(invoices)).toBe(note);
  });
});
