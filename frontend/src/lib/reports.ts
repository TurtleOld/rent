import { type Invoice, type LineItem } from "./api";

// Group by Service so aliases merged in the admin show as one line.
export function serviceKey(item: LineItem): string {
  return item.service != null ? `id:${item.service}` : `name:${item.service_name}`;
}

export const MONTH_SHORT = [
  "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
];

export function periodLabel(inv: Invoice): string {
  if (inv.period_month != null && inv.period_year != null) {
    return `${MONTH_SHORT[inv.period_month - 1]} ${String(inv.period_year).slice(2)}`;
  }
  return new Date(inv.created_at).toLocaleDateString("ru-RU", {
    month: "short",
    year: "2-digit",
  });
}

export function periodKey(inv: Invoice): string {
  if (inv.period_month != null && inv.period_year != null) {
    return `${inv.period_year}-${String(inv.period_month).padStart(2, "0")}`;
  }
  return inv.created_at.slice(0, 7);
}

const VOLUME_UNITS: ReadonlySet<string> = new Set(["куб.м", "кВт·ч", "Гкал"]);

export function showVolume(unit: string | null): boolean {
  if (!unit) return false;
  return VOLUME_UNITS.has(unit.trim());
}

// Квитанции без суммы к оплате не попадают в итоги и графики — об этом надо сказать.
export function unknownAmountNote(invoices: Invoice[]): string | null {
  const n = invoices.filter((inv) => inv.amount_due == null).length;
  if (n === 0) return null;
  const word = n % 10 === 1 && n % 100 !== 11 ? "квитанции" : "квитанций";
  return `без учёта ${n} ${word}`;
}
