import styles from "@/app/reports/reports.module.css";

export interface ChartPoint {
  x: number;
  y: number;
  label: string;
  value: number;
}

interface Props {
  points: ChartPoint[];
  color?: string;
  unit?: string;
}

const W = 480;
const H = 180;
const PAD = { top: 16, right: 16, bottom: 36, left: 56 };

export default function LineChart({ points, color = "#3b82f6", unit = "₽" }: Props) {
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

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => minVal + (range * i) / ticks);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={styles.chartSvg}>
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
          <text x={PAD.left - 6} y={toY(v) + 4} textAnchor="end" className={styles.chartTick}>
            {v.toLocaleString("ru-RU", { maximumFractionDigits: 2 })}
          </text>
        </g>
      ))}

      <path d={pathD} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" />

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
