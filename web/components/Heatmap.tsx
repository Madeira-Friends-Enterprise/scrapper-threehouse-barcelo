"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";
import type { PriceRow } from "@/lib/types";
import { formatCurrency, hotelKey } from "@/lib/format";

type Props = {
  rows: PriceRow[];
  hotels: { brand: string; hotelName: string; hotelId: string; city: string }[];
};

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const DOW_LABELS = ["M", "T", "W", "T", "F", "S", "S"]; // Monday-first

function monthDays(year: number, month: number): (Date | null)[] {
  // Returns a 6x7 grid, Monday-first
  const first = new Date(Date.UTC(year, month, 1));
  const dow = (first.getUTCDay() + 6) % 7; // 0=Mon
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < dow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(Date.UTC(year, month, d)));
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

function priceColor(price: number | null, min: number, max: number): string {
  if (price == null) return "bg-black/5 text-ink/30";
  if (max === min) return "bg-emerald-200";
  const t = (price - min) / (max - min);
  if (t < 0.2) return "bg-emerald-200 text-emerald-900";
  if (t < 0.4) return "bg-emerald-300 text-emerald-900";
  if (t < 0.6) return "bg-amber-200 text-amber-900";
  if (t < 0.8) return "bg-orange-300 text-orange-900";
  return "bg-rose-400 text-rose-900";
}

export function Heatmap({ rows, hotels }: Props) {
  const [selected, setSelected] = useState<string>(
    hotels[0] ? hotelKey(hotels[0].brand, hotels[0].hotelId) : "",
  );

  const hotelRows = useMemo(
    () => rows.filter((r) => hotelKey(r.brand, r.hotelId) === selected),
    [rows, selected],
  );

  const byDate = useMemo(() => {
    const m = new Map<string, PriceRow>();
    for (const r of hotelRows) m.set(r.date, r);
    return m;
  }, [hotelRows]);

  const { min, max } = useMemo(() => {
    const prices = hotelRows.map((r) => r.price).filter((x): x is number => x != null);
    return {
      min: prices.length ? Math.min(...prices) : 0,
      max: prices.length ? Math.max(...prices) : 0,
    };
  }, [hotelRows]);

  const months = useMemo(() => {
    if (hotelRows.length === 0) return [];
    const dates = hotelRows.map((r) => r.date).sort();
    const start = dates[0];
    const end = dates[dates.length - 1];
    const [sy, sm] = start.split("-").map(Number);
    const [ey, em] = end.split("-").map(Number);
    const out: { year: number; month: number }[] = [];
    let y = sy, m = sm - 1;
    while (y < ey || (y === ey && m <= em - 1)) {
      out.push({ year: y, month: m });
      m += 1;
      if (m > 11) { m = 0; y += 1; }
    }
    return out;
  }, [hotelRows]);

  const selectedHotel = hotels.find((h) => hotelKey(h.brand, h.hotelId) === selected);

  return (
    <div className="space-y-4">
      <div className="card flex flex-wrap items-center gap-3">
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Hotel</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 max-w-[320px]"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {hotels.map((h) => (
              <option key={hotelKey(h.brand, h.hotelId)} value={hotelKey(h.brand, h.hotelId)}>
                [{h.brand}] {h.hotelName}
              </option>
            ))}
          </select>
        </label>
        {selectedHotel && (
          <span className="text-sm text-ink/60">
            {selectedHotel.city} · min {formatCurrency(min)} · max {formatCurrency(max)}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1 text-xs text-ink/60">
          <span>cheap</span>
          <span className="w-4 h-4 rounded bg-emerald-200 inline-block" />
          <span className="w-4 h-4 rounded bg-emerald-300 inline-block" />
          <span className="w-4 h-4 rounded bg-amber-200 inline-block" />
          <span className="w-4 h-4 rounded bg-orange-300 inline-block" />
          <span className="w-4 h-4 rounded bg-rose-400 inline-block" />
          <span>expensive</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {months.map(({ year, month }) => (
          <div key={`${year}-${month}`} className="card">
            <div className="mb-2 font-semibold">
              {MONTH_NAMES[month]} <span className="text-ink/40 font-normal">{year}</span>
            </div>
            <div className="grid grid-cols-7 gap-1 text-[10px] text-ink/40 mb-1">
              {DOW_LABELS.map((d, i) => (
                <div key={i} className="text-center">{d}</div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {monthDays(year, month).map((cell, i) => {
                if (!cell) return <div key={i} className="aspect-square" />;
                const iso = cell.toISOString().slice(0, 10);
                const row = byDate.get(iso);
                const priceClass = priceColor(row?.price ?? null, min, max);
                return (
                  <div
                    key={i}
                    title={row ? `${iso} · ${formatCurrency(row.price, row.currency)}` : iso}
                    className={clsx(
                      "aspect-square rounded-md flex flex-col items-center justify-center text-[10px] font-medium",
                      priceClass,
                    )}
                  >
                    <span className="opacity-60">{cell.getUTCDate()}</span>
                    <span className="text-[9px] font-semibold">
                      {row?.price != null ? `${Math.round(row.price)}€` : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
