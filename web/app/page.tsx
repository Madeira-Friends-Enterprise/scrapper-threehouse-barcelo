import { getDataset } from "@/lib/data";
import { Stats } from "@/components/Stats";
import { PriceTable } from "@/components/HotelFilter";
import { EmptyState } from "@/components/EmptyState";

export const revalidate = 300;

export default async function HomePage() {
  try {
    const { rows, meta } = await getDataset();
    if (rows.length === 0) {
      return (
        <EmptyState
          title="No data yet"
          hint="Trigger the scraper with the ⚡ Scrape now button or wait for the next cron (every 4h)."
        />
      );
    }
    return (
      <>
        <Stats meta={meta} />
        <PriceTable rows={rows} hotels={meta.hotels} />
      </>
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return (
      <EmptyState
        title="Could not read Google Sheets"
        hint={`Check the environment variables on Vercel. Detail: ${msg}`}
      />
    );
  }
}
