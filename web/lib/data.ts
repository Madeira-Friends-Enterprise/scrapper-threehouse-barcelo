import "server-only";
import { cache } from "react";
import { fetchRows, summarize, latestOnly } from "./sheets";
import type { PriceRow, DatasetMeta } from "./types";

// Every request re-reads the sheet — the scraper runs on-demand and we want
// users to see fresh numbers the second the GitHub Action finishes.
export const revalidate = 0;

// Dashboard scope is now Booking only (Savoy Insular + Savoy Monumentalis).
// Threehouse + Barceló rows still live in the historical Sheet but are
// filtered out at read time so the UI stays focused. Re-add brands here
// to bring them back into view without touching the scrapers.
const VISIBLE_BRANDS = new Set(["Savoy Insular", "Savoy Monumentalis"]);

export const getDataset = cache(
  async (): Promise<{ rows: PriceRow[]; latest: PriceRow[]; meta: DatasetMeta }> => {
    const all = await fetchRows();
    const rows = all.filter((r) => VISIBLE_BRANDS.has(r.brand));
    const latest = latestOnly(rows);
    return { rows, latest, meta: summarize(latest) };
  },
);
