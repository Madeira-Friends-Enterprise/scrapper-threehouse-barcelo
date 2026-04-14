"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";
import type { PriceRow } from "@/lib/types";
import { formatCurrency, formatDate, hotelKey } from "@/lib/format";

type Props = {
  rows: PriceRow[];
  hotels: { brand: string; hotelName: string; hotelId: string; city: string }[];
};

export function PriceTable({ rows, hotels }: Props) {
  const [brandFilter, setBrandFilter] = useState<string>("all");
  const [hotelFilter, setHotelFilter] = useState<string>("all");
  const [roomFilter, setRoomFilter] = useState<string>("all");
  const [onlyAvailable, setOnlyAvailable] = useState(true);

  const brands = useMemo(() => Array.from(new Set(hotels.map((h) => h.brand))), [hotels]);

  const filteredHotels = useMemo(
    () => (brandFilter === "all" ? hotels : hotels.filter((h) => h.brand === brandFilter)),
    [hotels, brandFilter],
  );

  const availableRooms = useMemo(() => {
    const seen = new Map<string, string>();
    for (const r of rows) {
      if (brandFilter !== "all" && r.brand !== brandFilter) continue;
      if (hotelFilter !== "all" && hotelKey(r.brand, r.hotelId) !== hotelFilter) continue;
      const key = r.roomType || "(aggregate)";
      if (!seen.has(key)) seen.set(key, r.roomType);
    }
    return Array.from(seen.entries()).map(([key, label]) => ({ key, label: label || "All rooms (lowest)" }));
  }, [rows, brandFilter, hotelFilter]);

  const filtered = useMemo(() => {
    return rows.filter((r) => {
      if (brandFilter !== "all" && r.brand !== brandFilter) return false;
      if (hotelFilter !== "all" && hotelKey(r.brand, r.hotelId) !== hotelFilter) return false;
      if (roomFilter !== "all") {
        const key = r.roomType || "(aggregate)";
        if (key !== roomFilter) return false;
      }
      if (onlyAvailable && !r.available) return false;
      return true;
    });
  }, [rows, brandFilter, hotelFilter, roomFilter, onlyAvailable]);

  const toCsv = () => {
    const header = ["date", "brand", "hotel_name", "room_type", "city", "price", "currency", "available"];
    const lines = [header.join(",")];
    for (const r of filtered) {
      lines.push(
        [r.date, r.brand, `"${r.hotelName.replace(/"/g, "''")}"`, `"${(r.roomType || "").replace(/"/g, "''")}"`, r.city, r.price ?? "", r.currency, r.available]
          .map(String)
          .join(","),
      );
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `prices_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <label className="text-sm">
          <span className="mr-2 text-ink/60">Brand</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1"
            value={brandFilter}
            onChange={(e) => {
              setBrandFilter(e.target.value);
              setHotelFilter("all");
            }}
          >
            <option value="all">All</option>
            {brands.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          <span className="mr-2 text-ink/60">Hotel</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 max-w-[280px]"
            value={hotelFilter}
            onChange={(e) => {
              setHotelFilter(e.target.value);
              setRoomFilter("all");
            }}
          >
            <option value="all">All</option>
            {filteredHotels.map((h) => (
              <option key={hotelKey(h.brand, h.hotelId)} value={hotelKey(h.brand, h.hotelId)}>
                {h.hotelName} {h.city ? `· ${h.city}` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          <span className="mr-2 text-ink/60">Room</span>
          <select
            className="rounded-md border border-black/10 px-2 py-1 max-w-[280px]"
            value={roomFilter}
            onChange={(e) => setRoomFilter(e.target.value)}
          >
            <option value="all">All</option>
            {availableRooms.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={onlyAvailable}
            onChange={(e) => setOnlyAvailable(e.target.checked)}
          />
          Available only
        </label>

        <div className="ml-auto flex items-center gap-3">
          <span className="text-xs text-ink/50">{filtered.length.toLocaleString("en-GB")} rows</span>
          <button className="btn btn-ghost" onClick={toCsv}>
            ⬇ Export CSV
          </button>
        </div>
      </div>

      <div className="overflow-x-auto max-h-[70vh] border border-black/5 rounded-lg">
        <table className="min-w-full text-sm">
          <thead className="bg-ink text-white sticky top-0">
            <tr>
              <Th>Date</Th>
              <Th>Brand</Th>
              <Th>Hotel</Th>
              <Th>Room</Th>
              <Th>City</Th>
              <Th className="text-right">Price</Th>
              <Th>Avail.</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 5000).map((r, i) => (
              <tr key={i} className={clsx(i % 2 ? "bg-black/[0.015]" : "bg-white")}>
                <Td>{formatDate(r.date)}</Td>
                <Td>
                  <span
                    className={clsx(
                      "inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold",
                      r.brand === "Threehouse" ? "bg-amber-100 text-amber-800" : "bg-blue-100 text-blue-800",
                    )}
                  >
                    {r.brand}
                  </span>
                </Td>
                <Td className="max-w-[220px] truncate">{r.hotelName}</Td>
                <Td className="max-w-[220px] truncate text-xs text-ink/70">
                  {r.roomType || <span className="text-ink/40">aggregate</span>}
                </Td>
                <Td>{r.city || "—"}</Td>
                <Td className="text-right font-medium">{formatCurrency(r.price, r.currency)}</Td>
                <Td>{r.available ? "✓" : "—"}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length > 5000 && (
          <div className="px-3 py-2 text-xs text-ink/50">
            Showing first 5,000 rows. Filter to refine or export CSV.
          </div>
        )}
      </div>
    </div>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return <th className={clsx("text-left font-medium px-3 py-2", className)}>{children}</th>;
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return <td className={clsx("px-3 py-2 border-t border-black/5", className)}>{children}</td>;
}
