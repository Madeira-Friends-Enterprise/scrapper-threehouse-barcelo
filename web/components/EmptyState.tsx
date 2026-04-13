export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card text-center py-12">
      <div className="text-xl font-semibold">{title}</div>
      {hint && <div className="mt-2 text-sm text-ink/60">{hint}</div>}
    </div>
  );
}
