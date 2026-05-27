import LineChart, { type ChartPoint } from "./LineChart";
import { showVolume } from "@/lib/reports";
import styles from "@/app/reports/reports.module.css";

export interface ServiceRow {
  period: string;
  tariff: number | null;
  amount: number | null;
  quantity: number | null;
  unit: string | null;
}

interface Props {
  service: string;
  rows: ServiceRow[];
}

export default function ServiceChart({ service, rows }: Props) {
  const unit = rows[0]?.unit ?? null;
  const hasVolume = rows.some((r) => r.quantity != null && showVolume(unit));

  const tariffPoints: ChartPoint[] = rows
    .map((r, i) => ({ x: i, y: 0, label: r.period, value: r.tariff ?? 0 }))
    .filter((_, i) => rows[i].tariff != null);

  const amountPoints: ChartPoint[] = rows
    .map((r, i) => ({ x: i, y: 0, label: r.period, value: r.amount ?? 0 }))
    .filter((_, i) => rows[i].amount != null);

  const volumePoints: ChartPoint[] = hasVolume
    ? rows
        .map((r, i) => ({ x: i, y: 0, label: r.period, value: r.quantity ?? 0 }))
        .filter((_, i) => rows[i].quantity != null)
    : [];

  const series: { label: string; points: ChartPoint[]; color: string; unit: string }[] = [];
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
