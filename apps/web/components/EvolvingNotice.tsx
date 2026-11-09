// The visitor's notice that the product is still growing: on the landing,
// below the top bar, and in the demo chat, above the guest line.
export function EvolvingNotice() {
  return (
    <div className="w-full px-4 pt-2 text-center text-small text-ink-3">
      <p>Hax is evolving. More specific capabilities coming soon.</p>
      <p>
        Public repo:{" "}
        <a
          href="https://github.com/vinhto5197/hax"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          github.com/vinhto5197/hax
        </a>
      </p>
    </div>
  );
}
