"use client";

import { useMemo, useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import type { PriceRow } from "@/lib/types";
import { hotelKey } from "@/lib/format";

type Props = {
  rows: PriceRow[];
  hotels: { brand: string; hotelName: string; hotelId: string; city: string }[];
};

const COLORS = [
  "#3d5afe", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6",
  "#06b6d4", "#ec4899", "#84cc16", "#f43f5e", "#6366f1",
];

function yearMonth(date: string) {
  return date.slice(0, 7);
}

export function MonthlyChart({ rows, hotels }: Props) {
  const defaultSelection = hotels.slice(0, 5).map((h) => hotelKey(h.brand, h.hotelId));
  const [selection, setSelection] = useState<Set<string>>(new Set(defaultSelection));

  const toggle = (k: string) => {
    const next = new Set(selection);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setSelection(next);
  };

  const data = useMemo(() => {
    // buckets: { month: "YYYY-MM", [hotelKey]: avgPrice }
    const buckets = new Map<string, Record<string, number | string>>();
    const counts = new Map<string, Map<string, { sum: number; n: number }>>();

    for (const r of rows) {
      if (r.price == null || !r.available) continue;
      const key = hotelKey(r.brand, r.hotelId);
      if (!selection.has(key)) continue;
      const ym = yearMonth(r.date);
      if (!counts.has(ym)) counts.set(ym, new Map());
      const inner = counts.get(ym)!;
      const agg = inner.get(key) ?? { sum: 0, n: 0 };
      agg.sum += r.price;
      agg.n += 1;
      inner.set(key, agg);
    }

    const months = Array.from(counts.keys()).sort();
    for (const ym of months) {
      const row: Record<string, number | string> = { month: ym };
      for (const [k, { sum, n }] of counts.get(ym)!) {
        row[k] = Math.round((sum / n) * 100) / 100;
      }
      buckets.set(ym, row);
    }
    return months.map((m) => buckets.get(m)!);
  }, [rows, selection]);

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="text-sm text-ink/60 mb-2">
          Toggle hotels:
        </div>
        <div className="flex flex-wrap gap-2">
          {hotels.map((h, i) => {
            const k = hotelKey(h.brand, h.hotelId);
            const active = selection.has(k);
            return (
              <button
                key={k}
                onClick={() => toggle(k)}
                className="text-xs px-2 py-1 rounded-full border"
                style={{
                  borderColor: COLORS[i % COLORS.length],
                  backgroundColor: active ? COLORS[i % COLORS.length] : "transparent",
                  color: active ? "white" : COLORS[i % COLORS.length],
                }}
              >
                [{h.brand}] {h.hotelName}
              </button>
            );
          })}
        </div>
      </div>

      <div className="card">
        <div className="h-[480px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="month" />
              <YAxis
                tickFormatter={(v) => `${v}€`}
                width={60}
              />
              <Tooltip formatter={(v: number) => `${v}€`} />
              <Legend />
              {hotels.map((h, i) => {
                const k = hotelKey(h.brand, h.hotelId);
                if (!selection.has(k)) return null;
                return (
                  <Line
                    key={k}
                    type="monotone"
                    dataKey={k}
                    name={`[${h.brand}] ${h.hotelName}`}
                    stroke={COLORS[i % COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                );
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
