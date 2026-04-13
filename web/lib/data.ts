import "server-only";
import { cache } from "react";
import { fetchRows, summarize } from "./sheets";
import type { PriceRow, DatasetMeta } from "./types";

export const revalidate = 300;

export const getDataset = cache(async (): Promise<{ rows: PriceRow[]; meta: DatasetMeta }> => {
  const rows = await fetchRows();
  return { rows, meta: summarize(rows) };
});
