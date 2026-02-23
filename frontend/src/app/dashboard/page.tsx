"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { type Invoice, getInvoices, uploadInvoice } from "@/lib/api";
import { clearTokens } from "@/lib/auth";
import styles from "./dashboard.module.css";

const STATUS_LABELS: Record<string, string> = {
  processing: "Обрабатывается",
  processed: "Обработан",
  failed: "Ошибка",
};

const PAYMENT_LABELS: Record<string, string> = {
  unpaid: "Не оплачен",
  partially_paid: "Частично оплачен",
  paid: "Оплачен",
};

const MONTH_NAMES = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

type InvoiceGroup = {
  key: string;
  label: string;
  totalDue: number | null;
  invoices: Invoice[];
};

function groupByPeriod(invoices: Invoice[]): InvoiceGroup[] {
  const map = new Map<string, Invoice[]>();

  for (const inv of invoices) {
    const key =
      inv.period_year != null && inv.period_month != null
        ? `${inv.period_year}-${String(inv.period_month).padStart(2, "0")}`
        : "__no_period__";
    const group = map.get(key) ?? [];
    group.push(inv);
    map.set(key, group);
  }

  const groups: InvoiceGroup[] = [];

  for (const [key, items] of map.entries()) {
    if (key === "__no_period__") continue;
    const [year, monthStr] = key.split("-");
    const month = parseInt(monthStr, 10);
    const label = `${MONTH_NAMES[month - 1]} ${year}`;
    const totalDue = items.some((i) => i.amount_due != null)
      ? items.reduce((sum, i) => sum + (i.amount_due ? parseFloat(i.amount_due) : 0), 0)
      : null;
    groups.push({ key, label, totalDue, invoices: items });
  }

  // Sort groups newest first
  groups.sort((a, b) => b.key.localeCompare(a.key));

  // Append "no period" group at the end if exists
  const noPeriod = map.get("__no_period__");
  if (noPeriod) {
    groups.push({ key: "__no_period__", label: "Без периода", totalDue: null, invoices: noPeriod });
  }

  return groups;
}

export default function DashboardPage() {
  const router = useRouter();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function loadInvoices() {
    try {
      const data = await getInvoices();
      setInvoices(data.results);
    } catch {
      setError("Не удалось загрузить квитанции");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInvoices();
  }, []);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const invoice = await uploadInvoice(file);
      setInvoices((prev) => [invoice, ...prev]);
    } catch {
      setError("Ошибка при загрузке файла");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function handleLogout() {
    clearTokens();
    router.push("/login");
  }

  const groups = groupByPeriod(invoices);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.heading}>Квитанции ЖКХ</h1>
        <div className={styles.actions}>
          <label className={`${styles.uploadLabel} ${uploading ? styles.uploading : ""}`}>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              onChange={handleUpload}
              className={styles.hiddenInput}
              disabled={uploading}
            />
            {uploading ? "Загрузка..." : "+ Загрузить квитанцию"}
          </label>
          <button onClick={handleLogout} className={styles.logoutBtn}>
            Выйти
          </button>
        </div>
      </header>

      {error && <p className={styles.error}>{error}</p>}

      {loading ? (
        <p className={styles.placeholder}>Загрузка...</p>
      ) : invoices.length === 0 ? (
        <p className={styles.placeholder}>Нет квитанций. Загрузите PDF-файл.</p>
      ) : (
        <div className={styles.groups}>
          {groups.map((group) => (
            <section key={group.key} className={styles.group}>
              <div className={styles.groupHeader}>
                <h2 className={styles.groupTitle}>{group.label}</h2>
                {group.totalDue != null && (
                  <span className={styles.groupTotal}>
                    Итого: {group.totalDue.toLocaleString("ru-RU", { minimumFractionDigits: 2 })} ₽
                  </span>
                )}
              </div>
              <div className={styles.grid}>
                {group.invoices.map((inv) => (
                  <a key={inv.id} href={`/invoices/${inv.id}`} className={styles.card}>
                    <div className={styles.cardHeader}>
                      <span className={styles.provider}>
                        {inv.provider_name ?? "Поставщик неизвестен"}
                      </span>
                      <span className={`${styles.badge} ${styles[`badge__${inv.status}`]}`}>
                        {STATUS_LABELS[inv.status]}
                      </span>
                    </div>
                    <div className={styles.cardBody}>
                      {inv.amount_due && (
                        <p className={styles.amount}>
                          {parseFloat(inv.amount_due).toLocaleString("ru-RU", {
                            minimumFractionDigits: 2,
                          })}{" "}
                          ₽
                        </p>
                      )}
                      <span className={`${styles.payBadge} ${styles[`pay__${inv.payment_status}`]}`}>
                        {PAYMENT_LABELS[inv.payment_status]}
                      </span>
                    </div>
                    <p className={styles.date}>
                      {new Date(inv.created_at).toLocaleDateString("ru-RU")}
                    </p>
                  </a>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
