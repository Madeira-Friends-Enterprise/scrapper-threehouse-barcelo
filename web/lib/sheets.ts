import { google } from "googleapis";
import type { PriceRow, DatasetMeta, HotelSummary } from "./types";

const SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"];

function getAuth() {
  const raw = process.env.GOOGLE_SERVICE_ACCOUNT_JSON;
  if (!raw) throw new Error("GOOGLE_SERVICE_ACCOUNT_JSON env var missing");
  let creds: { client_email: string; private_key: string };
  try {
    creds = JSON.parse(raw);
  } catch {
    throw new Error("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON");
  }
  return new google.auth.JWT({
    email: creds.client_email,
    key: creds.private_key.replace(/\\n/g, "\n"),
    scopes: SCOPES,
  });
}

async function resolveSheetTitle(spreadsheetId: string, gid: number): Promise<string> {
  const sheets = google.sheets({ version: "v4", auth: getAuth() });
  const meta = await sheets.spreadsheets.get({ spreadsheetId });
  const tab = meta.data.sheets?.find((s) => s.properties?.sheetId === gid);
  if (!tab?.properties?.title) {
    throw new Error(`Worksheet gid=${gid} not found in spreadsheet`);
  }
  return tab.properties.title;
}

function toBool(v: string): boolean {
  return /^true|1|yes$/i.test(v.trim());
}

function toNum(v: string): number | null {
  if (v == null || v === "") return null;
  const n = Number(String(v).replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

export async function fetchRows(): Promise<PriceRow[]> {
  const spreadsheetId = process.env.GOOGLE_SHEET_ID;
  const gid = Number(process.env.GOOGLE_SHEET_GID ?? "0");
  if (!spreadsheetId) throw new Error("GOOGLE_SHEET_ID env var missing");

  const title = await resolveSheetTitle(spreadsheetId, gid);
  const sheets = google.sheets({ version: "v4", auth: getAuth() });
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId,
    range: `${title}!A1:K100000`,
    valueRenderOption: "UNFORMATTED_VALUE",
  });
  const values = (res.data.values ?? []) as string[][];
  if (values.length === 0) return [];

  const [header, ...data] = values;
  const idx = (k: string) => header.findIndex((h) => String(h).trim() === k);

  const cols = {
    scrapedAt: idx("scraped_at"),
    brand: idx("brand"),
    hotelName: idx("hotel_name"),
    hotelId: idx("hotel_id"),
    city: idx("city"),
    date: idx("date"),
    price: idx("price"),
    currency: idx("currency"),
    available: idx("available"),
    minStay: idx("min_stay"),
    sourceUrl: idx("source_url"),
  };

  const pick = (row: string[], i: number) => (i >= 0 ? String(row[i] ?? "") : "");

  return data.map((row) => ({
    scrapedAt: pick(row, cols.scrapedAt),
    brand: pick(row, cols.brand),
    hotelName: pick(row, cols.hotelName),
    hotelId: pick(row, cols.hotelId),
    city: pick(row, cols.city),
    date: pick(row, cols.date).slice(0, 10),
    price: toNum(pick(row, cols.price)),
    currency: pick(row, cols.currency) || "EUR",
    available: toBool(pick(row, cols.available)),
    minStay: toNum(pick(row, cols.minStay)) as number | null,
    sourceUrl: pick(row, cols.sourceUrl),
  }));
}

export function summarize(rows: PriceRow[]): DatasetMeta {
  const byHotel = new Map<string, PriceRow[]>();
  for (const r of rows) {
    const key = `${r.brand}__${r.hotelId}`;
    if (!byHotel.has(key)) byHotel.set(key, []);
    byHotel.get(key)!.push(r);
  }

  const hotels: HotelSummary[] = [];
  for (const [, group] of byHotel) {
    const prices = group.map((r) => r.price).filter((x): x is number => x != null);
    hotels.push({
      brand: group[0].brand,
      hotelName: group[0].hotelName,
      hotelId: group[0].hotelId,
      city: group[0].city,
      rowCount: group.length,
      avgPrice: prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : null,
      minPrice: prices.length ? Math.min(...prices) : null,
      maxPrice: prices.length ? Math.max(...prices) : null,
    });
  }

  hotels.sort((a, b) => a.brand.localeCompare(b.brand) || a.hotelName.localeCompare(b.hotelName));

  const dates = rows.map((r) => r.date).filter(Boolean).sort();
  const scraped = rows.map((r) => r.scrapedAt).filter(Boolean).sort();

  return {
    totalRows: rows.length,
    lastScrapedAt: scraped.length ? scraped[scraped.length - 1] : null,
    dateRange: {
      start: dates.length ? dates[0] : null,
      end: dates.length ? dates[dates.length - 1] : null,
    },
    hotels,
  };
}
