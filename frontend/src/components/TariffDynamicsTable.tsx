import styles from "@/app/reports/reports.module.css";
import { type TariffPoint, type TariffRow } from "@/lib/reports";

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

function TariffCell({ point }: { point: TariffPoint | null }) {
  if (!point) return <td className={styles.td}>—</td>;
  return (
    <td className={styles.td}>
      {point.ambiguous ? "разные значения" : fmtTariff(point.tariff)}
      <span className={styles.periodLabel}>{point.periodLabel}</span>
    </td>
  );
}

export default function TariffDynamicsTable({ rows }: Props) {
  if (rows.length === 0) return <p className={styles.empty}>Нет данных о тарифах.</p>;

  const sorted = [...rows].sort((a, b) => (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity));

  return (
    <>
      <div className={styles.tariffTable}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.th}>Услуга</th>
              <th className={styles.th}>Ед.</th>
              <th className={styles.th}>Тариф (последний доступный период)</th>
              <th className={styles.th}>Тариф (предыдущий доступный период)</th>
              <th className={styles.th}>Изменение</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(({ serviceName, unit, current, previous, changePct, note }) => (
              <tr key={serviceName} className={rowClass(changePct)}>
                <td className={styles.td}>{serviceName}</td>
                <td className={styles.td}>{unit ?? "—"}</td>
                <TariffCell point={current} />
                <TariffCell point={previous} />
                <td className={`${styles.td} ${changeClass(changePct)}`}>
                  {fmtChange(changePct)}
                  {note && <span className={styles.tariffNote}>{note}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.tariffCaption}>
        Для каждой услуги сравниваются последний и предыдущий доступные периоды в выбранном лицевом
        счёте; при пропуске месяца сравниваются фактические периоды.
      </p>
    </>
  );
}
