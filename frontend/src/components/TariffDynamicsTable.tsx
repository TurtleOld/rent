import { type Service } from "@/lib/api";
import styles from "@/app/reports/reports.module.css";

export interface TariffRow {
  service: Service;
  lastTariff: string | null;
  changePct: number | null;
}

interface Props {
  rows: TariffRow[];
}

function rowClass(pct: number | null): string {
  if (pct == null) return styles.tariffRow;
  if (pct > 25) return `${styles.tariffRow} ${styles.rowDanger}`;
  if (pct > 10) return `${styles.tariffRow} ${styles.rowWarn}`;
  return styles.tariffRow;
}

function changeClass(pct: number | null): string {
  if (pct == null) return styles.changeNeutral;
  if (pct > 0) return styles.changeUp;
  if (pct < 0) return styles.changeDown;
  return styles.changeNeutral;
}

function fmtChange(pct: number | null): string {
  if (pct == null) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

export default function TariffDynamicsTable({ rows }: Props) {
  if (rows.length === 0) return <p className={styles.empty}>Нет данных о тарифах.</p>;

  const sorted = [...rows].sort((a, b) => (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity));

  return (
    <div className={styles.tariffTable}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.th}>Услуга</th>
            <th className={styles.th}>Ед.</th>
            <th className={styles.th}>Тариф (текущий)</th>
            <th className={styles.th}>Изменение от пред. месяца</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(({ service, lastTariff, changePct }) => (
            <tr key={service.id} className={rowClass(changePct)}>
              <td className={styles.td}>{service.canonical_name}</td>
              <td className={styles.td}>{service.unit ?? "—"}</td>
              <td className={styles.td}>{lastTariff ?? "—"}</td>
              <td className={`${styles.td} ${changeClass(changePct)}`}>{fmtChange(changePct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
