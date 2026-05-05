"use client";

/**
 * Big inline CTA on the main page so any visitor (not just whoever knows
 * to look at the small "Scrape now" pill in the header) can trigger a
 * fresh scrape. Both buttons share the same modal — this one just fires
 * a window event the RefreshButton mounted in the layout listens to.
 */
export function HeroScrape() {
  const trigger = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("scrape:start"));
    }
  };
  return (
    <div className="card flex flex-col sm:flex-row items-start sm:items-center gap-4 border border-accent/20 bg-gradient-to-r from-accent/5 to-transparent">
      <div className="flex-1">
        <div className="font-semibold text-base">Update prices now</div>
        <div className="text-sm text-ink/60 mt-1">
          Pulls fresh prices from every source (Threehouse, Barceló, Savoy
          Insular, Savoy Monumentalis). Takes 60–75 min — a progress bar
          stays up the whole time and the page refreshes automatically when
          the new rows are in the Sheet.
        </div>
      </div>
      <button
        className="btn btn-primary px-6 py-3 text-base whitespace-nowrap"
        onClick={trigger}
      >
        Scrape now
      </button>
    </div>
  );
}
