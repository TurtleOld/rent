"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { type Invoice, getInvoicesAll } from "@/lib/api";
import { periodKey, periodLabel } from "@/lib/reports";
import LineChart, { type ChartPoint } from "@/components/LineChart";
import ServiceChart, { type ServiceRow } from "@/components/ServiceChart";
import TariffDynamicsTable, { type TariffRow } from "@/components/TariffDynamicsTable";
import styles from "./reports.module.css";

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const router = useRouter();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);

  useEffect(() => {
    getInvoicesAll()
      .then((data) => setInvoices(data.filter((inv) => inv.status === "processed")))
      .catch(() => setError("Не удалось загрузить данные"))
      .finally(() => setLoading(false));
  }, []);

  const accounts = useMemo(() => {
    const map = new Map<string, Invoice[]>();
    for (const inv of invoices) {
      const key = inv.account_number ?? `#${inv.id}`;
      const list = map.get(key) ?? [];
      list.push(inv);
      map.set(key, list);
    }
    for (const [, list] of map) {
      list.sort((a, b) => periodKey(a).localeCompare(periodKey(b)));
    }
    return map;
  }, [invoices]);

  const accountKeys = useMemo(() => Array.from(accounts.keys()), [accounts]);

  useEffect(() => {
    if (accountKeys.length > 0 && selectedAccount === null) {
      setSelectedAccount(accountKeys[0]);
    }
  }, [accountKeys, selectedAccount]);

  const selectedInvoices = useMemo(
    () => (selectedAccount ? (accounts.get(selectedAccount) ?? []) : []),
    [accounts, selectedAccount],
  );

  const chartDataByAccount = useMemo(() => {
    const result: { account: string; points: ChartPoint[] }[] = [];
    for (const [account, list] of accounts) {
      const points: ChartPoint[] = list
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

  const serviceTrends = useMemo(() => {
    if (!selectedInvoices.length) return [];
    const map = new Map<string, ServiceRow[]>();
    for (const inv of selectedInvoices) {
      const period = periodLabel(inv);
      for (const item of inv.line_items) {
        const list = map.get(item.service_name) ?? [];
        list.push({
          period,
          tariff: item.tariff != null ? parseFloat(item.tariff) : null,
          amount: item.amount != null ? parseFloat(item.amount) : null,
          quantity: item.quantity != null ? parseFloat(item.quantity) : null,
          unit: item.unit ?? null,
        });
        map.set(item.service_name, list);
      }
    }
    return Array.from(map.entries()).map(([service, rows]) => ({ service, rows }));
  }, [selectedInvoices]);

  // Тарифные строки из выбранного счёта: по каждой услуге берём последние два
  // тарифа с ненулевым значением и вычисляем % изменения.
  const tariffRows = useMemo((): TariffRow[] => {
    if (!selectedInvoices.length) return [];
    const map = new Map<string, { unit: string | null; tariffs: number[] }>();
    for (const inv of selectedInvoices) {
      for (const item of inv.line_items) {
        if (item.tariff == null) continue;
        const tariff = parseFloat(item.tariff);
        if (!isFinite(tariff)) continue;
        const entry = map.get(item.service_name) ?? { unit: item.unit ?? null, tariffs: [] };
        entry.tariffs.push(tariff);
        map.set(item.service_name, entry);
      }
    }
    return Array.from(map.entries()).map(([serviceName, { unit, tariffs }]) => {
      const last = tariffs[tariffs.length - 1] ?? null;
      const prev = tariffs.length >= 2 ? tariffs[tariffs.length - 2] : null;
      const changePct =
        last != null && prev != null && prev !== 0
          ? Math.round(((last - prev) / prev) * 10000) / 100
          : null;
      return { serviceName, unit, lastTariff: last, prevTariff: prev, changePct };
    });
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

      {/* ── Секция 1: Сумма к оплате по счетам ── */}
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

      {/* ── Секции 2 и 3: привязаны к выбранному счёту ── */}
      {accountKeys.length > 0 && (
        <>
          <div className={styles.sectionHeader} style={{ marginBottom: "1.25rem" }}>
            <h2 className={styles.sectionTitle} style={{ marginBottom: 0 }}>
              Лицевой счёт:
            </h2>
            <div className={styles.accountPicker}>
              <select
                className={styles.pickerSelect}
                value={selectedAccount ?? ""}
                onChange={(e) => setSelectedAccount(e.target.value)}
              >
                {accountKeys.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </div>
          </div>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Динамика тарифов и сумм по услугам</h2>
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

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>Динамика тарифов</h2>
            <TariffDynamicsTable rows={tariffRows} />
          </section>
        </>
      )}
    </div>
  );
}
