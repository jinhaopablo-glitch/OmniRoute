import { BarChart, type Point } from "../components/BarChart";
import { ErrorBox, Loading, PageHead, Stat } from "../components/ui";
import { fmtDate, fmtEur, fmtNum, fmtUsd, madridDay } from "../lib/format";
import { supabase } from "../lib/supabase";
import type { Metric } from "../lib/types";
import { unwrap, useData } from "../lib/useData";

const DAYS = 30;

export function Estadisticas() {
  const state = useData(async () => {
    const since = new Date(Date.now() - DAYS * 86_400_000);
    const [metrics, runs, content] = await Promise.all([
      supabase.from("metrics_daily").select("*").gte("day", madridDay(since)).order("day"),
      supabase.from("agent_runs").select("created_at, cost_usd").gte("created_at", since.toISOString()),
      supabase
        .from("content_items")
        .select("kind, status")
        .gte("created_at", since.toISOString()),
    ]);
    return {
      metrics: unwrap(metrics) as Metric[],
      runs: unwrap(runs) as { created_at: string; cost_usd: string }[],
      content: unwrap(content) as { kind: string; status: string }[],
    };
  });

  const d = state.data;
  const days = Array.from({ length: DAYS }, (_, i) => madridDay(new Date(Date.now() - (DAYS - 1 - i) * 86_400_000)));
  const series = (source: string, key: string): Point[] =>
    days.map((day) => {
      const m = d?.metrics.find((x) => x.source === source && x.day === day);
      return { label: fmtDate(day), value: Number(m?.metrics[key] ?? 0) };
    });
  const spend: Point[] = days.map((day) => ({
    label: fmtDate(day),
    value: (d?.runs ?? []).filter((r) => madridDay(new Date(r.created_at)) === day).reduce((a, r) => a + Number(r.cost_usd), 0),
  }));
  const sum = (pts: Point[]) => pts.reduce((a, p) => a + p.value, 0);
  const revenue = series("shopify", "revenue_eur");
  const orders = series("shopify", "orders");
  const published = (d?.content ?? []).filter((c) => c.status === "published").length;
  const videos = (d?.content ?? []).filter((c) => c.kind === "video").length;

  return (
    <>
      <PageHead title="Estadísticas" subtitle={`Últimos ${DAYS} días.`} />
      <ErrorBox error={state.error} />
      {state.loading && !d ? (
        <Loading lines={6} />
      ) : (
        <>
          <div className="grid k4 keep2">
            <Stat label="Ventas" value={fmtEur(sum(revenue))} hint={`${fmtNum(sum(orders))} pedidos`} />
            <Stat
              label="Ticket medio"
              value={fmtEur(sum(orders) ? sum(revenue) / sum(orders) : 0)}
              hint="Ventas / pedidos"
            />
            <Stat label="Vídeos generados" value={fmtNum(videos)} hint={`${fmtNum(published)} publicados`} />
            <Stat label="Gasto de IA" value={fmtUsd(sum(spend))} hint="Claude + búsquedas web" />
          </div>
          <div className="grid k2 section">
            <BarChart title="Ventas diarias (€)" points={revenue} format={(v) => fmtEur(v)} />
            <BarChart title="Pedidos diarios" points={orders} format={(v) => fmtNum(Math.round(v))} />
            <BarChart title="Alcance diario de Instagram" points={series("instagram", "reach")} format={(v) => fmtNum(Math.round(v))} />
            <BarChart title="Gasto diario de IA (USD)" points={spend} format={(v) => fmtUsd(v)} color="#C66A3D" />
          </div>
        </>
      )}
    </>
  );
}
