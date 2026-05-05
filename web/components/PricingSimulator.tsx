"use client";

import { useMemo, useState } from "react";
import type { PriceRow } from "@/lib/types";
import { hotelKey } from "@/lib/format";

type Props = {
  rows: PriceRow[];
  hotels: { brand: string; hotelName: string; hotelId: string; city: string }[];
};

type Strategy = {
  key: string;
  name: string;
  blurb: string;
  multiplier: (nights: number) => number;
};

// 1n/2n/3n premium multipliers explored against a baseline 4+ night rate.
// Numbers come from the 2026-05-04 analysis of the Savoy Insular and
// Monumentalis Booking calendars: both properties charge a flat
// "1-week-equivalent" total for any 1-3 night stay (per-night = 7×/3.5×/2.33×
// of the 7-night per-night).
const STRATEGIES: Strategy[] = [
  {
    key: "savoy",
    name: "A — Savoy match (aggressive)",
    blurb: "Mirror the lock-out fee Savoy applies: same total for any 1–3 night stay (= 7 × baseline). Maximises revenue per booking but pushes short-stay guests away.",
    multiplier: (n) => (n <= 3 ? 7 / n : 1),
  },
  {
    key: "moderate",
    name: "B — Moderate premium (recommended)",
    blurb: "1n at 4×, 2n at 2×, 3n at 1.5×. Covers fixed turnover/cleaning costs without scaring off weekend couples or business travellers.",
    multiplier: (n) => (n === 1 ? 4 : n === 2 ? 2 : n === 3 ? 1.5 : 1),
  },
  {
    key: "curve",
    name: "C — Declining curve",
    blurb: "Smooth multiplier 1 + 6/n² that decays continuously: 1n=7×, 2n=2.5×, 3n=1.67×, 4n=1.38×, 7n=1.12×, 14n=1.03×. UX-friendly, no hard cliff at 4 nights.",
    multiplier: (n) => Math.max(1, 1 + 6 / (n * n)),
  },
];

const STAY_LENGTHS = [1, 2, 3, 4, 5, 7, 14];

function fmtEUR(n: number): string {
  return `€${Math.round(n).toLocaleString("en-GB")}`;
}

