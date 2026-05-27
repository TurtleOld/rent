import styles from "@/app/reports/reports.module.css";

export interface TariffRow {
  serviceName: string;
  unit: string | null;
  prevTariff: number | null;
  lastTariff: number | null;
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

function fmtTariff(v: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
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
            <th className={styles.th}>Тариф (тек.)</th>
            <th className={styles.th}>Тариф (пред. мес.)</th>
            <th className={styles.th}>Изменение</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map(({ serviceName, unit, lastTariff, prevTariff, changePct }) => (
            <tr key={serviceName} className={rowClass(changePct)}>
              <td className={styles.td}>{serviceName}</td>
              <td className={styles.td}>{unit ?? "—"}</td>
              <td className={styles.td}>{fmtTariff(lastTariff)}</td>
              <td className={styles.td}>{fmtTariff(prevTariff)}</td>
              <td className={`${styles.td} ${changeClass(changePct)}`}>{fmtChange(changePct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
