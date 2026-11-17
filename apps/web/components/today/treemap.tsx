import { money, pct, type Position } from "@/lib/today";

// Holdings as boxes: size is share of the portfolio, color is today's move (slate down, green up).

type Item = { ticker: string; name: string; weight: number; move: number | null; dayPnl: number; value: number };
type Box = Item & { x: number; y: number; w: number; h: number };

const OTHER_BELOW = 2; // percent of the portfolio

function toItems(positions: Position[]): Item[] {
  const items = positions.map((p) => ({
    ticker: p.ticker, name: p.name, weight: p.weight_pct, move: p.day_change_pct, dayPnl: p.day_pnl, value: p.market_value,
  }));
  const small = items.filter((i) => i.weight < OTHER_BELOW);
  if (small.length < 2) return items.sort((a, b) => b.weight - a.weight);
  const value = small.reduce((s, i) => s + i.value, 0);
  const dayPnl = small.reduce((s, i) => s + i.dayPnl, 0);
  const other: Item = {
    ticker: "Other", name: `${small.length} smaller holdings`, weight: small.reduce((s, i) => s + i.weight, 0),
    move: value !== dayPnl ? (dayPnl / (value - dayPnl)) * 100 : null, dayPnl, value,
  };
  return [...items.filter((i) => i.weight >= OTHER_BELOW).sort((a, b) => b.weight - a.weight), other];
}

// Squarified treemap (Bruls, Huizing & van Wijk): lay boxes in rows along the short side, keeping them close to square.
function squarify(items: Item[], W: number, H: number): Box[] {
  const total = items.reduce((s, i) => s + i.weight, 0) || 1;
  const area = (i: Item) => (i.weight / total) * W * H;
  const out: Box[] = [];
  let rest = [...items];
  let x = 0, y = 0, w = W, h = H;

  const worst = (row: Item[], side: number) => {
    const s = row.reduce((t, i) => t + area(i), 0);
    const max = Math.max(...row.map(area)), min = Math.min(...row.map(area));
    return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min));
  };

  while (rest.length) {
    const side = Math.min(w, h);
    const row = [rest[0]];
    let i = 1;
    while (i < rest.length && worst([...row, rest[i]], side) <= worst(row, side)) row.push(rest[i++]);
    rest = rest.slice(i);
    const rowArea = row.reduce((t, it) => t + area(it), 0);
    if (w >= h) {
      const rw = rowArea / h; // a column on the left
      let cy = y;
      for (const it of row) { const bh = area(it) / rw; out.push({ ...it, x, y: cy, w: rw, h: bh }); cy += bh; }
      x += rw; w -= rw;
    } else {
      const rh = rowArea / w; // a row across the top
      let cx = x;
      for (const it of row) { const bw = area(it) / rh; out.push({ ...it, x: cx, y, w: bw, h: rh }); cx += bw; }
      y += rh; h -= rh;
    }
  }
  return out;
}

const FILLS: [number, string, boolean][] = [
  // [upper bound of the bin in %, fill, light text?]
  [-2, "var(--color-move-down-3)", true],
  [-0.75, "var(--color-move-down-2)", false],
  [-0.1, "var(--color-move-down-1)", false],
  [0.1, "var(--color-move-flat)", false],
  [0.75, "var(--color-move-up-1)", false],
  [2, "var(--color-move-up-2)", false],
  [Infinity, "var(--color-move-up-3)", true],
];
function fill(move: number | null): [string, boolean] {
  if (move == null) return ["var(--color-move-flat)", false];
  const [, color, light] = FILLS.find(([max]) => move <= max)!;
  return [color, light];
}

function Cell({ b, W, H }: { b: Box; W: number; H: number }) {
  const [bg, light] = fill(b.move);
  const shareOfArea = (b.w * b.h) / (W * H);
  const size = shareOfArea > 0.2 ? "lg" : shareOfArea > 0.06 ? "md" : shareOfArea > 0.025 ? "sm" : "xs";
  const label = `${b.ticker}: ${b.weight.toFixed(0)}% of portfolio, ${pct(b.move)} today (${money(b.dayPnl, { signed: true })})`;
  return (
    <div
      title={label}
      className="absolute p-[1.5px]"
      style={{ left: `${(b.x / W) * 100}%`, top: `${(b.y / H) * 100}%`, width: `${(b.w / W) * 100}%`, height: `${(b.h / H) * 100}%` }}
    >
      <div
        className={`flex h-full flex-col justify-between overflow-hidden rounded ${light ? "text-paper" : "text-ink"} ${
          size === "lg" ? "p-5 md:p-6" : size === "md" ? "p-4" : "p-2.5"
        }`}
        style={{ background: bg }}
      >
        {size === "lg" && (
          <>
            <div>
              <div className="text-3xl leading-none font-bold tracking-tight md:text-[44px]">{b.ticker}</div>
              <div className="mt-1.5 truncate text-[15px]">{b.name}</div>
            </div>
            <div className="flex items-end justify-between gap-3">
              <div className="text-2xl leading-tight font-semibold md:text-3xl">
                {pct(b.move)}
                <div className="text-base font-medium">{money(b.dayPnl, { signed: true })} today</div>
              </div>
              <div className="text-right text-[15px]">
                {b.weight.toFixed(0)}% of portfolio
                <div>{money(b.value)}</div>
              </div>
            </div>
          </>
        )}
        {size === "md" && (
          <>
            <div className="flex justify-between gap-2">
              <div className="truncate text-2xl leading-none font-bold">{b.ticker}</div>
              <div className="text-xl font-semibold">{pct(b.move)}</div>
            </div>
            <div className="flex justify-between gap-2 text-[15px]">
              <span>{b.weight.toFixed(0)}%</span>
              <span className="truncate">{money(b.dayPnl, { signed: true })} today</span>
            </div>
          </>
        )}
        {size === "sm" && (
          <>
            <div className="truncate text-base leading-none font-bold">{b.ticker}</div>
            <div className="text-sm font-semibold">{pct(b.move)}</div>
          </>
        )}
        {size === "xs" && <div className="truncate text-xs font-semibold">{b.ticker}</div>}
      </div>
    </div>
  );
}

function Layout({ items, W, H, className }: { items: Item[]; W: number; H: number; className: string }) {
  return (
    <div className={`relative ${className}`} aria-hidden="true">
      {squarify(items, W, H).map((b) => <Cell key={b.ticker} b={b} W={W} H={H} />)}
    </div>
  );
}

export function Treemap({ positions }: { positions: Position[] }) {
  const items = toItems(positions);
  const description = items.map((i) => `${i.ticker} ${i.weight.toFixed(0)}% ${pct(i.move)}`).join(", ");
  return (
    <div role="img" aria-label={`Holdings by share of portfolio, with today's move: ${description}`}>
      {/* Desktop and phone get their own layout, since the best arrangement depends on the box's shape. */}
      <Layout items={items} W={1000} H={380} className="hidden h-[380px] md:block" />
      <Layout items={items} W={350} H={320} className="h-[320px] md:hidden" />
    </div>
  );
}

export function TreemapLegend() {
  return (
    <div aria-hidden="true" className="flex items-center gap-2 text-[13px] text-ink-muted">
      <span>{"−"}3%</span>
      <span className="flex gap-0.5">
        {["down-3", "down-2", "flat", "up-2", "up-3"].map((k) => (
          <span key={k} className="h-2.5 w-5 rounded-sm" style={{ background: `var(--color-move-${k})` }} />
        ))}
      </span>
      <span>+3%</span>
      <span className="ml-2 hidden sm:inline">Size is share of your portfolio</span>
    </div>
  );
}