export function PricingSimulator({ rows, hotels }: Props) {
  const [baseline, setBaseline] = useState<number>(250);
  const [active, setActive] = useState<string>("moderate");

  // Suggest a baseline from observed data: median of "Per night calendar"
  // rows across Threehouse + Barceló. Falls back to 250 € if no data.
  const observedBaseline = useMemo(() => {
    const calendarPrices = rows
      .filter((r) => r.stayNights == null && r.price != null)
      .map((r) => r.price as number);
    if (calendarPrices.length === 0) return null;
    const sorted = [...calendarPrices].sort((a, b) => a - b);
    return Math.round(sorted[Math.floor(sorted.length / 2)]);
  }, [rows]);

  const observedSavoyRatios = useMemo(() => {
    // For each Savoy date with all four stay lengths priced, compute the
    // per-night ratios to the 7-night per-night rate. The Booking row
    // stores TOTAL stay price (matches what booking.com shows in its
    // calendar), so per-night = total / stay_nights before ratio-ing.
    const byDate = new Map<string, Map<number, number>>();
    for (const r of rows) {
      if (!r.brand.startsWith("Savoy")) continue;
      if (r.stayNights == null || r.stayNights <= 0 || r.price == null) continue;
      const k = `${r.brand}__${r.hotelId}__${r.date}`;
      if (!byDate.has(k)) byDate.set(k, new Map());
      // Convert stored total to per-night for the ratio analysis.
      byDate.get(k)!.set(r.stayNights, r.price / r.stayNights);
    }
    const ratios: Record<number, number[]> = { 1: [], 2: [], 3: [] };
    for (const stays of byDate.values()) {
      const seven = stays.get(7);
      if (!seven || seven <= 0) continue;
      for (const n of [1, 2, 3] as const) {
        const v = stays.get(n);
        if (v) ratios[n].push(v / seven);
      }
    }
    const median = (arr: number[]) => {
      if (!arr.length) return null;
      const s = [...arr].sort((a, b) => a - b);
      return s[Math.floor(s.length / 2)];
    };
    return { 1: median(ratios[1]), 2: median(ratios[2]), 3: median(ratios[3]), n: byDate.size };
  }, [rows]);

  const strategy = STRATEGIES.find((s) => s.key === active) ?? STRATEGIES[1];

  const projection = STAY_LENGTHS.map((n) => {
    const mult = strategy.multiplier(n);
    const perNight = baseline * mult;
    return { nights: n, multiplier: mult, perNight, total: perNight * n };
  });

  return (
    <div className="space-y-4">
      <div className="card space-y-3">
        <div className="font-semibold">Pricing rule simulator</div>
        <p className="text-sm text-ink/60">
          Input the baseline per-night rate you want to charge for stays of
          4+ nights. The simulator shows how each premium strategy translates
          that into 1/2/3-night displayed prices, and how the math compares
          to what Savoy Insular and Savoy Monumentalis are doing on Booking
          for the same dates.
        </p>

        <div className="flex flex-wrap items-end gap-4">
          <label className="text-sm">
            <div className="text-ink/60 mb-1">Baseline (per-night, 4+ nights)</div>
            <div className="flex items-center gap-2">
              <span className="text-ink/40">€</span>
              <input
                type="number"
                value={baseline}
                onChange={(e) => setBaseline(Number(e.target.value) || 0)}
                className="rounded-md border border-black/10 px-2 py-1 w-32"
                min={0}
                step={10}
              />
            </div>
          </label>
          {observedBaseline != null && (
            <button
              className="btn btn-ghost text-xs"
              onClick={() => setBaseline(observedBaseline)}
              type="button"
            >
              Use observed median (€{observedBaseline})
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-2 pt-2">
          {STRATEGIES.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => setActive(s.key)}
              className={
                "text-xs px-3 py-1.5 rounded-full border " +
                (s.key === active
                  ? "bg-accent text-white border-accent"
                  : "bg-white border-black/10 hover:bg-black/[0.03]")
              }
            >
              {s.name}
            </button>
          ))}
        </div>
        <p className="text-xs text-ink/60">{strategy.blurb}</p>
      </div>

      <div className="card overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-ink text-white">
            <tr>
              <th className="text-left font-medium px-3 py-2">Stay length</th>
              <th className="text-right font-medium px-3 py-2">Multiplier</th>
              <th className="text-right font-medium px-3 py-2">Displayed per-night</th>
              <th className="text-right font-medium px-3 py-2">Total stay</th>
              <th className="text-right font-medium px-3 py-2">vs 7-night per-night</th>
            </tr>
          </thead>
          <tbody>
            {projection.map((p) => {
              const sevenPerNight = baseline * strategy.multiplier(7);
              const ratio = sevenPerNight > 0 ? p.perNight / sevenPerNight : 0;
              return (
                <tr key={p.nights} className="border-t border-black/5">
                  <td className="px-3 py-2">
                    {p.nights} night{p.nights > 1 ? "s" : ""}
                    {p.nights >= 4 && p.nights <= 6 && (
                      <span className="ml-2 text-[10px] uppercase text-ink/40">baseline</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{p.multiplier.toFixed(2)}×</td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium">{fmtEUR(p.perNight)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink/70">{fmtEUR(p.total)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink/60">{ratio.toFixed(2)}×</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="card space-y-2">
        <div className="font-semibold text-sm">Observed Savoy ratios (live data)</div>
        {observedSavoyRatios.n === 0 ? (
          <p className="text-sm text-ink/60">
            No Savoy snapshots in the current dataset yet. Run the scraper, then
            this panel will fill with the live Booking ratios.
          </p>
        ) : (
          <>
            <p className="text-sm text-ink/60">
              Median ratio of per-night price to 7-night per-night, computed
              across {observedSavoyRatios.n} Savoy date snapshots in the Sheet.
              Use these as a real benchmark for whatever strategy you pick.
            </p>
            <table className="min-w-full text-sm mt-2">
              <thead>
                <tr className="text-ink/60 text-xs">
                  <th className="text-left font-medium px-2 py-1">Stay</th>
                  <th className="text-right font-medium px-2 py-1">Savoy median ratio</th>
                  <th className="text-right font-medium px-2 py-1">Savoy implied per-night @ €{baseline} baseline</th>
                </tr>
              </thead>
              <tbody>
                {[1, 2, 3].map((n) => {
                  const r = (observedSavoyRatios as Record<number, number | null>)[n];
                  return (
                    <tr key={n} className="border-t border-black/5">
                      <td className="px-2 py-1">{n} night{n > 1 ? "s" : ""}</td>
                      <td className="px-2 py-1 text-right tabular-nums">
                        {r == null ? "—" : `${r.toFixed(2)}×`}
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums">
                        {r == null ? "—" : fmtEUR(baseline * r)}
                      </td>
                    </tr>
                  );
                })}
                <tr className="border-t border-black/5">
                  <td className="px-2 py-1">7 nights (baseline)</td>
                  <td className="px-2 py-1 text-right tabular-nums">1.00×</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmtEUR(baseline)}</td>
                </tr>
              </tbody>
            </table>
          </>
        )}
      </div>

      {hotels.length > 0 && (
        <div className="card text-xs text-ink/50">
          Comparing against {hotels.filter((h) => h.brand.startsWith("Savoy")).length} Savoy
          listings in the dataset.
        </div>
      )}
    </div>
  );
}
