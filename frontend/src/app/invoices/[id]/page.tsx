"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  type Invoice,
  type Payment,
  createPayment,
  deleteInvoice,
  getInvoice,
  getPayments,
  patchInvoice,
} from "@/lib/api";
import styles from "./invoice.module.css";

const STATUS_LABELS: Record<string, string> = {
  processing: "Обрабатывается",
  processed: "Обработан",
  failed: "Ошибка",
};

const PAYMENT_STATUS_LABELS: Record<string, string> = {
  unpaid: "Не оплачен",
  partially_paid: "Частично оплачен",
  paid: "Оплачен",
};

type EditableFields = Pick<
  Invoice,
  "provider_name" | "account_number" | "payer_name" | "address" | "amount_due"
>;

const EDITABLE_LABELS: { field: keyof EditableFields; label: string }[] = [
  { field: "provider_name", label: "Поставщик" },
  { field: "account_number", label: "Лицевой счёт" },
  { field: "payer_name", label: "Плательщик" },
  { field: "address", label: "Адрес" },
  { field: "amount_due", label: "К оплате (₽)" },
];

export default function InvoiceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = Number(params.id);

  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editData, setEditData] = useState<EditableFields>({
    provider_name: null,
    account_number: null,
    payer_name: null,
    address: null,
    amount_due: null,
  });
  const [payAmount, setPayAmount] = useState("");
  const [payDate, setPayDate] = useState(new Date().toISOString().split("T")[0]);
  const [payNote, setPayNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let pollTimer: ReturnType<typeof setTimeout> | null = null;

    async function load(isInitial = false) {
      try {
        const inv = await getInvoice(id);
        setInvoice(inv);
        setEditData({
          provider_name: inv.provider_name,
          account_number: inv.account_number,
          payer_name: inv.payer_name,
          address: inv.address,
          amount_due: inv.amount_due,
        });
        if (isInitial) {
          const pays = await getPayments(id);
          setPayments(pays);
        }
        if (inv.status === "processing") {
          pollTimer = setTimeout(() => void load(false), 3000);
        }
      } catch {
        setError("Не удалось загрузить квитанцию");
      } finally {
        if (isInitial) setLoading(false);
      }
    }

    void load(true);

    return () => {
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [id]);

  async function handleSaveEdit() {
    setSaving(true);
    setError(null);
    try {
      const updated = await patchInvoice(id, editData);
      setInvoice(updated);
      setEditing(false);
    } catch {
      setError("Ошибка при сохранении");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddPayment() {
    if (!payAmount) return;
    setSaving(true);
    setError(null);
    try {
      const payment = await createPayment(id, {
        amount: payAmount,
        payment_date: payDate,
        ...(payNote ? { note: payNote } : {}),
      });
      setPayments((prev) => [payment, ...prev]);
      setPayAmount("");
      setPayNote("");
      const updated = await getInvoice(id);
      setInvoice(updated);
    } catch {
      setError("Ошибка при добавлении платежа");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Удалить квитанцию? Это действие нельзя отменить.")) return;
    setSaving(true);
    setError(null);
    try {
      await deleteInvoice(id);
      router.push("/dashboard");
    } catch {
      setError("Ошибка при удалении квитанции");
      setSaving(false);
    }
  }

  if (loading) return <div className={styles.loading}>Загрузка...</div>;
  if (!invoice) return <div className={styles.loading}>{error ?? "Квитанция не найдена"}</div>;

  const fmt = (v: string | null) =>
    v != null ? parseFloat(v).toLocaleString("ru-RU", { minimumFractionDigits: 2 }) + " ₽" : "—";

  return (
    <div className={styles.page}>
      <button onClick={() => router.back()} className={styles.back}>
        ← Назад
      </button>

      {error && <p className={styles.error}>{error}</p>}

      {/* Main info */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Данные квитанции</h2>
          <div className={styles.headerActions}>
            {invoice.status === "processed" && !editing && (
              <button onClick={() => setEditing(true)} className={styles.editBtn}>
                Редактировать
              </button>
            )}
            <button onClick={handleDelete} disabled={saving} className={styles.deleteBtn}>
              Удалить
            </button>
          </div>
        </div>

        {editing ? (
          <div className={styles.editForm}>
            {EDITABLE_LABELS.map(({ field, label }) => (
              <label key={field} className={styles.editLabel}>
                {label}
                <input
                  value={(editData[field] as string) ?? ""}
                  onChange={(e) =>
                    setEditData((prev) => ({ ...prev, [field]: e.target.value || null }))
                  }
                  className={styles.editInput}
                />
              </label>
            ))}
            <div className={styles.editActions}>
              <button onClick={handleSaveEdit} disabled={saving} className={styles.saveBtn}>
                {saving ? "Сохранение..." : "Сохранить"}
              </button>
              <button onClick={() => setEditing(false)} className={styles.cancelBtn}>
                Отмена
              </button>
            </div>
          </div>
        ) : (
          <dl className={styles.details}>
            <dt>Статус</dt>
            <dd>{STATUS_LABELS[invoice.status]}</dd>
            <dt>Поставщик</dt>
            <dd>{invoice.provider_name ?? "—"}</dd>
            <dt>Лицевой счёт</dt>
            <dd>{invoice.account_number ?? "—"}</dd>
            <dt>Плательщик</dt>
            <dd>{invoice.payer_name ?? "—"}</dd>
            <dt>Адрес</dt>
            <dd>{invoice.address ?? "—"}</dd>
            <dt>Период</dt>
            <dd>
              {invoice.period_month != null && invoice.period_year != null
                ? `${invoice.period_month}/${invoice.period_year}`
                : "—"}
            </dd>
            <dt>Начислено</dt>
            <dd>{fmt(invoice.amount_charged)}</dd>
            {invoice.amount_recalculation && (
              <>
                <dt>Перерасчёт</dt>
                <dd>{fmt(invoice.amount_recalculation)}</dd>
              </>
            )}
            {invoice.amount_due_without_insurance != null || invoice.amount_due_with_insurance != null ? (
              <>
                {invoice.amount_due_without_insurance != null && (
                  <>
                    <dt>К оплате (без страхования)</dt>
                    <dd>{fmt(invoice.amount_due_without_insurance)}</dd>
                  </>
                )}
                {invoice.amount_due_with_insurance != null && (
                  <>
                    <dt>К оплате (со страхованием)</dt>
                    <dd>{fmt(invoice.amount_due_with_insurance)}</dd>
                  </>
                )}
              </>
            ) : (
              <>
                <dt>К оплате</dt>
                <dd>{fmt(invoice.amount_due)}</dd>
              </>
            )}
            <dt>Статус оплаты</dt>
            <dd>{PAYMENT_STATUS_LABELS[invoice.payment_status]}</dd>
            <dt>Оплачено (пользователь)</dt>
            <dd>{fmt(invoice.total_paid)}</dd>
            {invoice.confidence != null && (
              <>
                <dt>Уверенность AI</dt>
                <dd>{Math.round(invoice.confidence * 100)}%</dd>
              </>
            )}
            {invoice.warnings.length > 0 && (
              <>
                <dt>Предупреждения</dt>
                <dd>
                  <ul className={styles.warnings}>
                    {invoice.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </dd>
              </>
            )}
            {invoice.status === "failed" && invoice.error_message && (
              <>
                <dt>Ошибка обработки</dt>
                <dd className={styles.errorText}>{invoice.error_message}</dd>
              </>
            )}
          </dl>
        )}
      </div>

      {/* Line items */}
      {invoice.line_items.length > 0 && (
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>Услуги</h2>
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Услуга</th>
                  <th>Ед.</th>
                  <th>Кол-во</th>
                  <th>Тариф</th>
                  <th>Начислено</th>
                  <th>Перерасчёт</th>
                  <th>Задолж./Переплата</th>
                  <th>Итого</th>
                  <th>Счётчик</th>
                </tr>
              </thead>
              <tbody>
                {invoice.line_items.map((item) => (
                  <tr key={item.id}>
                    <td>{item.service_name}</td>
                    <td>{item.unit ?? "—"}</td>
                    <td>{item.quantity ?? "—"}</td>
                    <td>{item.tariff ?? "—"}</td>
                    <td>{item.amount_charged != null ? fmt(item.amount_charged) : "—"}</td>
                    <td>{item.recalculation != null ? fmt(item.recalculation) : "—"}</td>
                    <td>{item.debt != null ? fmt(item.debt) : "—"}</td>
                    <td>{item.amount != null ? fmt(item.amount) : "—"}</td>
                    <td>{item.meter_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Payments */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Платежи</h2>
        <div className={styles.paymentForm}>
          <input
            type="number"
            placeholder="Сумма (₽)"
            value={payAmount}
            onChange={(e) => setPayAmount(e.target.value)}
            min="0.01"
            step="0.01"
            className={styles.payInput}
          />
          <input
            type="date"
            value={payDate}
            onChange={(e) => setPayDate(e.target.value)}
            className={styles.payInput}
          />
          <input
            type="text"
            placeholder="Примечание (необязательно)"
            value={payNote}
            onChange={(e) => setPayNote(e.target.value)}
            className={`${styles.payInput} ${styles.payNoteInput}`}
          />
          <button
            onClick={handleAddPayment}
            disabled={saving || !payAmount}
            className={styles.saveBtn}
          >
            Добавить
          </button>
        </div>
        {payments.length === 0 ? (
          <p className={styles.noPayments}>Платежей ещё нет</p>
        ) : (
          <ul className={styles.paymentList}>
            {payments.map((p) => (
              <li key={p.id} className={styles.paymentItem}>
                <span className={styles.paymentDate}>
                  {new Date(p.payment_date).toLocaleDateString("ru-RU")}
                </span>
                <span className={styles.paymentAmount}>{fmt(p.amount)}</span>
                {p.note && <span className={styles.paymentNote}>{p.note}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
