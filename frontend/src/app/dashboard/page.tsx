"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { type Invoice, getInvoicesAll, uploadInvoice } from "@/lib/api";
import { clearTokens } from "@/lib/auth";
import { unknownAmountNote } from "@/lib/reports";
import styles from "./dashboard.module.css";

const STATUS_LABELS: Record<string, string> = {
  processing: "Обрабатывается",
  processed: "Обработан",
  failed: "Ошибка",
};

const PAYMENT_LABELS: Record<string, string> = {
  unpaid: "Не оплачена",
  partially_paid: "Частично оплачена",
  paid: "Оплачена",
  amount_unknown: "Сумма не распознана",
};

const MONTH_NAMES = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

type InvoiceGroup = {
  key: string;
  label: string;
  totalDue: number | null;
  unknownNote: string | null;
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
    const totalDue = items.reduce((sum, i) => {
      const v = i.amount_due_without_insurance ?? i.amount_due;
      return sum + (v ? parseFloat(v) : 0);
    }, 0);
    groups.push({ key, label, totalDue, unknownNote: unknownAmountNote(items), invoices: items });
  }

  // Sort groups newest first
  groups.sort((a, b) => b.key.localeCompare(a.key));

  // Append "no period" group at the end if exists
  const noPeriod = map.get("__no_period__");
  if (noPeriod) {
    groups.push({ key: "__no_period__", label: "Без периода", totalDue: null, unknownNote: null, invoices: noPeriod });
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
      setInvoices(await getInvoicesAll());
    } catch {
      setError("Не удалось загрузить квитанции");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInvoices();
  }, []);

  // Поллинг пока есть хотя бы один инвойс в статусе processing
  useEffect(() => {
    const hasProcessing = invoices.some((inv) => inv.status === "processing");
    if (!hasProcessing) return;
    const timer = setTimeout(() => void loadInvoices(), 3000);
    return () => clearTimeout(timer);
  }, [invoices]);

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

  async function handleLogout() {
    await clearTokens();
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
          <button onClick={() => router.push("/reports")} className={styles.reportsBtn}>
            Отчёты
          </button>
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
                    {group.unknownNote && ` (${group.unknownNote})`}
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
                      {inv.amount_due_without_insurance != null || inv.amount_due_with_insurance != null ? (
                        <>
                          {inv.amount_due_without_insurance != null && (
                            <p className={styles.amount}>
                              {parseFloat(inv.amount_due_without_insurance).toLocaleString("ru-RU", {
                                minimumFractionDigits: 2,
                              })}{" "}
                              ₽{" "}
                              <span className={styles.amountLabel}>без страх.</span>
                            </p>
                          )}
                          {inv.amount_due_with_insurance != null && (
                            <p className={styles.amountSecondary}>
                              {parseFloat(inv.amount_due_with_insurance).toLocaleString("ru-RU", {
                                minimumFractionDigits: 2,
                              })}{" "}
                              ₽{" "}
                              <span className={styles.amountLabel}>со страх.</span>
                            </p>
                          )}
                        </>
                      ) : inv.amount_due ? (
                        <p className={styles.amount}>
                          {parseFloat(inv.amount_due).toLocaleString("ru-RU", {
                            minimumFractionDigits: 2,
                          })}{" "}
                          ₽
                        </p>
                      ) : null}
                      <span className={`${styles.payBadge} ${styles[`pay__${inv.payment_status}`]}`}>
                        {PAYMENT_LABELS[inv.payment_status]}
                      </span>
                      {inv.payment_status === "amount_unknown" && (
                        <span className={styles.amountLabel}>
                          {" "}внесено{" "}
                          {parseFloat(inv.total_paid).toLocaleString("ru-RU", { minimumFractionDigits: 2 })} ₽
                        </span>
                      )}
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
