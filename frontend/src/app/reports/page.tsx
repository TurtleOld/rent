"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { type Invoice, getInvoicesAll } from "@/lib/api";
import styles from "./reports.module.css";

const MONTH_SHORT = [
  "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
];

// ── SVG Line Chart ────────────────────────────────────────────────────────────

interface Point {
  x: number;
  y: number;
  label: string;
  value: number;
}

function LineChart({ points, color = "#3b82f6", unit = "₽" }: { points: Point[]; color?: string; unit?: string }) {
  const W = 480;
  const H = 180;
  const PAD = { top: 16, right: 16, bottom: 36, left: 56 };

  if (points.length === 0) return null;

  const values = points.map((p) => p.value);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  const toX = (i: number) =>
    PAD.left + (i / Math.max(points.length - 1, 1)) * (W - PAD.left - PAD.right);
  const toY = (v: number) =>
    PAD.top + (1 - (v - minVal) / range) * (H - PAD.top - PAD.bottom);

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)} ${toY(p.value).toFixed(1)}`)
    .join(" ");

  // Y-axis grid lines
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => minVal + (range * i) / ticks);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={styles.chartSvg}>
      {/* Grid lines */}
      {yTicks.map((v, i) => (
        <g key={i}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={toY(v)}
            y2={toY(v)}
            stroke="#e5e7eb"
            strokeWidth="1"
          />
          <text
            x={PAD.left - 6}
            y={toY(v) + 4}
            textAnchor="end"
            className={styles.chartTick}
          >
            {v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}
          </text>
        </g>
      ))}

      {/* Line */}
      <path d={pathD} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />

      {/* Dots + X labels */}
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={toX(i)} cy={toY(p.value)} r="4" fill={color} />
          <title>{`${p.label}: ${p.value.toLocaleString("ru-RU", { minimumFractionDigits: 2 })} ${unit}`}</title>
          <text
            x={toX(i)}
            y={H - PAD.bottom + 16}
            textAnchor="middle"
            className={styles.chartTick}
          >
            {p.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

// ── Multi-series service chart ────────────────────────────────────────────────

const VOLUME_UNITS_EXCLUDE = new Set(["кв.м.", "кв.м", "чел.", "чел", "абонент", "абон."]);

function showVolume(unit: string | null): boolean {
  if (!unit) return false;
  return !VOLUME_UNITS_EXCLUDE.has(unit.trim().toLowerCase());
}

interface ServiceRow {
  period: string;
  tariff: number | null;
  amount: number | null;
  quantity: number | null;
  unit: string | null;
}

function ServiceChart({ service, rows }: { service: string; rows: ServiceRow[] }) {
  const hasVolume = rows.some((r) => r.quantity != null && showVolume(rows[0]?.unit ?? null));
  const unit = rows[0]?.unit ?? null;

  const tariffPoints: Point[] = rows
    .map((r, i) => ({ x: i, y: 0, label: r.period, value: r.tariff ?? 0 }))
    .filter((_, i) => rows[i].tariff != null);

  const amountPoints: Point[] = rows
    .map((r, i) => ({ x: i, y: 0, label: r.period, value: r.amount ?? 0 }))
    .filter((_, i) => rows[i].amount != null);

  const volumePoints: Point[] = hasVolume
    ? rows
        .map((r, i) => ({ x: i, y: 0, label: r.period, value: r.quantity ?? 0 }))
        .filter((_, i) => rows[i].quantity != null)
    : [];

  const series: { label: string; points: Point[]; color: string; unit: string }[] = [];
  if (tariffPoints.length >= 2) series.push({ label: "Тариф", points: tariffPoints, color: "#f59e0b", unit: "₽" });
  if (amountPoints.length >= 2) series.push({ label: "Сумма", points: amountPoints, color: "#3b82f6", unit: "₽" });
  if (volumePoints.length >= 2) series.push({ label: "Объём", points: volumePoints, color: "#10b981", unit: unit ?? "" });

  if (series.length === 0) return null;

  return (
    <div className={styles.chartCard}>
      <h3 className={styles.chartTitle}>{service}</h3>
      <div className={styles.multiChartGrid}>
        {series.map(({ label, points, color, unit: u }) => (
          <div key={label} className={styles.miniChartWrap}>
            <div className={styles.miniChartLabel} style={{ color }}>{label}</div>
            <LineChart points={points} color={color} unit={u} />
          </div>
        ))}
      </div>
      <div className={styles.chartLegend}>
        {series.map(({ label, color }) => (
          <span key={label} className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: color }} />
            {label}{label !== "Объём" ? " (₽)" : unit ? ` (${unit})` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function periodLabel(inv: Invoice): string {
  if (inv.period_month != null && inv.period_year != null) {
    return `${MONTH_SHORT[inv.period_month - 1]} ${String(inv.period_year).slice(2)}`;
  }
  return new Date(inv.created_at).toLocaleDateString("ru-RU", { month: "short", year: "2-digit" });
}

function periodKey(inv: Invoice): string {
  if (inv.period_month != null && inv.period_year != null) {
    return `${inv.period_year}-${String(inv.period_month).padStart(2, "0")}`;
  }
  return inv.created_at.slice(0, 7);
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const router = useRouter();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);

  useEffect(() => {
    getInvoicesAll()
      .then((data) => {
        const processed = data.filter((inv) => inv.status === "processed");
        setInvoices(processed);
      })
      .catch(() => setError("Не удалось загрузить данные"))
      .finally(() => setLoading(false));
  }, []);

  // Group invoices by account_number
  const accounts = useMemo(() => {
    const map = new Map<string, Invoice[]>();
    for (const inv of invoices) {
      const key = inv.account_number ?? `#${inv.id}`;
      const list = map.get(key) ?? [];
      list.push(inv);
      map.set(key, list);
    }
    // Sort each group by period ascending
    for (const [, list] of map) {
      list.sort((a, b) => periodKey(a).localeCompare(periodKey(b)));
    }
    return map;
  }, [invoices]);

  const accountKeys = useMemo(() => Array.from(accounts.keys()), [accounts]);

  // Set default selected account
  useEffect(() => {
    if (accountKeys.length > 0 && selectedAccount === null) {
      setSelectedAccount(accountKeys[0]);
    }
  }, [accountKeys, selectedAccount]);

  const selectedInvoices = useMemo(
    () => (selectedAccount ? (accounts.get(selectedAccount) ?? []) : []),
    [accounts, selectedAccount],
  );

  // Chart data for amount_due_without_insurance per account
  const chartDataByAccount = useMemo(() => {
    const result: { account: string; points: Point[] }[] = [];
    for (const [account, list] of accounts) {
      const points: Point[] = list
        .filter((inv) => inv.amount_due_without_insurance != null || inv.amount_due != null)
        .map((inv, i) => ({
          x: i,
          y: 0,
          label: periodLabel(inv),
          value: parseFloat(inv.amount_due_without_insurance ?? inv.amount_due ?? "0"),
        }));
      if (points.length >= 2) result.push({ account, points });
    }
    return result;
  }, [accounts]);

  // Tariff & amount trends per service for selected account
  const serviceTrends = useMemo(() => {
    if (!selectedInvoices.length) return [];

    const map = new Map<string, ServiceRow[]>();

    for (const inv of selectedInvoices) {
      const period = periodLabel(inv);
      for (const item of inv.line_items) {
        const key = item.service_name;
        const list = map.get(key) ?? [];
        list.push({
          period,
          tariff: item.tariff != null ? parseFloat(item.tariff) : null,
          amount: item.amount != null ? parseFloat(item.amount) : null,
          quantity: item.quantity != null ? parseFloat(item.quantity) : null,
          unit: item.unit ?? null,
        });
        map.set(key, list);
      }
    }

    return Array.from(map.entries()).map(([service, rows]) => ({ service, rows }));
  }, [selectedInvoices]);

  if (loading) return <div className={styles.loading}>Загрузка...</div>;

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button onClick={() => router.push("/dashboard")} className={styles.backBtn}>
          ← Назад
        </button>
        <h1 className={styles.heading}>Отчёты</h1>
      </div>

      {error && <p className={styles.error}>{error}</p>}

      {invoices.length === 0 && !error && (
        <p className={styles.empty}>Нет обработанных квитанций для построения отчётов.</p>
      )}

      {/* ── Section 1: Amount without insurance per account ── */}
      {chartDataByAccount.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>Сумма к оплате без страхования по лицевым счетам</h2>
          <div className={styles.chartGrid}>
            {chartDataByAccount.map(({ account, points }) => (
              <div key={account} className={styles.chartCard}>
                <h3 className={styles.chartTitle}>Л/с {account}</h3>
                <LineChart points={points} />
                <div className={styles.chartLegend}>
                  <span className={styles.legendDot} style={{ background: "#3b82f6" }} />
                  Сумма без страх. (₽)
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Section 2: Tariff & amount per service ── */}
      {accountKeys.length > 0 && (
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Динамика тарифов и сумм по услугам</h2>
            <div className={styles.accountPicker}>
              <label className={styles.pickerLabel}>Лицевой счёт:</label>
              <select
                className={styles.pickerSelect}
                value={selectedAccount ?? ""}
                onChange={(e) => setSelectedAccount(e.target.value)}
              >
                {accountKeys.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {serviceTrends.length === 0 ? (
            <p className={styles.empty}>Нет строк услуг для выбранного счёта.</p>
          ) : (
            <div className={styles.chartGrid}>
              {serviceTrends.map(({ service, rows }) => (
                <ServiceChart key={service} service={service} rows={rows} />
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
