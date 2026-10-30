// The product's mark: drawn geometry, not type. This is the only place the
// name is a graphic; it takes its colour from `currentColor`. The favicon in
// `app/icon.svg` is the x of this mark on the accent tile.
export function Wordmark({
  height = 22,
  className,
}: {
  height?: number;
  className?: string;
}) {
  return (
    <svg
      role="img"
      aria-label="Hax"
      viewBox="-6 -6 256 112"
      width={(height * 256) / 112}
      height={height}
      className={className}
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth={24}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 12V88M12 62a26 26 0 0 1 52 0V88" />
        <circle cx="122" cy="62" r="26" />
        <path d="M148 36V88" />
        <path d="M180 36L232 88" />
        <path d="M232 36L180 88" />
      </g>
    </svg>
  );
}
