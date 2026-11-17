// Foxhood's fox head. Original artwork, not a Marist logo.
export function FoxMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <path d="M2 2.5 L8.5 8 H15.5 L22 2.5 L20.5 12.5 L12 21.5 L3.5 12.5 Z" fill="var(--color-fox)" />
      <path d="M7.5 12.5 L12 16.5 L16.5 12.5 L12 18.5 Z" fill="var(--color-paper)" />
    </svg>
  );
}

export function Wordmark({ size = 24 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2 font-bold tracking-tight text-fox" style={{ fontSize: size * 0.88 }}>
      <FoxMark size={size} />
      Foxhood
    </span>
  );
}
