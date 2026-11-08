import { useState } from "react";

export interface Point {
  label: string; // etiqueta del eje (p. ej. "3 nov")
  value: number;
}

/**
 * Gráfica de barras de UNA serie (una medida por gráfica, nunca dos escalas).
 * Barras finas con extremo redondeado, cuadrícula discreta, tooltip al pasar
 * el ratón o tocar, y vista de tabla accesible.
 */
export function BarChart({
  title,
  points,
  format,
  color = "#203D2B",
}: {
  title: string;
  points: Point[];
  format: (v: number) => string;
  color?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const W = 640;
  const H = 220;
  const pad = { l: 64, r: 8, t: 12, b: 26 };
  const max = Math.max(1, ...points.map((p) => p.value));
  const niceMax = niceCeil(max);
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const step = points.length ? iw / points.length : iw;
  const bw = Math.max(3, Math.min(28, step * 0.62));
  const ticks = [0, 0.5, 1].map((f) => niceMax * f);
  const labelEvery = Math.ceil(points.length / 8);

  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        <button className="btn small" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? "Ver gráfica" : "Ver tabla"}
        </button>
      </div>
      {points.length === 0 ? (
        <div className="empty">Sin datos todavía</div>
      ) : table ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Día</th>
                <th>Valor</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.label}>
                  <td>{p.label}</td>
                  <td>{format(p.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart" onMouseLeave={() => setHover(null)}>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. Máximo ${format(max)}.`}>
            {ticks.map((t) => {
              const y = pad.t + ih - (t / niceMax) * ih;
              return (
                <g key={t}>
                  <line className="chart-grid" x1={pad.l} x2={W - pad.r} y1={y} y2={y} />
                  {t > 0 && (
                    <text className="chart-axis" x={pad.l - 8} y={y + 4} textAnchor="end">
                      {format(t)}
                    </text>
                  )}
                </g>
              );
            })}
            {points.map((p, i) => {
              const h = (p.value / niceMax) * ih;
              const x = pad.l + i * step + (step - bw) / 2;
              const y = pad.t + ih - h;
              const r = Math.min(4, bw / 2, h);
              return (
                <g key={p.label}>
                  {/* zona de interacción mayor que la barra */}
                  <rect
                    x={pad.l + i * step}
                    y={pad.t}
                    width={step}
                    height={ih}
                    fill="transparent"
                    onMouseEnter={() => setHover(i)}
                    onTouchStart={() => setHover(i)}
                  />
                  {h > 0 && (
                    <path
                      d={`M${x},${pad.t + ih} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${pad.t + ih} Z`}
                      fill={color}
                      opacity={hover === null || hover === i ? 1 : 0.45}
                      pointerEvents="none"
                    />
                  )}
                  {i % labelEvery === 0 && (
                    <text className="chart-axis" x={pad.l + i * step + step / 2} y={H - 8} textAnchor="middle">
                      {p.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {hover !== null && points[hover] && (
            <div
              className="tip"
              style={{
                left: `${((pad.l + hover * step + step / 2) / W) * 100}%`,
                top: `${((pad.t + ih - (points[hover].value / niceMax) * ih) / H) * 100}%`,
              }}
            >
              <strong>{format(points[hover].value)}</strong> · {points[hover].label}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function niceCeil(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / exp;
  const nice = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return nice * exp;
}
