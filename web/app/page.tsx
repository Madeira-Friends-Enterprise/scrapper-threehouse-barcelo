import { getDataset } from "@/lib/data";
import { Stats } from "@/components/Stats";
import { PriceTable } from "@/components/HotelFilter";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function HomePage() {
  try {
    const { latest, meta } = await getDataset();
    if (latest.length === 0) {
      return (
        <EmptyState
          title="No data yet"
          hint="Hit Scrape now in the header. A progress bar will appear and stay until every source finishes (~60–75 min)."
        />
      );
    }
    return (
      <>
        <Stats meta={meta} />
        <PriceTable rows={latest} hotels={meta.hotels} />
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
