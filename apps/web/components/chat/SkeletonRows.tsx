// Placeholder rows for a list whose first fetch is in flight. Each row's box
// matches the real row it stands in for (Sidebar's conversation row: 56 px;
// DocumentsPanel's row: 22 px), so the list does not shift when it lands.
// Reduced motion is handled by the global rule in globals.css.

const CONVERSATION_WIDTHS = ["w-3/4", "w-1/2", "w-5/6", "w-2/3", "w-2/5"];
const DOCUMENT_WIDTHS = ["w-2/3", "w-1/2", "w-3/5"];

const BAR = "rounded-control bg-surface-3";

export function SkeletonRows({
  kind,
}: {
  kind: "conversations" | "documents";
}) {
  return (
    <div data-skeleton={kind} className="flex animate-pulse flex-col gap-1">
      {kind === "conversations"
        ? CONVERSATION_WIDTHS.map((width) => (
            <div
              key={width}
              data-skeleton-row
              className="rounded-control px-3 py-2"
            >
              <div className="flex h-5.5 items-center">
                <div className={`h-3.5 ${width} ${BAR}`} />
              </div>
              <div className="flex h-4.5 items-center">
                <div className={`h-3 w-16 ${BAR}`} />
              </div>
            </div>
          ))
        : DOCUMENT_WIDTHS.map((width) => (
            <div
              key={width}
              data-skeleton-row
              className="flex h-5.5 items-center gap-2 px-1"
            >
              <div className={`h-3.5 flex-none ${width} ${BAR}`} />
              <div className="flex-1" />
              <div className={`h-3 w-10 ${BAR}`} />
            </div>
          ))}
    </div>
  );
}
