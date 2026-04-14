import "server-only";
import { cache } from "react";
import { fetchRows, summarize, latestOnly } from "./sheets";
import type { PriceRow, DatasetMeta } from "./types";

// Every request re-reads the sheet — the scraper runs on-demand and we want
// users to see fresh numbers the second the GitHub Action finishes.
export const revalidate = 0;

export const getDataset = cache(
  async (): Promise<{ rows: PriceRow[]; latest: PriceRow[]; meta: DatasetMeta }> => {
    const rows = await fetchRows();
    const latest = latestOnly(rows);
    return { rows, latest, meta: summarize(latest) };
  },
);
