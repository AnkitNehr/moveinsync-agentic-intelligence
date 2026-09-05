/**
 * Formatting helpers shared by every view.
 *
 * A null value never renders as "0" or "undefined" — it renders as an em dash.
 * On this dataset nulls are meaningful (a metric with no SLA, an unacknowledged
 * alert, a contract that records no distance), so collapsing them into zero
 * would invent a fact.
 */

/** Rate metrics arrive as 0..1 and are read as percentages. */
export function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

/** Percentage *points* — already a delta on the 0..100 scale. */
export function pts(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const s = v > 0 ? '+' : v < 0 ? '−' : '';
  return `${s}${Math.abs(v).toFixed(digits)} pts`;
}

export function signed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const s = v > 0 ? '+' : v < 0 ? '−' : '';
  return `${s}${Math.abs(v).toFixed(digits)}`;
}

export function currency(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return `₹${v.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function num(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Compact form for stat-tile sample counts: 188,992 -> 189.0K */
export function compact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (Math.abs(v) < 1000) return String(v);
  if (Math.abs(v) < 1_000_000) return `${(v / 1000).toFixed(1)}K`;
  return `${(v / 1_000_000).toFixed(2)}M`;
}

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (v < 1000) return `${v} ms`;
  return `${(v / 1000).toFixed(1)} s`;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (v === 0) return '$0.0000';
  return `$${v.toFixed(4)}`;
}

/** Renders a value according to its catalog unit. */
export function byUnit(v: number | null | undefined, unit: string): string {
  switch (unit) {
    case 'rate':
      return pct(v);
    case 'currency':
      return currency(v);
    case 'minutes':
      return v === null || v === undefined ? '—' : `${num(v, 1)} min`;
    default:
      return num(v, 2);
  }
}

/** "2026-06" -> "June 2026". Falls back to the raw label if it is not a period. */
export function periodLabel(p: string | null | undefined): string {
  if (!p) return '—';
  const m = /^(\d{4})-(\d{2})/.exec(p);
  if (!m) return p;
  const months = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];
  const idx = Number(m[2]) - 1;
  return idx >= 0 && idx < 12 ? `${months[idx]} ${m[1]}` : p;
}

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

/** Maps a backend severity band onto a status token. */
export function severityColor(severity: string | null | undefined): string {
  switch ((severity ?? '').toUpperCase()) {
    case 'CRITICAL':
    case 'SEV1':
    case 'SEV-1':
      return 'var(--critical)';
    case 'HIGH':
    case 'SERIOUS':
    case 'SEV2':
    case 'SEV-2':
      return 'var(--serious)';
    case 'MEDIUM':
    case 'WARNING':
    case 'SEV3':
    case 'SEV-3':
      return 'var(--warning)';
    default:
      return 'var(--ink-muted)';
  }
}
