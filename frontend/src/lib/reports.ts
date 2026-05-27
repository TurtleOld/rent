import { type Invoice } from "./api";

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
