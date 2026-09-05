import {
  Component,
  EventEmitter,
  Output,
  OnInit,
  OnDestroy,
  inject,
  signal,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService, HttpError } from '../core/api.service';
import type { Health, Incident, MetricObservation, RunProgress, RunSummary } from '../core/models';
import {
  byUnit,
  compact,
  num,
  periodLabel,
  pts,
  severityColor,
  shortTime,
  usd,
  ms,
} from '../core/format';

interface FunnelBandDef {
  id: string;
  label: string;
  hint: string;
  stages: string[];
}

const FUNNEL_BANDS: FunnelBandDef[] = [
  {
    id: 'sense',
    label: 'Sense',
    hint: 'Deterministic Java — ingest through policy',
    stages: ['ingest', 'scan', 'rank', 'policy'],
  },
  {
    id: 'reason',
    label: 'Reason',
    hint: 'First model call. It never sees a trip row.',
    stages: ['triage', 'reason', 'narrate'],
  },
  {
    id: 'act',
    label: 'Act',
    hint: 'Policy then outbox. No LLM.',
    stages: ['actionGuard', 'persist'],
  },
];

const STAGE_LABELS: Record<string, string> = {
  ingest: 'Ingest',
  scan: 'Scan',
  rank: 'Rank',
  policy: 'Policy',
  triage: 'Triage',
  reason: 'Reason',
  narrate: 'Narrate',
  actionGuard: 'Guard',
  persist: 'Persist',
};

const LLM_STAGES = new Set(['triage', 'reason', 'narrate']);

interface Kpi {
  id: string;
  label: string;
  unit: string;
  /** true when a rising value is the good outcome */
  higherIsBetter: boolean;
  obs: MetricObservation | null;
  error: string | null;
}

/**
 * The landing view: where the platform stands, what it costs to ask, and what
 * it wants looked at.
 *
 * The run telemetry is on screen rather than in a log. An agentic system that
 * cannot tell you what it spent is not auditable, and "how much does this cost
 * to run" is the first question anyone asks about one.
 */
