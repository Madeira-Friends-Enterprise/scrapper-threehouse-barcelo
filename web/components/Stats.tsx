import type { DatasetMeta } from "@/lib/types";
import { formatDate } from "@/lib/format";

export function Stats({ meta }: { meta: DatasetMeta }) {
  const last = meta.lastScrapedAt
    ? new Date(meta.lastScrapedAt).toLocaleString("en-GB")
    : "—";

  const cards = [
    { label: "Hotels", value: meta.hotels.length },
    { label: "Total rows", value: meta.totalRows.toLocaleString("en-GB") },
    {
      label: "Date range",
      value:
        meta.dateRange.start && meta.dateRange.end
          ? `${formatDate(meta.dateRange.start)} → ${formatDate(meta.dateRange.end)}`
          : "—",
    },
    { label: "Last update", value: last },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      {cards.map((c) => (
        <div key={c.label} className="card">
          <div className="text-xs uppercase tracking-wide text-ink/50">{c.label}</div>
          <div className="mt-1 text-lg font-semibold truncate">{c.value}</div>
        </div>
      ))}
    </div>
  );
}
