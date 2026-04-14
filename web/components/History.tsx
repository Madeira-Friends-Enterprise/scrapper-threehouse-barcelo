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

export function History({ rows, hotels }: Props) {
  const [hotelSel, setHotelSel] = useState<string>(
    hotels[0] ? hotelKey(hotels[0].brand, hotels[0].hotelId) : "",
  );

  // Derive rooms that exist for the selected hotel from the history rows.
  const rooms = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of rows) {
      if (hotelKey(r.brand, r.hotelId) !== hotelSel) continue;
      const key = r.roomType || "(aggregate)";
      if (!seen.has(key)) seen.set(key, r.roomType || "All rooms (lowest)");
    }
    return Array.from(seen.entries()).map(([key, label]) => ({ key, label }));
  }, [rows, hotelSel]);

  const [roomSel, setRoomSel] = useState<string>("(aggregate)");
  const [stayDate, setStayDate] = useState<string>("");

  // Available stay-dates for the chosen hotel+room (so the user can pick a date
  // that actually has history).
  const stayDates = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) {
      if (hotelKey(r.brand, r.hotelId) !== hotelSel) continue;
      const rk = r.roomType || "(aggregate)";
      if (rk !== roomSel) continue;
      if (r.date) s.add(r.date);
    }
    const sorted = Array.from(s).sort();
    return sorted;
  }, [rows, hotelSel, roomSel]);

  const effectiveStay = stayDate || stayDates[0] || "";

  // Series: price per scrapedAt for the selected (hotel, room, date).
  const series = useMemo(() => {
    const points: { scrapedAt: string; price: number | null }[] = [];
    for (const r of rows) {
      if (hotelKey(r.brand, r.hotelId) !== hotelSel) continue;
      const rk = r.roomType || "(aggregate)";
      if (rk !== roomSel) continue;
      if (r.date !== effectiveStay) continue;
      points.push({ scrapedAt: r.scrapedAt, price: r.price });
    }
    points.sort((a, b) => a.scrapedAt.localeCompare(b.scrapedAt));
    return points;
  }, [rows, hotelSel, roomSel, effectiveStay]);

  const snapshotCount = series.length;

  return (
    <div className="space-y-4">
      <div className="card grid grid-cols-1 md:grid-cols-3 gap-3">
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Hotel</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 w-full"
            value={hotelSel}
            onChange={(e) => {
              setHotelSel(e.target.value);
              setRoomSel("(aggregate)");
              setStayDate("");
            }}
          >
            {hotels.map((h) => (
              <option key={hotelKey(h.brand, h.hotelId)} value={hotelKey(h.brand, h.hotelId)}>
                [{h.brand}] {h.hotelName}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Room</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 w-full"
            value={roomSel}
            onChange={(e) => {
              setRoomSel(e.target.value);
              setStayDate("");
            }}
          >
            {rooms.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Stay date</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 w-full"
            value={effectiveStay}
            onChange={(e) => setStayDate(e.target.value)}
          >
            {stayDates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="card">
        <div className="text-sm text-ink/60 mb-2">
          {snapshotCount} snapshots for {effectiveStay || "—"} on{" "}
          {roomSel === "(aggregate)" ? "all rooms" : roomSel}.
        </div>
        <div className="h-[420px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={series} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
              <XAxis
                dataKey="scrapedAt"
                tickFormatter={(v) => String(v).slice(5, 16).replace("T", " ")}
                minTickGap={40}
              />
              <YAxis tickFormatter={(v) => `${v}€`} width={60} />
              <Tooltip
                labelFormatter={(v) => `scraped ${String(v).replace("T", " ").slice(0, 19)}`}
                formatter={(v) => (v == null ? "—" : `${v}€`)}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="price"
                name="Price"
                stroke="#3d5afe"
                strokeWidth={2}
                dot={{ r: 2 }}
                connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
