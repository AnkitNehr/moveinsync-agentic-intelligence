import {
  Component,
  EventEmitter,
  Output,
  OnInit,
  inject,
  signal,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService, HttpError } from '../core/api.service';
import type { Health, Incident, MetricObservation, RunSummary } from '../core/models';
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

        @if (s.stageTimings?.length) {
          <div class="stages scroll-x">
            @for (st of s.stageTimings; track st) {
              <span class="stage mono">{{ st }}</span>
            }
          </div>
        }
      } @else if (!running()) {
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

      .stages {
        display: flex;
        gap: 6px;
        margin-top: 9px;
        padding-bottom: 3px;
      }

      .stage {
        flex: none;
        padding: 3px 8px;
        border-radius: 4px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        color: var(--ink-muted);
        white-space: nowrap;
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
export class DashboardComponent implements OnInit {
  private readonly api = inject(ApiService);

  @Output() openIncident = new EventEmitter<string>();
  @Output() healthChanged = new EventEmitter<Health>();

  readonly health = signal<Health | null>(null);
  readonly summary = signal<RunSummary | null>(null);
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

  // re-exported for the template
  readonly num = num;
  readonly usd = usd;
  readonly ms = ms;
  readonly compact = compact;
  readonly pts = pts;
  readonly periodLabel = periodLabel;
  readonly shortTime = shortTime;
  readonly severityColor = severityColor;

  async ngOnInit(): Promise<void> {
    void this.loadHealth();
    void this.loadKpis();
    void this.loadLatestRun();
    void this.loadIncidents();
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
    // Rate metrics carry their delta in points already (see Trend javadoc).
    return k.unit === 'rate' ? pts(d) : byUnit(Math.abs(d), k.unit);
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

  async runNow(): Promise<void> {
    this.running.set(true);
    this.runError.set(null);
    try {
      this.summary.set(await this.api.run());
      await Promise.all([this.loadIncidents(), this.loadKpis(), this.loadHealth()]);
    } catch (e) {
      this.runError.set(this.reason(e));
    } finally {
      this.running.set(false);
    }
  }

  private reason(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
  }
}
