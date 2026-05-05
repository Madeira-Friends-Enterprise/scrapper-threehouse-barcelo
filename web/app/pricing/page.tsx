import { getDataset } from "@/lib/data";
import { Stats } from "@/components/Stats";
import { PricingSimulator } from "@/components/PricingSimulator";
import { EmptyState } from "@/components/EmptyState";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function PricingPage() {
  try {
    const { latest, meta } = await getDataset();
    return (
      <>
        <Stats meta={meta} />
        <PricingSimulator rows={latest} hotels={meta.hotels} />
      </>
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return <EmptyState title="Could not load data" hint={msg} />;
  }
}
