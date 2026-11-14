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

export interface TariffPoint {
  periodLabel: string;
  tariff: number | null;
  ambiguous: boolean;
}

export interface TariffRow {
  serviceName: string;
  unit: string | null;
  current: TariffPoint;
  previous: TariffPoint | null;
  changePct: number | null;
  note: string | null;
}

function accountKey(inv: Invoice): string {
  return inv.account_number ?? `#${inv.id}`;
}

interface PeriodTariffs {
  label: string;
  tariffs: Set<number>;
  units: Set<string>;
}

function toPoint({ label, tariffs, units }: PeriodTariffs): TariffPoint {
  const ambiguous = tariffs.size > 1 || units.size > 1;
  return {
    periodLabel: label,
    tariff: ambiguous ? null : (tariffs.values().next().value ?? null),
    ambiguous,
  };
}

function singleUnit(period: PeriodTariffs): string | null {
  if (period.units.size !== 1) return null;
  return period.units.values().next().value || null;
}

// Сравниваем последний и предыдущий доступные периоды услуги: в отчёте бывают
// пропуски месяцев, и соседняя строка — не обязательно предыдущий период.
export function buildTariffRows(invoices: Invoice[], account: string | null): TariffRow[] {
  const byService = new Map<string, { serviceName: string; periods: Map<string, PeriodTariffs> }>();
  const chronological = [...invoices].sort((a, b) => periodKey(a).localeCompare(periodKey(b)));

  for (const inv of chronological) {
    if (account !== null && accountKey(inv) !== account) continue;
    const periodKeyValue = periodKey(inv);
    const label = periodLabel(inv);
    for (const item of inv.line_items) {
      if (item.tariff == null) continue;
      const tariff = parseFloat(item.tariff);
      if (!isFinite(tariff)) continue;
      const key = serviceKey(item);
      const entry = byService.get(key) ?? { serviceName: item.service_name, periods: new Map() };
      entry.serviceName = item.service_name;
      const period = entry.periods.get(periodKeyValue) ?? {
        label,
        tariffs: new Set<number>(),
        units: new Set<string>(),
      };
      period.tariffs.add(tariff);
      period.units.add(item.unit?.trim() ?? "");
      entry.periods.set(periodKeyValue, period);
      byService.set(key, entry);
    }
  }

  const rows: TariffRow[] = [];
  for (const { serviceName, periods } of byService.values()) {
    const sorted = [...periods.entries()].sort(([a], [b]) => a.localeCompare(b));
    const currentPeriod = sorted[sorted.length - 1][1];
    const previousPeriod = sorted.length >= 2 ? sorted[sorted.length - 2][1] : null;
    const current = toPoint(currentPeriod);
    const previous = previousPeriod ? toPoint(previousPeriod) : null;
    const currentUnit = singleUnit(currentPeriod);
    const previousUnit = previousPeriod ? singleUnit(previousPeriod) : null;

    let changePct: number | null = null;
    let note: string | null = null;
    if (current.ambiguous) {
      note = "тариф за текущий период неоднозначен";
    } else if (!previous) {
      note = "нет предыдущего периода с тарифом";
    } else if (previous.ambiguous) {
      note = "тариф за предыдущий период неоднозначен";
    } else if (previous.tariff === 0) {
      note = "предыдущий тариф равен нулю";
    } else if (currentUnit !== previousUnit) {
      note = "разные единицы измерения";
    } else if (current.tariff != null && previous.tariff != null) {
      changePct = Math.round(((current.tariff - previous.tariff) / previous.tariff) * 10000) / 100;
    }

    rows.push({ serviceName, unit: currentUnit, current, previous, changePct, note });
  }
  return rows;
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

// Неполные квитанции (без распознанных услуг) исключаются из итогов и графиков — об этом надо сказать.
export function incompleteNote(invoices: Invoice[]): string | null {
  const n = invoices.filter((inv) => inv.status === "incomplete").length;
  if (n === 0) return null;
  const mod10 = n % 10;
  const mod100 = n % 100;
  const phrase =
    mod10 === 1 && mod100 !== 11
      ? "неполная квитанция исключена"
      : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)
        ? "неполные квитанции исключены"
        : "неполных квитанций исключены";
  return `${n} ${phrase} из итогов и графиков`;
}
