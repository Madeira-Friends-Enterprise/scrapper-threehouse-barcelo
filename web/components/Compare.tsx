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
import { formatCurrency, formatDate, hotelKey } from "@/lib/format";

type Props = {
  rows: PriceRow[];
  hotels: { brand: string; hotelName: string; hotelId: string; city: string }[];
};

export function Compare({ rows, hotels }: Props) {
  const threehouse = hotels.filter((h) => h.brand === "Threehouse");
  const barcelo = hotels.filter((h) => h.brand === "Barceló");

  const [leftKey, setLeftKey] = useState<string>(
    threehouse[0] ? hotelKey(threehouse[0].brand, threehouse[0].hotelId) : "",
  );
  const [rightKey, setRightKey] = useState<string>(
    barcelo[0] ? hotelKey(barcelo[0].brand, barcelo[0].hotelId) : "",
  );

  const mapFor = (key: string) => {
    const m = new Map<string, number | null>();
    for (const r of rows) {
      if (hotelKey(r.brand, r.hotelId) !== key) continue;
      if (!r.available) continue;
      m.set(r.date, r.price);
    }
    return m;
  };

  const series = useMemo(() => {
    const left = mapFor(leftKey);
    const right = mapFor(rightKey);
    const allDates = Array.from(new Set([...left.keys(), ...right.keys()])).sort();
    return allDates.map((d) => ({
      date: d,
      left: left.get(d) ?? null,
      right: right.get(d) ?? null,
    }));
  }, [rows, leftKey, rightKey]);

  const commonDays = series.filter((s) => s.left != null && s.right != null);
  const avgLeft = commonDays.length
    ? commonDays.reduce((a, b) => a + (b.left ?? 0), 0) / commonDays.length
    : null;
  const avgRight = commonDays.length
    ? commonDays.reduce((a, b) => a + (b.right ?? 0), 0) / commonDays.length
    : null;
  const diff =
    avgLeft != null && avgRight != null ? avgLeft - avgRight : null;

  const leftHotel = hotels.find((h) => hotelKey(h.brand, h.hotelId) === leftKey);
  const rightHotel = hotels.find((h) => hotelKey(h.brand, h.hotelId) === rightKey);

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Threehouse</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 w-full"
            value={leftKey}
            onChange={(e) => setLeftKey(e.target.value)}
          >
            {threehouse.map((h) => (
              <option key={hotelKey(h.brand, h.hotelId)} value={hotelKey(h.brand, h.hotelId)}>
                {h.hotelName}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Barceló</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 w-full"
            value={rightKey}
            onChange={(e) => setRightKey(e.target.value)}
          >
            {barcelo.map((h) => (
              <option key={hotelKey(h.brand, h.hotelId)} value={hotelKey(h.brand, h.hotelId)}>
                {h.hotelName} {h.city ? `· ${h.city}` : ""}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <StatCard label={`Avg ${leftHotel?.hotelName ?? ""}`} value={formatCurrency(avgLeft)} tint="amber" />
        <StatCard label={`Avg ${rightHotel?.hotelName ?? ""}`} value={formatCurrency(avgRight)} tint="blue" />
        <StatCard
          label="Avg difference (TH − Barceló)"
          value={diff == null ? "—" : `${diff >= 0 ? "+" : ""}${formatCurrency(diff)}`}
          tint={diff == null ? "neutral" : diff >= 0 ? "red" : "green"}
        />
      </div>

      <div className="card">
        <div className="h-[460px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis dataKey="date" tickFormatter={(v) => formatDate(v)} minTickGap={40} />
              <YAxis tickFormatter={(v) => `${v}€`} width={60} />
              <Tooltip
                labelFormatter={(v) => formatDate(String(v))}
                formatter={(v) => (v == null ? "—" : `${v}€`)}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="left"
                name={leftHotel?.hotelName ?? "Threehouse"}
                stroke="#f59e0b"
                strokeWidth={2}
                dot={false}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="right"
                name={rightHotel?.hotelName ?? "Barceló"}
                stroke="#3d5afe"
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 text-xs text-ink/50">
          {commonDays.length} days with a price in both hotels.
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, tint }: { label: string; value: string; tint: "amber" | "blue" | "red" | "green" | "neutral" }) {
  const tintClass = {
    amber: "bg-amber-50 border-amber-200",
    blue: "bg-blue-50 border-blue-200",
    red: "bg-rose-50 border-rose-200",
    green: "bg-emerald-50 border-emerald-200",
    neutral: "bg-black/5 border-black/10",
  }[tint];
  return (
    <div className={`card ${tintClass}`}>
      <div className="text-xs uppercase tracking-wide text-ink/60">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}