@Component({
  selector: 'mi-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <!-- ---------------- KPI row ---------------- -->
    <section class="kpis" aria-label="Headline metrics">
      @for (k of kpis(); track k.id) {
        <article class="tile">
          <div class="tile-label">{{ k.label }}</div>

          @if (k.obs) {
            <div class="tile-value">{{ fmt(k.obs.value, k.unit) }}</div>

            @if (k.obs.references?.trend?.delta !== null && k.obs.references?.trend?.delta !== undefined) {
              <div class="tile-delta" [style.color]="deltaColor(k)">
                <span aria-hidden="true">{{ deltaGlyph(k) }}</span>
                <span class="num">{{ deltaText(k) }}</span>
                <span class="vs">vs {{ periodLabel(priorOf(k)) }}</span>
              </div>
            } @else {
              <div class="tile-delta muted">no prior period</div>
            }

            <div class="tile-foot num">
              n={{ compact(k.obs.sampleSize) }}
              @if (k.obs.references?.sla?.breached) {
                <span class="sla-flag">SLA breached</span>
              }
            </div>
          } @else if (k.error) {
            <div class="tile-value dash">—</div>
            <div class="tile-delta muted">{{ k.error }}</div>
          } @else {
            <div class="tile-value dash">…</div>
            <div class="tile-delta muted">loading</div>
          }
        </article>
      }

      <!-- Alerts is a row count, not a catalog metric — sourced from /api/health. -->
      <article class="tile">
        <div class="tile-label">Alerts ingested</div>
        @if (health(); as h) {
          <div class="tile-value">{{ compact(h.rows['alerts'] ?? 0) }}</div>
          <div class="tile-delta muted">
            {{ h.openIncidents }} open incident{{ h.openIncidents === 1 ? '' : 's' }}
          </div>
          <div class="tile-foot num">coverage {{ (h.coverage * 100).toFixed(1) }}%</div>
        } @else {
          <div class="tile-value dash">…</div>
          <div class="tile-delta muted">loading</div>
        }
      </article>
    </section>

    <!-- ---------------- Run control + telemetry ---------------- -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>Analysis run</h2>
          <p class="hint">
            One sense &rarr; reason &rarr; act pass over the fact store. Defaults to the
            latest period with data against the month before it.
          </p>
        </div>
        <button class="primary" (click)="runNow()" [disabled]="running()">
          {{ running() ? 'Running…' : 'Run now' }}
        </button>
      </div>

      @if (runError()) {
        <p class="error">{{ runError() }}</p>
      }

      <div class="funnel" aria-label="Pipeline funnel">
        @for (band of funnel(); track band.id) {
          <div class="band" [attr.data-band]="band.id">
            <div class="band-head">
              <span class="band-label">{{ band.label }}</span>
              <span class="band-hint">{{ band.hint }}</span>
            </div>
            <ol class="steps">
              @for (step of band.steps; track step.id) {
                <li class="step" [class.current]="step.status === 'current'" [class.done]="step.status === 'done'">
                  <span class="step-name">{{ step.label }}</span>
                  <span class="step-engine">{{ step.engine }}</span>
                  @if (step.count) {
                    <span class="step-count num">{{ step.count }}</span>
                  }
                  @if (step.ms) {
                    <span class="step-ms num">{{ step.ms }}</span>
                  }
                </li>
              }
            </ol>
          </div>
        }
      </div>

      @if (summary(); as s) {
        <div class="telemetry">
          <div class="tel"><span>Run</span><b class="mono">{{ s.runId }}</b></div>
          <div class="tel"><span>Trips scanned</span><b class="num">{{ num(s.trips) }}</b></div>
          <div class="tel"><span>Series evaluated</span><b class="num">{{ num(s.seriesEvaluated) }}</b></div>
          <div class="tel"><span>Candidates</span><b class="num">{{ num(s.candidates) }}</b></div>
          <div class="tel"><span>Incidents opened</span><b class="num">{{ num(s.incidents) }}</b></div>
          <div class="tel"><span>Prompt tokens</span><b class="num">{{ num(s.promptTokens) }}</b></div>
          <div class="tel"><span>Completion tokens</span><b class="num">{{ num(s.completionTokens) }}</b></div>
          <div class="tel accent"><span>Estimated cost</span><b class="num">{{ usd(s.estimatedCostUsd) }}</b></div>
          <div class="tel accent"><span>Wall clock</span><b class="num">{{ ms(s.wallClockMs) }}</b></div>
        </div>
      } @else if (!running() && !progress()?.running) {
        <p class="hint idle">
          No run has completed since startup. Press <b>Run now</b> to execute one.
        </p>
      }
    </section>

    <!-- ---------------- Incident list ---------------- -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>Incidents</h2>
          <p class="hint">
            Ranked by triage priority. Everything here cleared the volume gate and the
            attention threshold.
          </p>
        </div>
        <button class="ghost" (click)="loadIncidents()" [disabled]="loadingIncidents()">
          Refresh
        </button>
      </div>

      @if (incidents().length === 0) {
        <p class="hint idle">
          {{ loadingIncidents() ? 'Loading…' : 'No open incidents for this period.' }}
        </p>
      } @else {
        <ul class="incidents">
          @for (i of incidents(); track i.id) {
            <li>
              <button class="incident" (click)="openIncident.emit(i.id)">
                <span class="stripe" [style.background]="severityColor(i.severity)"></span>

                <span class="body">
                  <span class="row1">
                    <span class="sev" [style.color]="severityColor(i.severity)">
                      {{ i.severity }}
                    </span>
                    <span class="prio num">P{{ i.priority }}</span>
                    <span class="idtag mono">{{ i.id }}</span>
                    @if (i.status && i.status !== 'OPEN') {
                      <span class="statustag">{{ i.status }}</span>
                    }
                  </span>

                  <span class="title">{{ i.title }}</span>
                  <span class="why">{{ i.whyNow }}</span>

                  <span class="meta">
                    {{ i.findingIds.length }} finding{{ i.findingIds.length === 1 ? '' : 's' }}
                    @if (routedTo(i); as dest) {
                      &middot; routed to {{ dest }}
                    }
                    @if (i.quality) {
                      &middot; {{ i.quality.confidence }} confidence
                      &middot; <span class="num">{{ (i.quality.coverage * 100).toFixed(1) }}%</span> coverage
                    }
                    &middot; {{ shortTime(i.detectedAt) }}
                  </span>
                </span>

                <span class="chev" aria-hidden="true">&rsaquo;</span>
              </button>
            </li>
          }
        </ul>
      }

      <!-- The suppressed tail. A detector that only ever shows you its hits is
           not telling you how selective it was being. -->
      <p class="threshold">
        <span class="num">{{ belowThreshold() }}</span> other findings scored below the
        attention threshold.
      </p>
    </section>
  `,
  styles: [
    `
      :host {
        display: block;
      }

      h2 {
        margin: 0;
        font-size: 13px;
        font-weight: 650;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        color: var(--ink-2);
      }

      .hint {
        margin: 3px 0 0;
        font-size: 12px;
        color: var(--ink-muted);
        max-width: 62ch;
      }

      .hint.idle {
        padding: 14px 0 2px;
      }

      .error {
        margin: 10px 0 0;
        padding: 9px 11px;
        border-radius: var(--radius);
        background: color-mix(in srgb, var(--critical) 10%, transparent);
        border: 1px solid color-mix(in srgb, var(--critical) 35%, transparent);
        color: var(--critical);
        font-size: 12.5px;
      }

      /* ---- KPI tiles ---- */
      .kpis {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
        gap: 10px;
        margin-bottom: 16px;
      }

      .tile {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 12px 13px 11px;
      }

      .tile-label {
        font-size: 11px;
        font-weight: 550;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
      }

      /* Proportional figures on display values — tabular looks loose at 26px. */
      .tile-value {
        font-size: 26px;
        font-weight: 620;
        letter-spacing: -0.02em;
        line-height: 1.15;
        margin-top: 5px;
        color: var(--ink);
      }

      .tile-value.dash {
        color: var(--ink-muted);
      }

      .tile-delta {
        display: flex;
        align-items: baseline;
        gap: 5px;
        font-size: 12px;
        font-weight: 550;
        margin-top: 3px;
      }

      .tile-delta.muted {
        color: var(--ink-muted);
        font-weight: 400;
      }

      .vs {
        color: var(--ink-muted);
        font-weight: 400;
      }

      .tile-foot {
        margin-top: 7px;
        padding-top: 7px;
        border-top: 1px solid var(--line);
        font-size: 11px;
        color: var(--ink-muted);
        display: flex;
        gap: 7px;
        align-items: center;
        flex-wrap: wrap;
      }

      .sla-flag {
        color: var(--critical);
        font-weight: 600;
      }

      /* ---- panels ---- */
      .panel {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 14px 15px;
        margin-bottom: 14px;
      }

      .panel-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 14px;
        flex-wrap: wrap;
      }

      button.primary {
        background: var(--accent);
        color: #fff;
        border: none;
        border-radius: var(--radius);
        padding: 8px 18px;
        font-size: 13px;
        font-weight: 600;
        white-space: nowrap;
      }

      button.primary:hover:not(:disabled) {
        filter: brightness(1.08);
      }

      button.primary:disabled {
        opacity: 0.55;
      }

      button.ghost {
        background: var(--surface-2);
        color: var(--ink-2);
        border: 1px solid var(--line-strong);
        border-radius: var(--radius);
        padding: 6px 13px;
        font-size: 12px;
        font-weight: 550;
      }

      button.ghost:hover:not(:disabled) {
        border-color: var(--accent);
        color: var(--accent);
      }

      /* ---- telemetry ---- */
      .telemetry {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(136px, 1fr));
        gap: 1px;
        margin-top: 13px;
        background: var(--line);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        overflow: hidden;
      }

      .tel {
        background: var(--surface-2);
        padding: 8px 10px;
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
      }

      .tel span {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
      }

      .tel b {
        font-size: 14px;
        font-weight: 620;
        color: var(--ink);
        overflow-wrap: anywhere;
      }

      .tel.accent b {
        color: var(--accent);
      }

      .mono {
        font-family: var(--mono);
        font-size: 11.5px !important;
      }

      .funnel {
        display: grid;
        grid-template-columns: 1.4fr 1.1fr 0.8fr;
        gap: 10px;
        margin-top: 13px;
      }

      @media (max-width: 900px) {
        .funnel {
          grid-template-columns: 1fr;
        }
      }

      .band {
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: var(--surface-2);
        padding: 8px 9px 9px;
        min-width: 0;
      }

      .band-head {
        display: flex;
        flex-direction: column;
        gap: 1px;
        margin-bottom: 7px;
      }

      .band-label {
        font-size: 11px;
        font-weight: 650;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--ink-2);
      }

      .band-hint {
        font-size: 11px;
        color: var(--ink-muted);
        line-height: 1.35;
      }

      .steps {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }

      .step {
        flex: 1 1 72px;
        min-width: 72px;
        display: flex;
        flex-direction: column;
        gap: 1px;
        padding: 6px 7px;
        border-radius: 5px;
        border: 1px solid var(--line);
        background: var(--surface-sunken);
        color: var(--ink-muted);
      }

      .step.done {
        color: var(--ink);
        border-color: color-mix(in srgb, var(--good) 45%, var(--line));
        background: color-mix(in srgb, var(--good) 8%, var(--surface));
      }

      .step.current {
        color: var(--ink);
        border-color: var(--accent);
        background: color-mix(in srgb, var(--accent) 10%, var(--surface));
        box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 35%, transparent);
      }

      .step-name {
        font-size: 12px;
        font-weight: 620;
      }

      .step-engine {
        font-size: 10px;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        color: var(--ink-muted);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .step-count,
      .step-ms {
        font-size: 11px;
        color: var(--ink-2);
      }

      /* ---- incident list ---- */
      .incidents {
        list-style: none;
        margin: 12px 0 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 7px;
      }

      button.incident {
        width: 100%;
        display: flex;
        align-items: stretch;
        gap: 11px;
        text-align: left;
        background: var(--surface-2);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 0;
        overflow: hidden;
      }

      button.incident:hover {
        border-color: var(--accent-line);
        background: var(--surface-sunken);
      }

      /* Severity stripe. Colour is the cue, but the SEV text label beside it
         carries the same information — status is never hue-only. */
      .stripe {
        width: 4px;
        flex: none;
      }

      .body {
        display: flex;
        flex-direction: column;
        gap: 3px;
        padding: 10px 0;
        min-width: 0;
        flex: 1;
      }

      .row1 {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .sev {
        font-size: 10.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }

      .prio,
      .idtag,
      .statustag {
        font-size: 10.5px;
        color: var(--ink-muted);
        padding: 1px 6px;
        border-radius: 4px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
      }

      .idtag {
        font-family: var(--mono);
      }

      .title {
        font-size: 13.5px;
        font-weight: 600;
        color: var(--ink);
        padding-right: 8px;
      }

      .why {
        font-size: 12.5px;
        color: var(--ink-2);
        padding-right: 8px;
      }

      .meta {
        font-size: 11px;
        color: var(--ink-muted);
        margin-top: 2px;
      }

      .chev {
        display: flex;
        align-items: center;
        padding-right: 12px;
        font-size: 20px;
        color: var(--ink-muted);
        flex: none;
      }

      .threshold {
        margin: 13px 0 0;
        padding-top: 11px;
        border-top: 1px dashed var(--line-strong);
        font-size: 12px;
        color: var(--ink-muted);
        font-style: italic;
      }
    `,
  ],
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  @Output() openIncident = new EventEmitter<string>();
  @Output() healthChanged = new EventEmitter<Health>();

  readonly health = signal<Health | null>(null);
  readonly summary = signal<RunSummary | null>(null);
  readonly progress = signal<RunProgress | null>(null);
  readonly incidents = signal<Incident[]>([]);
  readonly running = signal(false);
  readonly loadingIncidents = signal(false);
  readonly runError = signal<string | null>(null);
  readonly kpis = signal<Kpi[]>([
    { id: 'ota', label: 'On-Time Arrival', unit: 'rate', higherIsBetter: true, obs: null, error: null },
    { id: 'cost_per_trip', label: 'Cost per Trip', unit: 'currency', higherIsBetter: false, obs: null, error: null },
    { id: 'occupancy', label: 'Seat Occupancy', unit: 'rate', higherIsBetter: true, obs: null, error: null },
    { id: 'noshow_rate', label: 'No-Show Rate', unit: 'rate', higherIsBetter: false, obs: null, error: null },
  ]);

  /**
   * Candidates the scorer raised minus the ones that became incidents. This is
   * the suppressed tail — the volume gate and the score threshold doing their
   * job on segments like SPOT_2.0 (702 trips) and trip_nodal=SHUTTLE (244).
   */
  readonly belowThreshold = computed(() => {
    const s = this.summary();
    if (!s) return 0;
    return Math.max(0, s.candidates - s.incidents);
  });

  readonly funnel = computed(() => {
    const p = this.progress();
    const h = this.health();
    const completed = new Map((p?.completed ?? []).map((s) => [s.stage, s]));
    const current = p?.currentStage ?? null;
    return FUNNEL_BANDS.map((band) => ({
      id: band.id,
      label: band.label,
      hint: band.hint,
      steps: band.stages.map((id) => {
        const timing = completed.get(id);
        let status: 'pending' | 'current' | 'done' = 'pending';
        if (current === id) status = 'current';
        else if (timing) status = 'done';
        return {
          id,
          label: STAGE_LABELS[id] ?? id,
          status,
          count: this.countFor(id, p),
          ms: timing ? ms(timing.millis) : null,
          engine: this.engineFor(id, h),
        };
      }),
    }));
  });

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  // re-exported for the template
  readonly num = num;
  readonly usd = usd;
  readonly ms = ms;
  readonly compact = compact;
  readonly pts = pts;
  readonly periodLabel = periodLabel;
  readonly shortTime = shortTime;
  readonly severityColor = severityColor;

  routedTo(i: Incident): string | null {
    const notify = i.recommendedActions?.find((a) => a.type === 'notify');
    return notify?.target ?? null;
  }

  async ngOnInit(): Promise<void> {
    void this.loadHealth();
    void this.loadKpis();
    void this.loadLatestRun();
    void this.loadIncidents();
    void this.loadProgress();
    this.pollTimer = setInterval(() => void this.tickProgress(), 500);
  }

  ngOnDestroy(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private countFor(stage: string, p: RunProgress | null): string | null {
    if (!p) return null;
    if (stage === 'ingest' && p.trips != null) {
      return compact(p.trips) + ' trips';
    }
    if (stage === 'scan') {
      const bits: string[] = [];
      if (p.seriesEvaluated != null) bits.push(compact(p.seriesEvaluated) + ' series');
      if (p.findings != null) bits.push(compact(p.findings) + ' hits');
      return bits.length ? bits.join(' · ') : null;
    }
    if (stage === 'rank' && p.candidates != null) {
      return compact(p.candidates) + ' candidates';
    }
    if (stage === 'persist' && p.incidents != null) {
      return compact(p.incidents) + ' incidents';
    }
    return null;
  }

  private engineFor(stage: string, h: Health | null): string {
    if (!LLM_STAGES.has(stage)) return 'code';
    const tier = h?.stageTiers?.[stage];
    return tier && tier !== 'deterministic' ? tier : 'deterministic';
  }

  fmt(v: number | null, unit: string): string {
    return byUnit(v, unit);
  }

  priorOf(k: Kpi): string | null {
    // The trend frame compares against the immediately preceding period.
    const p = k.obs?.period;
    if (!p) return null;
    const m = /^(\d{4})-(\d{2})$/.exec(p);
    if (!m) return null;
    const d = new Date(Number(m[1]), Number(m[2]) - 1, 1);
    d.setMonth(d.getMonth() - 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }

  deltaText(k: Kpi): string {
    const d = k.obs?.references?.trend?.delta;
    if (d === null || d === undefined) return '—';
    // Trend.delta arrives on the metric's OWN scale, so a rate is a fraction (0.0223) and not
    // percentage points (2.23). Finding.deltaPts and the attribution deltas are already scaled to
    // points, which is the trap: one payload carries two scales, and a formatter that is correct
    // for one silently under-reports the other by 100x. That is exactly what shipped — this tile
    // read "+0.02 pts" while the brief said "+2.23 pts" about the same movement, and two panels
    // disagreeing on screen costs more credibility than either number is worth.
    return k.unit === 'rate' ? pts(d * 100) : byUnit(Math.abs(d), k.unit);
  }

  deltaGlyph(k: Kpi): string {
    const d = k.obs?.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return '→';
    return d > 0 ? '▲' : '▼';
  }

  /** Colour is direction x whether up is good — and the glyph repeats it. */
  deltaColor(k: Kpi): string {
    const d = k.obs?.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return 'var(--ink-muted)';
    const good = d > 0 ? k.higherIsBetter : !k.higherIsBetter;
    return good ? 'var(--good)' : 'var(--critical)';
  }

  async loadHealth(): Promise<void> {
    try {
      const h = await this.api.health();
      this.health.set(h);
      this.healthChanged.emit(h);
    } catch {
      /* the shell header already surfaces an unreachable backend */
    }
  }

  async loadKpis(): Promise<void> {
    const current = this.kpis();
    await Promise.all(
      current.map(async (k, idx) => {
        try {
          const obs = await this.api.metric(k.id);
          this.patchKpi(idx, { obs, error: null });
        } catch (e) {
          this.patchKpi(idx, { obs: null, error: this.reason(e) });
        }
      }),
    );
  }

  private patchKpi(idx: number, patch: Partial<Kpi>): void {
    this.kpis.update((list) =>
      list.map((k, i) => (i === idx ? { ...k, ...patch } : k)),
    );
  }

  async loadLatestRun(): Promise<void> {
    try {
      const latest = await this.api.latestRun();
      this.summary.set(latest.summary);
      if (latest.incidents?.length) this.incidents.set(latest.incidents);
    } catch (e) {
      // 404 here means "nothing has run yet", which is a normal cold start.
      if (!(e instanceof HttpError) || e.status !== 404) {
        this.runError.set(this.reason(e));
      }
    }
  }

  async loadIncidents(): Promise<void> {
    this.loadingIncidents.set(true);
    try {
      this.incidents.set(await this.api.incidents());
    } catch (e) {
      this.runError.set(this.reason(e));
    } finally {
      this.loadingIncidents.set(false);
    }
  }

  async loadProgress(): Promise<void> {
    try {
      const p = await this.api.runProgress();
      this.progress.set(p);
    } catch {
      /* a missing progress endpoint should not blank the dashboard */
    }
  }

  private async tickProgress(): Promise<void> {
    try {
      this.progress.set(await this.api.runProgress());
    } catch {
      /* keep the last snapshot */
    }
  }

  async runNow(): Promise<void> {
    this.running.set(true);
    this.runError.set(null);
    try {
      this.summary.set(await this.api.run());
      await Promise.all([
        this.loadIncidents(),
        this.loadKpis(),
        this.loadHealth(),
        this.loadProgress(),
      ]);
    } catch (e) {
      this.runError.set(this.reason(e));
    } finally {
      this.running.set(false);
      await this.loadProgress();
    }
  }

  private reason(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }
}
