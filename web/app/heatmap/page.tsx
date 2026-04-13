import { getDataset } from "@/lib/data";
import { Stats } from "@/components/Stats";
import { Heatmap } from "@/components/Heatmap";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";
export const revalidate = 300;

export default async function HeatmapPage() {
  try {
    const { rows, meta } = await getDataset();
    if (rows.length === 0) return <EmptyState title="No data yet" />;
    return (
      <>
        <Stats meta={meta} />
        <Heatmap rows={rows} hotels={meta.hotels} />
      </>
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return <EmptyState title="Error loading data" hint={msg} />;
  }
}
