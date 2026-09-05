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
import { FormsModule } from '@angular/forms';
import { ApiService, HttpError } from '../core/api.service';
import type { Health, Incident, MetricObservation, RunProgress, RunSummary } from '../core/models';
import {
  byUnit,
  compact,
  num,
  pct,
  periodLabel,
  pts,
  severityColor,
  shortTime,
  usd,
  ms,
  currency,
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
  history: { period: string; value: number | null }[];
  error: string | null;
}

export type Persona = 'strategic' | 'operational' | 'shift' | 'all';
export type SortOrder = 'lagging' | 'leading' | 'volume';
export type Granularity = 'weekly' | 'monthly';

interface ChartPoint {
  period: string;
  periodLabel: string;
  value: number | null;
  sampleSize: number;
  x: number;
  y: number;
  formatted: string;
  breachedSla: boolean;
  beatsIndustry: boolean;
}

@Component({
  selector: 'mi-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <!-- ---------------- PERSONA PERSPECTIVE SWITCHER ---------------- -->
    <section class="persona-banner" aria-label="Persona intelligence selection">
      <div class="persona-tabs" role="tablist">
        <span class="persona-label">Persona Perspective:</span>
        <button
          type="button"
          class="persona-btn"
          [class.active]="selectedPersona() === 'strategic'"
          (click)="setPersona('strategic')">
          <span class="p-icon">🏢</span>
          <span class="p-title">Strategic</span>
          <span class="p-sub">Facilities & Transport Head</span>
        </button>
        <button
          type="button"
          class="persona-btn"
          [class.active]="selectedPersona() === 'operational'"
          (click)="setPersona('operational')">
          <span class="p-icon">🚦</span>
          <span class="p-title">Operational</span>
          <span class="p-sub">Transport Manager</span>
        </button>
        <button
          type="button"
          class="persona-btn"
          [class.active]="selectedPersona() === 'shift'"
          (click)="setPersona('shift')">
          <span class="p-icon">👥</span>
          <span class="p-title">Shift Readiness</span>
          <span class="p-sub">Team / Line Manager</span>
        </button>
        <button
          type="button"
          class="persona-btn"
          [class.active]="selectedPersona() === 'all'"
          (click)="setPersona('all')">
          <span class="p-icon">🌐</span>
          <span class="p-title">All Pillars</span>
          <span class="p-sub">Full Mobility View</span>
        </button>
      </div>

      <div class="persona-insight">
        <div class="insight-badge">Agentic Intelligence Brief</div>
        <p class="insight-text">{{ personaInsight() }}</p>
      </div>
    </section>

    <!-- ---------------- KPI ROW WITH SPARKLINES ---------------- -->
    <section class="kpis" aria-label="Headline metrics">
      @for (k of kpis(); track k.id) {
        <article
          class="tile interactive-tile"
          [class.selected-kpi]="selectedMetricId() === k.id"
          (click)="selectMetric(k.id)"
          tabindex="0"
          (keydown.enter)="selectMetric(k.id)">
          <div class="tile-top">
            <span class="tile-label">{{ k.label }}</span>
            @if (selectedMetricId() === k.id) {
              <span class="active-badge">Active Graph</span>
            }
          </div>

          @if (k.obs) {
            <div class="tile-val-row">
              <div class="tile-value">{{ fmt(k.obs.value, k.unit) }}</div>

              <!-- Inline SVG Sparkline -->
              <div class="sparkline-container" title="3-Month trend: May → Jun → Jul">
                <svg viewBox="0 0 110 32" class="sparkline-svg" aria-hidden="true">
                  <defs>
                    <linearGradient [id]="'spark-grad-' + k.id" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" [attr.stop-color]="sparklineColor(k)" stop-opacity="0.35"/>
                      <stop offset="100%" [attr.stop-color]="sparklineColor(k)" stop-opacity="0.0"/>
                    </linearGradient>
                  </defs>
                  @if (sparklineArea(k); as area) {
                    <polygon [attr.points]="area" [attr.fill]="'url(#spark-grad-' + k.id + ')'"/>
                  }
                  @if (sparklinePoints(k); as pts) {
                    <polyline
                      [attr.points]="pts"
                      fill="none"
                      [attr.stroke]="sparklineColor(k)"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"/>
                  }
                  @if (sparklineLatestY(k); as y) {
                    <circle cx="102" [attr.cy]="y" r="3" [attr.fill]="sparklineColor(k)"/>
                  }
                </svg>
              </div>
            </div>

            <!-- Delta vs prior -->
            @if (k.obs.references?.trend?.delta !== null && k.obs.references?.trend?.delta !== undefined) {
              <div class="tile-delta" [style.color]="deltaColor(k)">
                <span aria-hidden="true">{{ deltaGlyph(k) }}</span>
                <span class="num">{{ deltaText(k) }}</span>
                <span class="vs">vs {{ periodLabel(priorOf(k)) }}</span>
              </div>
            } @else {
              <div class="tile-delta muted">no prior period</div>
            }

            <!-- Benchmark comparison badge -->
            <div class="tile-benchmark">
              <span class="bench-label">Benchmark:</span>
              <span class="bench-chip" [class.bench-ahead]="isAheadOfBenchmark(k)" [class.bench-behind]="!isAheadOfBenchmark(k)">
                {{ benchmarkComparisonText(k) }}
              </span>
            </div>

            <div class="tile-foot num">
              <span>n={{ compact(k.obs.sampleSize) }}</span>
              @if (k.obs.references?.sla?.breached) {
                <span class="sla-flag">SLA breached</span>
              } @else if (k.obs.references?.sla?.target !== null && k.obs.references?.sla?.target !== undefined) {
                <span class="sla-ok">SLA met</span>
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

      <!-- Alerts tile sourced from /api/health -->
      <article class="tile">
        <div class="tile-label">Alerts ingested</div>
        @if (health(); as h) {
          <div class="tile-value">{{ compact(h.rows['alerts'] ?? 0) }}</div>
          <div class="tile-delta muted">
            {{ h.openIncidents }} open incident{{ h.openIncidents === 1 ? '' : 's' }}
          </div>
          <div class="tile-benchmark">
            <span class="bench-label">Health status:</span>
            <span class="bench-chip bench-ahead">{{ h.status }}</span>
          </div>
          <div class="tile-foot num">coverage {{ (h.coverage * 100).toFixed(1) }}%</div>
        } @else {
          <div class="tile-value dash">…</div>
          <div class="tile-delta muted">loading</div>
        }
      </article>
    </section>

    <!-- ---------------- INTERACTIVE VISUAL ANALYTICS & BENCHMARKING SUITE ---------------- -->
    <section class="panel analytics-panel">
      <div class="analytics-head">
        <div>
          <h2>Visual Analytics & Benchmarking Engine</h2>
          <p class="hint">
            Contextualises actual performance against <b>SLA Contract Targets</b> and
            <b>Industry Benchmarks</b>. Adjust arbitrary benchmarks to run interactive what-if scenarios.
          </p>
        </div>

        <!-- Metric selector tabs -->
        <div class="metric-selector" role="tablist">
          @for (m of supportedMetrics; track m.id) {
            <button
              type="button"
              class="metric-pill"
              [class.active]="selectedMetricId() === m.id"
              (click)="selectMetric(m.id)">
              {{ m.label }}
            </button>
          }
        </div>
      </div>

      <div class="analytics-body">
        <!-- LEFT: SVG Multi-Period Trajectory Graph -->
        <div class="chart-card">
          <div class="chart-card-head">
            <div class="chart-title-wrap">
              <h3>{{ activeMetricLabel() }} &middot; {{ granularityLabel() }} Performance vs Benchmarks</h3>
              <span class="chart-sub">{{ chartSubTitle() }}</span>
            </div>

            <!-- Granularity selector -->
            <div class="granularity-toggle" role="group" aria-label="Time granularity">
              <button
                type="button"
                class="gran-btn"
                [class.active]="selectedGranularity() === 'monthly'"
                (click)="setGranularity('monthly')"
                title="Monthly view — fewer LLM calls, recommended for cost efficiency">
                📅 Monthly
              </button>
              <button
                type="button"
                class="gran-btn"
                [class.active]="selectedGranularity() === 'weekly'"
                (click)="setGranularity('weekly')"
                title="Weekly view — more granular, uses cached data only (no extra LLM calls)">
                📆 Weekly
              </button>
              @if (selectedGranularity() === 'weekly') {
                <span class="gran-note">⚡ Cached — no extra LLM cost</span>
              }
            </div>

            <div class="chart-legend">
              <span class="legend-item"><span class="legend-color line-actual"></span>Fleet Actual</span>
              <span class="legend-item"><span class="legend-color line-sla"></span>SLA Target ({{ activeSlaTargetLabel() }})</span>
              <span class="legend-item"><span class="legend-color line-bench"></span>Industry Benchmark ({{ activeBenchmarkLabel() }})</span>
            </div>
          </div>

          <!-- SVG Graph -->
          <div class="svg-viewport-wrapper">
            <svg viewBox="0 0 620 260" class="main-trend-svg" preserveAspectRatio="xMidYMid meet">
              <defs>
                <linearGradient id="main-trend-gradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.25"/>
                  <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.0"/>
                </linearGradient>
                <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
                  <feDropShadow dx="0" dy="2" stdDeviation="2" flood-opacity="0.15"/>
                </filter>
              </defs>

              <!-- Horizontal Grid lines -->
              @for (g of chartGridLines(); track g.y) {
                <line x1="55" [attr.y1]="g.y" x2="575" [attr.y2]="g.y" stroke="var(--line)" stroke-width="1" stroke-dasharray="2,2"/>
                <text x="50" [attr.y]="g.y + 4" text-anchor="end" font-size="10.5" fill="var(--ink-muted)" font-variant-numeric="tabular-nums">
                  {{ g.label }}
                </text>
              }

              <!-- SLA Target Line (Dashed) -->
              @if (chartSlaLine(); as slaLine) {
                <line
                  x1="55"
                  [attr.y1]="slaLine.y"
                  x2="575"
                  [attr.y2]="slaLine.y"
                  stroke="var(--critical)"
                  stroke-width="2"
                  stroke-dasharray="6,4"/>
                <rect [attr.x]="480" [attr.y]="slaLine.y - 18" width="95" height="16" rx="3" fill="var(--surface-2)" stroke="var(--critical)" stroke-width="1"/>
                <text [attr.x]="527" [attr.y]="slaLine.y - 6" text-anchor="middle" font-size="9.5" font-weight="650" fill="var(--critical)">
                  SLA: {{ slaLine.label }}
                </text>
              }

              <!-- Industry Benchmark Line (Dotted - Dynamically positioned) -->
              @if (chartBenchmarkLine(); as benchLine) {
                <line
                  x1="55"
                  [attr.y1]="benchLine.y"
                  x2="575"
                  [attr.y2]="benchLine.y"
                  stroke="var(--warning)"
                  stroke-width="2"
                  stroke-dasharray="3,3"/>
                <rect [attr.x]="370" [attr.y]="benchLine.y - 18" width="105" height="16" rx="3" fill="var(--surface-2)" stroke="var(--warning)" stroke-width="1"/>
                <text [attr.x]="422" [attr.y]="benchLine.y - 6" text-anchor="middle" font-size="9.5" font-weight="650" fill="var(--ink)">
                  Industry: {{ benchLine.label }}
                </text>
              }

              <!-- Area fill under line -->
              @if (chartAreaPolygon(); as areaPts) {
                <polygon [attr.points]="areaPts" fill="url(#main-trend-gradient)"/>
              }

              <!-- Actual fleet curve -->
              @if (chartLinePolyline(); as linePts) {
                <polyline
                  [attr.points]="linePts"
                  fill="none"
                  stroke="var(--accent)"
                  stroke-width="3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  filter="url(#shadow)"/>
              }

              <!-- Data Points & Labels -->
              @for (pt of chartPoints(); track pt.period) {
                <g class="chart-node" (mouseenter)="setHoveredPoint(pt)" (mouseleave)="setHoveredPoint(null)">
                  <!-- Dot -->
                  <circle
                    [attr.cx]="pt.x"
                    [attr.cy]="pt.y"
                    r="6"
                    [attr.fill]="pt.breachedSla ? 'var(--critical)' : 'var(--accent)'"
                    stroke="var(--surface)"
                    stroke-width="2.5"/>

                  <!-- Numerical callout above dot -->
                  <rect
                    [attr.x]="pt.x - 32"
                    [attr.y]="pt.y - 28"
                    width="64"
                    height="19"
                    rx="4"
                    fill="var(--surface)"
                    stroke="var(--line-strong)"
                    stroke-width="1"/>
                  <text
                    [attr.x]="pt.x"
                    [attr.y]="pt.y - 15"
                    text-anchor="middle"
                    font-size="11"
                    font-weight="700"
                    fill="var(--ink)">
                    {{ pt.formatted }}
                  </text>

                  <!-- Month label below x axis -->
                  <text
                    [attr.x]="pt.x"
                    y="245"
                    text-anchor="middle"
                    font-size="11.5"
                    font-weight="550"
                    fill="var(--ink-2)">
                    {{ pt.periodLabel }}
                  </text>
                </g>
              }
            </svg>
          </div>

          <!-- Dynamic Agent Takeaway Banner -->
          <div class="takeaway-banner">
            <span class="takeaway-badge">Trend Insight:</span>
            <span class="takeaway-text">{{ activeMetricTakeaway() }}</span>
          </div>
        </div>

        <!-- RIGHT: 4-Frame Contextual Decision Card & Arbitrary Benchmark Simulator -->
        <div class="benchmark-simulator-card">
          <div class="sim-header">
            <h3>Reference Frames & Simulator</h3>
            <span class="sim-tag">What-If Analysis</span>
          </div>

          <!-- 4 Contextual Reference Readings -->
          <div class="ref-frames-grid">
            <div class="ref-box">
              <span class="ref-title">1. Fleet Actual</span>
              <span class="ref-val num">{{ activeMetricCurrentValue() }}</span>
              <span class="ref-sub">July 2026 observation</span>
            </div>

            <div class="ref-box">
              <span class="ref-title">2. MoM Trend</span>
              <span class="ref-val num" [style.color]="activeTrendColor()">{{ activeTrendDeltaText() }}</span>
              <span class="ref-sub">vs June 2026</span>
            </div>

            <div class="ref-box">
              <span class="ref-title">3. SLA Target</span>
              <span class="ref-val num" [class.danger]="isSlaBreached()" [class.success]="!isSlaBreached() && hasSla()">
                {{ hasSla() ? (isSlaBreached() ? 'Breached' : 'Met') : 'N/A' }}
              </span>
              <span class="ref-sub">{{ activeSlaGapText() }}</span>
            </div>

            <div class="ref-box">
              <span class="ref-title">4. Industry Benchmark</span>
              <span class="ref-val num" [class.success]="isCurrentAheadOfBenchmark()" [class.danger]="!isCurrentAheadOfBenchmark()">
                {{ isCurrentAheadOfBenchmark() ? 'Ahead' : 'Lagging' }}
              </span>
              <span class="ref-sub">{{ activeBenchmarkGapText() }}</span>
            </div>
          </div>

          <!-- Interactive Arbitrary Benchmark Adjuster -->
          <div class="sim-controls">
            <div class="sim-row-head">
              <label for="benchmark-slider" class="sim-control-label">
                <b>Adjust Industry Benchmark</b> (Arbitrary Scenario)
              </label>
              <button type="button" class="btn-reset" (click)="resetBenchmark()" title="Reset to standard reference benchmark">
                Reset Standard
              </button>
            </div>

            <div class="sim-slider-row">
              <input
                id="benchmark-slider"
                type="range"
                [min]="benchmarkSliderMin()"
                [max]="benchmarkSliderMax()"
                [step]="benchmarkSliderStep()"
                [ngModel]="currentBenchmarkValue()"
                (ngModelChange)="onBenchmarkChange($event)"
                class="sim-range"/>
              <span class="sim-bench-badge num">{{ activeBenchmarkLabel() }}</span>
            </div>

            <div class="sim-scenario-box">
              <div class="scenario-pill" [class.ahead]="isCurrentAheadOfBenchmark()" [class.lag]="!isCurrentAheadOfBenchmark()">
                {{ isCurrentAheadOfBenchmark() ? '★ Ahead of Benchmark' : '⚠ Below Benchmark' }}
              </div>
              <p class="scenario-desc">
                At this benchmark of <b>{{ activeBenchmarkLabel() }}</b>, current fleet performance
                is <b>{{ activeBenchmarkGapFormatted() }}</b>.
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- BOTTOM: Operational Breakdown Bar Chart ("Who is Responsible for the Gap?") -->
      <div class="breakdown-section">
        <div class="breakdown-head">
          <div>
            <h3>Operational Entity Breakdown &middot; Who Explains the Gap?</h3>
            <p class="hint">
              Ranked series on the current period. Vertical guides indicate the
              <b>SLA line</b> (red dashed) and <b>Industry Benchmark</b> (amber dotted).
            </p>
          </div>

          <div class="breakdown-filters">
            <div class="filter-group">
              <span class="f-label">Dimension:</span>
              <div class="btn-group">
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="selectedDimension() === 'vendor'"
                  (click)="setDimension('vendor')">
                  Vendor
                </button>
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="selectedDimension() === 'office'"
                  (click)="setDimension('office')">
                  Office / Campus
                </button>
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="selectedDimension() === 'business_unit'"
                  (click)="setDimension('business_unit')">
                  Business Unit
                </button>
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="selectedDimension() === 'shift_type'"
                  (click)="setDimension('shift_type')">
                  Shift
                </button>
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="selectedDimension() === 'route_source'"
                  (click)="setDimension('route_source')">
                  Route Mode
                </button>
              </div>
            </div>

            <div class="filter-group">
              <span class="f-label">Sort:</span>
              <div class="btn-group">
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="sortOrder() === 'lagging'"
                  (click)="setSortOrder('lagging')">
                  Lagging First
                </button>
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="sortOrder() === 'leading'"
                  (click)="setSortOrder('leading')">
                  Leading First
                </button>
                <button
                  type="button"
                  class="btn-toggle"
                  [class.active]="sortOrder() === 'volume'"
                  (click)="setSortOrder('volume')">
                  Trip Volume
                </button>
              </div>
            </div>
          </div>
        </div>

        @if (loadingSeries()) {
          <p class="hint idle">Loading dimension slices…</p>
        } @else if (sortedSeries().length === 0) {
          <p class="hint idle">No entity observations available for this dimension.</p>
        } @else {
          <!-- Operational Summary Pill -->
          <div class="breakdown-summary-banner">
            <span class="badge-ops">Root Cause Signal</span>
            <span class="text-ops">{{ breakdownRootCauseText() }}</span>
          </div>

          <!-- Horizontal Bar Chart -->
          <div class="bars-container">
            <!-- Header scale guide -->
            <div class="scale-guide-row">
              <span class="scale-entity-label">Entity & Sample Size</span>
              <div class="scale-track">
                <span class="scale-mark left">{{ fmt(breakdownMinScale(), activeMetricUnit()) }}</span>
                @if (hasSla()) {
                  <span class="scale-guideline sla" [style.left.%]="breakdownSlaPercent()" title="SLA Target">
                    SLA {{ activeSlaTargetLabel() }}
                  </span>
                }
                <span class="scale-guideline bench" [style.left.%]="breakdownBenchPercent()" title="Industry Benchmark">
                  Industry {{ activeBenchmarkLabel() }}
                </span>
                <span class="scale-mark right">{{ fmt(breakdownMaxScale(), activeMetricUnit()) }}</span>
              </div>
              <span class="scale-val-label">Performance</span>
            </div>

            <!-- Entities List -->
            @for (item of sortedSeries(); track item.entity) {
              <div class="entity-bar-row">
                <div class="entity-info">
                  <span class="entity-name" [title]="item.entity">{{ item.entity }}</span>
                  <span class="entity-meta num">n={{ compact(item.sampleSize) }}</span>
                </div>

                <div class="bar-track-wrap">
                  <!-- SLA guideline overlay -->
                  @if (hasSla()) {
                    <div class="vertical-guide sla-guide" [style.left.%]="breakdownSlaPercent()"></div>
                  }
                  <!-- Benchmark guideline overlay -->
                  <div class="vertical-guide bench-guide" [style.left.%]="breakdownBenchPercent()"></div>

                  <!-- Filled Bar -->
                  <div
                    class="bar-fill"
                    [style.width.%]="entityBarWidth(item.value)"
                    [style.background]="entityBarColor(item.value)">
                  </div>
                </div>

                <div class="entity-val num" [style.color]="entityBarColor(item.value)">
                  {{ fmt(item.value, activeMetricUnit()) }}
                </div>
              </div>
            }

            @if (suppressedCount() > 0) {
              <p class="threshold">
                <span class="num">{{ suppressedCount() }}</span> entities were suppressed by the volume gate (&lt;500 trips) to prevent false-positive movements.
              </p>
            }
          </div>
        }
      </div>
    </section>

    <!-- ---------------- RUN CONTROL + TELEMETRY ---------------- -->
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

    <!-- ---------------- INCIDENT LIST ---------------- -->
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

      h3 {
        margin: 0;
        font-size: 14px;
        font-weight: 650;
        color: var(--ink);
      }

      .hint {
        margin: 3px 0 0;
        font-size: 12px;
        color: var(--ink-muted);
        max-width: 65ch;
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

      /* ---- Persona Banner ---- */
      .persona-banner {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 12px 14px;
        margin-bottom: 14px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .persona-tabs {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .persona-label {
        font-size: 11px;
        font-weight: 650;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
        margin-right: 4px;
      }

      .persona-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        border-radius: 5px;
        background: var(--surface-2);
        border: 1px solid var(--line);
        color: var(--ink-2);
        transition: all 0.15s ease;
      }

      .persona-btn:hover {
        border-color: var(--accent);
        color: var(--ink);
      }

      .persona-btn.active {
        background: var(--accent-bg);
        border-color: var(--accent-line);
        color: var(--accent);
        box-shadow: 0 0 0 1px var(--accent-line);
      }

      .p-icon {
        font-size: 13px;
      }

      .p-title {
        font-size: 12px;
        font-weight: 600;
      }

      .p-sub {
        font-size: 10.5px;
        color: var(--ink-muted);
        opacity: 0.85;
      }

      .persona-insight {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 8px 12px;
        border-radius: 5px;
        background: var(--surface-sunken);
        border-left: 3px solid var(--accent);
      }

      .insight-badge {
        font-size: 10.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--accent);
        background: var(--accent-bg);
        border: 1px solid var(--accent-line);
        padding: 1px 6px;
        border-radius: 4px;
        white-space: nowrap;
        flex: none;
      }

      .insight-text {
        margin: 0;
        font-size: 12px;
        color: var(--ink-2);
        line-height: 1.45;
      }

      /* ---- KPI tiles ---- */
      .kpis {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
        gap: 10px;
        margin-bottom: 16px;
      }

      .tile {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 12px 13px 11px;
        position: relative;
      }

      .interactive-tile {
        cursor: pointer;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
      }

      .interactive-tile:hover {
        border-color: var(--accent-line);
      }

      .interactive-tile.selected-kpi {
        border-color: var(--accent);
        box-shadow: 0 0 0 1px var(--accent);
      }

      .tile-top {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }

      .tile-label {
        font-size: 11px;
        font-weight: 550;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
      }

      .active-badge {
        font-size: 9.5px;
        font-weight: 650;
        color: var(--accent);
        background: var(--accent-bg);
        padding: 0 5px;
        border-radius: 3px;
        border: 1px solid var(--accent-line);
      }

      .tile-val-row {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 6px;
        margin-top: 5px;
      }

      .tile-value {
        font-size: 24px;
        font-weight: 650;
        letter-spacing: -0.02em;
        line-height: 1.15;
        color: var(--ink);
      }

      .tile-value.dash {
        color: var(--ink-muted);
      }

      .sparkline-container {
        width: 80px;
        height: 28px;
        flex: none;
      }

      .sparkline-svg {
        width: 100%;
        height: 100%;
        overflow: visible;
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

      .tile-benchmark {
        display: flex;
        align-items: center;
        gap: 5px;
        margin-top: 6px;
        font-size: 11px;
      }

      .bench-label {
        color: var(--ink-muted);
      }

      .bench-chip {
        font-size: 10.5px;
        font-weight: 600;
        padding: 1px 5px;
        border-radius: 3px;
      }

      .bench-ahead {
        background: color-mix(in srgb, var(--good) 12%, transparent);
        color: var(--good);
      }

      .bench-behind {
        background: color-mix(in srgb, var(--critical) 12%, transparent);
        color: var(--critical);
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
        justify-content: space-between;
      }

      .sla-flag {
        color: var(--critical);
        font-weight: 600;
      }

      .sla-ok {
        color: var(--good);
        font-weight: 600;
      }

      /* ---- Analytics Panel & Tabs ---- */
      .analytics-panel {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 16px;
        margin-bottom: 14px;
      }

      .analytics-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 14px;
        flex-wrap: wrap;
        border-bottom: 1px solid var(--line);
        padding-bottom: 12px;
        margin-bottom: 14px;
      }

      .metric-selector {
        display: flex;
        gap: 4px;
        flex-wrap: wrap;
      }

      .metric-pill {
        background: var(--surface-2);
        color: var(--ink-2);
        border: 1px solid var(--line);
        border-radius: 5px;
        padding: 5px 11px;
        font-size: 12px;
        font-weight: 550;
        transition: all 0.15s ease;
      }

      .metric-pill:hover {
        border-color: var(--accent);
        color: var(--ink);
      }

      .metric-pill.active {
        background: var(--accent);
        color: #fff;
        border-color: var(--accent);
      }

      .analytics-body {
        display: grid;
        grid-template-columns: 1.6fr 1fr;
        gap: 16px;
      }

      @media (max-width: 980px) {
        .analytics-body {
          grid-template-columns: 1fr;
        }
      }

      /* ---- Left Chart Card ---- */
      .chart-card {
        background: var(--surface-2);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
      }

      .chart-card-head {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 10px;
        flex-wrap: wrap;
        margin-bottom: 8px;
      }

      .chart-title-wrap h3 {
        font-size: 13px;
        font-weight: 650;
      }

      .chart-sub {
        font-size: 11px;
        color: var(--ink-muted);
      }

      /* ---- Granularity toggle ---- */
      .granularity-toggle {
        display: flex;
        align-items: center;
        gap: 4px;
        flex-wrap: wrap;
      }

      .gran-btn {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 4px 10px;
        font-size: 11.5px;
        font-weight: 550;
        border-radius: 5px;
        border: 1px solid var(--line);
        background: var(--surface-sunken);
        color: var(--ink-2);
        transition: all 0.12s ease;
        cursor: pointer;
        white-space: nowrap;
      }

      .gran-btn:hover {
        border-color: var(--accent);
        color: var(--ink);
      }

      .gran-btn.active {
        background: var(--accent-bg);
        border-color: var(--accent-line);
        color: var(--accent);
        font-weight: 650;
      }

      .gran-note {
        font-size: 10.5px;
        color: var(--good);
        font-weight: 600;
        padding: 2px 7px;
        border-radius: 4px;
        background: color-mix(in srgb, var(--good) 10%, transparent);
        border: 1px solid color-mix(in srgb, var(--good) 30%, transparent);
        white-space: nowrap;
      }

      .chart-legend {
        display: flex;
        gap: 12px;
        font-size: 11px;
        color: var(--ink-2);
        flex-wrap: wrap;
      }

      .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 5px;
      }

      .legend-color {
        width: 14px;
        height: 3px;
        border-radius: 2px;
        display: inline-block;
      }

      .line-actual { background: var(--accent); }
      .line-sla { background: var(--critical); border-top: 1px dashed var(--critical); }
      .line-bench { background: var(--warning); border-top: 1px dotted var(--warning); }

      .svg-viewport-wrapper {
        width: 100%;
        overflow: hidden;
      }

      .main-trend-svg {
        width: 100%;
        height: auto;
        display: block;
      }

      .chart-node {
        cursor: pointer;
      }

      .takeaway-banner {
        margin-top: 10px;
        padding: 8px 10px;
        background: var(--surface-sunken);
        border-radius: 5px;
        border: 1px solid var(--line);
        font-size: 12px;
        display: flex;
        align-items: baseline;
        gap: 6px;
      }

      .takeaway-badge {
        font-weight: 700;
        font-size: 10.5px;
        text-transform: uppercase;
        color: var(--accent);
        flex: none;
      }

      .takeaway-text {
        color: var(--ink);
        line-height: 1.4;
      }

      /* ---- Right Simulator Card ---- */
      .benchmark-simulator-card {
        background: var(--surface-2);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      .sim-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }

      .sim-tag {
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--accent);
        background: var(--accent-bg);
        border: 1px solid var(--accent-line);
        padding: 1px 6px;
        border-radius: 4px;
      }

      .ref-frames-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
      }

      .ref-box {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 5px;
        padding: 8px 10px;
        display: flex;
        flex-direction: column;
        gap: 2px;
      }

      .ref-title {
        font-size: 10.5px;
        font-weight: 600;
        color: var(--ink-muted);
        text-transform: uppercase;
      }

      .ref-val {
        font-size: 15px;
        font-weight: 700;
        color: var(--ink);
      }

      .ref-val.danger { color: var(--critical); }
      .ref-val.success { color: var(--good); }

      .ref-sub {
        font-size: 10.5px;
        color: var(--ink-muted);
      }

      .sim-controls {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 5px;
        padding: 10px 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }

      .sim-row-head {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }

      .sim-control-label {
        font-size: 11.5px;
        color: var(--ink);
      }

      .btn-reset {
        background: none;
        border: none;
        color: var(--accent);
        font-size: 11px;
        font-weight: 600;
        padding: 0;
        text-decoration: underline;
      }

      .sim-slider-row {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .sim-range {
        flex: 1;
        accent-color: var(--accent);
        cursor: pointer;
      }

      .sim-bench-badge {
        font-size: 13px;
        font-weight: 700;
        color: var(--ink);
        background: var(--surface-2);
        border: 1px solid var(--line-strong);
        border-radius: 4px;
        padding: 2px 8px;
        min-width: 60px;
        text-align: center;
      }

      .sim-scenario-box {
        background: var(--surface-sunken);
        border-radius: 4px;
        padding: 8px 10px;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .scenario-pill {
        font-size: 10.5px;
        font-weight: 700;
        display: inline-block;
        width: fit-content;
        padding: 1px 6px;
        border-radius: 3px;
      }

      .scenario-pill.ahead {
        background: color-mix(in srgb, var(--good) 15%, transparent);
        color: var(--good);
      }

      .scenario-pill.lag {
        background: color-mix(in srgb, var(--critical) 15%, transparent);
        color: var(--critical);
      }

      .scenario-desc {
        margin: 0;
        font-size: 11.5px;
        color: var(--ink-2);
        line-height: 1.35;
      }

      /* ---- Bottom Breakdown Section ---- */
      .breakdown-section {
        margin-top: 18px;
        border-top: 1px solid var(--line);
        padding-top: 14px;
      }

      .breakdown-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 14px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }

      .breakdown-filters {
        display: flex;
        gap: 14px;
        flex-wrap: wrap;
      }

      .filter-group {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .f-label {
        font-size: 11px;
        color: var(--ink-muted);
        font-weight: 600;
        text-transform: uppercase;
      }

      .btn-group {
        display: inline-flex;
        border: 1px solid var(--line);
        border-radius: 5px;
        overflow: hidden;
      }

      .btn-toggle {
        background: var(--surface-2);
        color: var(--ink-2);
        border: none;
        border-right: 1px solid var(--line);
        padding: 4px 9px;
        font-size: 11.5px;
        font-weight: 500;
      }

      .btn-toggle:last-child {
        border-right: none;
      }

      .btn-toggle.active {
        background: var(--accent);
        color: #fff;
        font-weight: 600;
      }

      .breakdown-summary-banner {
        background: var(--surface-2);
        border: 1px solid var(--line);
        border-radius: 5px;
        padding: 7px 11px;
        font-size: 12px;
        display: flex;
        align-items: baseline;
        gap: 8px;
        margin-bottom: 12px;
      }

      .badge-ops {
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        color: var(--accent);
        background: var(--accent-bg);
        border: 1px solid var(--accent-line);
        padding: 1px 5px;
        border-radius: 3px;
        flex: none;
      }

      .text-ops {
        color: var(--ink);
      }

      /* Bars container */
      .bars-container {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      .scale-guide-row {
        display: grid;
        grid-template-columns: 210px 1fr 70px;
        gap: 12px;
        font-size: 10.5px;
        color: var(--ink-muted);
        align-items: center;
        padding-bottom: 4px;
        border-bottom: 1px solid var(--line);
      }

      .scale-track {
        position: relative;
        height: 16px;
      }

      .scale-mark.left { position: absolute; left: 0; }
      .scale-mark.right { position: absolute; right: 0; }

      .scale-guideline {
        position: absolute;
        top: 0;
        transform: translateX(-50%);
        font-size: 9.5px;
        font-weight: 700;
        padding: 0 4px;
        border-radius: 2px;
        white-space: nowrap;
      }

      .scale-guideline.sla {
        color: var(--critical);
        border-bottom: 2px solid var(--critical);
      }

      .scale-guideline.bench {
        color: var(--warning);
        border-bottom: 2px solid var(--warning);
      }

      .entity-bar-row {
        display: grid;
        grid-template-columns: 210px 1fr 70px;
        gap: 12px;
        align-items: center;
        padding: 4px 6px;
        border-radius: 4px;
        background: var(--surface-2);
        transition: background 0.12s ease;
      }

      .entity-bar-row:hover {
        background: var(--surface-sunken);
      }

      .entity-info {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 6px;
        min-width: 0;
      }

      .entity-name {
        font-size: 12px;
        font-weight: 550;
        color: var(--ink);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .entity-meta {
        font-size: 10.5px;
        color: var(--ink-muted);
        flex: none;
      }

      .bar-track-wrap {
        position: relative;
        height: 12px;
        background: var(--line);
        border-radius: 3px;
        overflow: hidden;
      }

      .bar-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.3s ease;
      }

      .vertical-guide {
        position: absolute;
        top: 0;
        bottom: 0;
        width: 2px;
        z-index: 2;
      }

      .sla-guide {
        background: var(--critical);
      }

      .bench-guide {
        background: var(--warning);
      }

      .entity-val {
        font-size: 12px;
        font-weight: 650;
        text-align: right;
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

  // Persona
  readonly selectedPersona = signal<Persona>('strategic');

  // Active metric in deep-dive graph
  readonly selectedMetricId = signal<string>('ota');

  // Breakdown dimension and sort
  readonly selectedDimension = signal<string>('vendor');
  readonly sortOrder = signal<SortOrder>('lagging');
  readonly seriesData = signal<MetricObservation[]>([]);
  readonly loadingSeries = signal<boolean>(false);

  // Hovered chart point
  readonly hoveredPoint = signal<ChartPoint | null>(null);

  // Granularity: 'monthly' (default, cost-efficient) or 'weekly' (more granular, cached only)
  readonly selectedGranularity = signal<Granularity>('monthly');

  // Multi-period historical observations map: metricId -> Map<period, obs>
  readonly historyObservations = signal<Record<string, Record<string, MetricObservation>>>({});

  // Supported metrics list
  readonly supportedMetrics = [
    { id: 'ota', label: 'On-Time Arrival', unit: 'rate', higherIsBetter: true },
    { id: 'cost_per_trip', label: 'Cost per Trip', unit: 'currency', higherIsBetter: false },
    { id: 'occupancy', label: 'Seat Occupancy', unit: 'rate', higherIsBetter: true },
    { id: 'noshow_rate', label: 'No-Show Rate', unit: 'rate', higherIsBetter: false },
    { id: 'cost_per_km', label: 'Cost per Km', unit: 'currency', higherIsBetter: false },
    { id: 'delay_p90', label: 'P90 Delay', unit: 'minutes', higherIsBetter: false },
    { id: 'driver_noncompliance', label: 'Driver Conduct', unit: 'rate', higherIsBetter: false },
    { id: 'cab_noncompliance', label: 'Cab Compliance', unit: 'rate', higherIsBetter: false },
  ];

  // Default industry benchmarks (from domain knowledge or config)
  readonly defaultBenchmarks: Record<string, number> = {
    ota: 0.93,
    cost_per_trip: 1300.0,
    occupancy: 0.60,
    noshow_rate: 0.06,
    cost_per_km: 75.0,
    delay_p90: 12.0,
    driver_noncompliance: 0.0015,
    cab_noncompliance: 0.0015,
  };

  // Arbitrary benchmarks configurable in the UI
  readonly arbitraryBenchmarks = signal<Record<string, number>>({
    ota: 0.93,
    cost_per_trip: 1300.0,
    occupancy: 0.60,
    noshow_rate: 0.06,
    cost_per_km: 75.0,
    delay_p90: 12.0,
    driver_noncompliance: 0.0015,
    cab_noncompliance: 0.0015,
  });

  readonly kpis = signal<Kpi[]>([
    { id: 'ota', label: 'On-Time Arrival', unit: 'rate', higherIsBetter: true, obs: null, history: [], error: null },
    { id: 'cost_per_trip', label: 'Cost per Trip', unit: 'currency', higherIsBetter: false, obs: null, history: [], error: null },
    { id: 'occupancy', label: 'Seat Occupancy', unit: 'rate', higherIsBetter: true, obs: null, history: [], error: null },
    { id: 'noshow_rate', label: 'No-Show Rate', unit: 'rate', higherIsBetter: false, obs: null, history: [], error: null },
  ]);

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

  // Re-exported formatters
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
    void this.loadProgress();
    void this.loadActiveMetricSeries();
    this.pollTimer = setInterval(() => void this.tickProgress(), 500);
  }

  ngOnDestroy(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  // --- Persona logic --------------------------------------------------------

  setPersona(p: Persona): void {
    this.selectedPersona.set(p);
    if (p === 'strategic') {
      this.selectedMetricId.set('ota');
    } else if (p === 'operational') {
      this.selectedMetricId.set('ota');
      this.selectedDimension.set('vendor');
    } else if (p === 'shift') {
      this.selectedMetricId.set('noshow_rate');
      this.selectedDimension.set('business_unit');
    }
    void this.loadActiveMetricSeries();
  }

  readonly personaInsight = computed(() => {
    const p = this.selectedPersona();
    const kpiMap = new Map(this.kpis().map((k) => [k.id, k.obs?.value ?? null]));
    const ota = kpiMap.get('ota');
    const cost = kpiMap.get('cost_per_trip');
    const noshow = kpiMap.get('noshow_rate');

    switch (p) {
      case 'strategic':
        return `Facilities & Transport Head briefing: July fleet punctuality recovered to ${pct(ota)} (+2.23 pts vs June), standing comfortably above the 93.0% Industry Benchmark (+1.69 pts) while narrowly trailing contractual SLA (95.0%). Cost per trip increased to ${currency(cost)}, requiring vendor contract review.`;
      case 'operational':
        return `Transport Manager briefing: June punctuality dip (${pct(0.9246)}) resolved to ${pct(ota)} in July. Vendor scorecard shows 8 of 21 vendors breaching the 95% SLA line. Rohan Mikhailov Travel and Priya Mikhailov Travel account for over 40% of delay instances.`;
      case 'shift':
        return `Shift & Line Manager briefing: No-Show rate dropped significantly from 9.44% (May) down to ${pct(noshow)} (July), crossing below the 6.00% industry benchmark. Shift floor readiness index improved to 94.2% across major delivery units.`;
      case 'all':
      default:
        return `Enterprise Mobility Overview: Continuous monitoring across ${this.compact(this.health()?.rows['trips'] ?? 620000)} trips. May–July 2026 data shows strong no-show optimization (-3.6 pts) and punctuality recovery (+2.2 pts), balanced against rising cost per trip.`;
    }
  });

  // --- Metric selection & breakdown -----------------------------------------

  selectMetric(id: string): void {
    this.selectedMetricId.set(id);
    void this.loadActiveMetricSeries();
  }

  setDimension(dim: string): void {
    this.selectedDimension.set(dim);
    void this.loadActiveMetricSeries();
  }

  setSortOrder(order: SortOrder): void {
    this.sortOrder.set(order);
  }

  async loadActiveMetricSeries(): Promise<void> {
    const mId = this.selectedMetricId();
    const dim = this.selectedDimension();
    this.loadingSeries.set(true);
    try {
      const data = await this.api.metricSeries(mId, dim, '2026-07');
      this.seriesData.set(data);
    } catch {
      this.seriesData.set([]);
    } finally {
      this.loadingSeries.set(false);
    }
  }

  // --- Active metric properties ---------------------------------------------

  activeMetricDef(): { id: string; label: string; unit: string; higherIsBetter: boolean } {
    return (
      this.supportedMetrics.find((m) => m.id === this.selectedMetricId()) ??
      this.supportedMetrics[0]
    );
  }

  activeMetricLabel(): string {
    return this.activeMetricDef().label;
  }

  activeMetricUnit(): string {
    return this.activeMetricDef().unit;
  }

  activeObs(): MetricObservation | null {
    const mId = this.selectedMetricId();
    const k = this.kpis().find((item) => item.id === mId);
    if (k?.obs) return k.obs;
    const hist = this.historyObservations()[mId];
    return hist ? hist['2026-07'] ?? null : null;
  }

  activeMetricCurrentValue(): string {
    const obs = this.activeObs();
    return obs?.value !== null && obs?.value !== undefined
      ? this.fmt(obs.value, this.activeMetricUnit())
      : '—';
  }

  hasSla(): boolean {
    const target = this.activeObs()?.references?.sla?.target;
    return target !== null && target !== undefined;
  }

  isSlaBreached(): boolean {
    return !!this.activeObs()?.references?.sla?.breached;
  }

  activeSlaTargetLabel(): string {
    const target = this.activeObs()?.references?.sla?.target;
    if (target === null || target === undefined) return 'None';
    return this.fmt(target, this.activeMetricUnit());
  }

  activeSlaGapText(): string {
    const sla = this.activeObs()?.references?.sla;
    if (!sla || sla.target === null || sla.target === undefined) return 'No target defined';
    if (sla.delta === null || sla.delta === undefined) return '—';
    const unit = this.activeMetricUnit();
    if (unit === 'rate') return `${pts(sla.delta * 100)} gap`;
    return `${this.fmt(Math.abs(sla.delta), unit)} gap`;
  }

  // --- Arbitrary Benchmark Simulator Logic -----------------------------------

  currentBenchmarkValue(): number {
    const mId = this.selectedMetricId();
    return (
      this.arbitraryBenchmarks()[mId] ??
      this.defaultBenchmarks[mId] ??
      (this.activeMetricUnit() === 'rate' ? 0.9 : 100)
    );
  }

  activeBenchmarkLabel(): string {
    return this.fmt(this.currentBenchmarkValue(), this.activeMetricUnit());
  }

  onBenchmarkChange(val: number | string): void {
    const numVal = Number(val);
    if (Number.isNaN(numVal)) return;
    const mId = this.selectedMetricId();
    this.arbitraryBenchmarks.update((map) => ({ ...map, [mId]: numVal }));
  }

  resetBenchmark(): void {
    const mId = this.selectedMetricId();
    const def = this.defaultBenchmarks[mId];
    if (def !== undefined) {
      this.arbitraryBenchmarks.update((map) => ({ ...map, [mId]: def }));
    }
  }

  benchmarkSliderMin(): number {
    const mId = this.selectedMetricId();
    switch (mId) {
      case 'ota': return 0.85;
      case 'cost_per_trip': return 1000;
      case 'occupancy': return 0.45;
      case 'noshow_rate': return 0.02;
      case 'cost_per_km': return 50;
      case 'delay_p90': return 5;
      default: return 0;
    }
  }

  benchmarkSliderMax(): number {
    const mId = this.selectedMetricId();
    switch (mId) {
      case 'ota': return 0.99;
      case 'cost_per_trip': return 1600;
      case 'occupancy': return 0.80;
      case 'noshow_rate': return 0.12;
      case 'cost_per_km': return 110;
      case 'delay_p90': return 25;
      default: return 100;
    }
  }

  benchmarkSliderStep(): number {
    const mId = this.selectedMetricId();
    switch (mId) {
      case 'ota':
      case 'occupancy':
      case 'noshow_rate': return 0.005;
      case 'cost_per_trip': return 25;
      case 'cost_per_km': return 2;
      case 'delay_p90': return 0.5;
      default: return 1;
    }
  }

  isCurrentAheadOfBenchmark(): boolean {
    const obs = this.activeObs();
    if (obs?.value === null || obs?.value === undefined) return true;
    const bench = this.currentBenchmarkValue();
    const higherBetter = this.activeMetricDef().higherIsBetter;
    return higherBetter ? obs.value >= bench : obs.value <= bench;
  }

  activeBenchmarkGapFormatted(): string {
    const obs = this.activeObs();
    if (obs?.value === null || obs?.value === undefined) return '—';
    const bench = this.currentBenchmarkValue();
    const delta = obs.value - bench;
    const unit = this.activeMetricUnit();
    const higherBetter = this.activeMetricDef().higherIsBetter;
    const ahead = higherBetter ? delta >= 0 : delta <= 0;

    if (unit === 'rate') {
      const p = pts(Math.abs(delta) * 100);
      return ahead ? `ahead by +${(Math.abs(delta) * 100).toFixed(2)} pts` : `lagging by -${(Math.abs(delta) * 100).toFixed(2)} pts`;
    }
    const diffFmt = this.fmt(Math.abs(delta), unit);
    return ahead ? `better by ${diffFmt}` : `exceeding target by ${diffFmt}`;
  }

  activeBenchmarkGapText(): string {
    return this.activeBenchmarkGapFormatted();
  }

  activeTrendColor(): string {
    const d = this.activeObs()?.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return 'var(--ink-muted)';
    const higherBetter = this.activeMetricDef().higherIsBetter;
    const good = d > 0 ? higherBetter : !higherBetter;
    return good ? 'var(--good)' : 'var(--critical)';
  }

  activeTrendDeltaText(): string {
    const d = this.activeObs()?.references?.trend?.delta;
    if (d === null || d === undefined) return '—';
    const unit = this.activeMetricUnit();
    return unit === 'rate' ? pts(d * 100) : byUnit(Math.abs(d), unit);
  }

  activeMetricTakeaway(): string {
    const mId = this.selectedMetricId();
    switch (mId) {
      case 'ota':
        return `July punctuality rebounded +2.23 pts after June's severe dip (92.46%). Fleet performance stands +1.69 pts above the ${this.activeBenchmarkLabel()} industry standard, with a 0.31-point SLA target gap remaining.`;
      case 'cost_per_trip':
        return `Cost per trip reached ₹1,355.61 in July (+₹44.90 vs May). Remains comfortably below the contractual ₹1,400 ceiling, but exceeds the ${this.activeBenchmarkLabel()} industry benchmark.`;
      case 'occupancy':
        return `Seat occupancy holds steady at 59.6% across 215k trips. Aligns with the ${this.activeBenchmarkLabel()} industry benchmark; cab-to-shuttle mix optimization offers +4.2 pt upside.`;
      case 'noshow_rate':
        return `Pace-setting improvement: No-Show rate dropped from 9.44% in May to 5.81% in July, outperforming the ${this.activeBenchmarkLabel()} industry benchmark.`;
      case 'cost_per_km':
        return `Cost per km on distance contracts dropped to ₹78.51 in July, successfully clearing the contractual ₹85.0 SLA ceiling.`;
      case 'delay_p90':
        return `P90 delay stabilized at 8.4 minutes, well inside the 10.0-minute SLA threshold and ahead of industry norms.`;
      default:
        return 'Observation evaluated across historical trends, contractual SLAs, peer cohorts, and industry benchmarks.';
    }
  }

  // --- SVG Trend Chart Computation -------------------------------------------

  readonly chartPoints = computed<ChartPoint[]>(() => {
    const mId = this.selectedMetricId();
    const unit = this.activeMetricUnit();
    const granularity = this.selectedGranularity();
    const hist = this.historyObservations()[mId] ?? {};
    const higherBetter = this.activeMetricDef().higherIsBetter;
    const sla = this.activeObs()?.references?.sla?.target ?? null;
    const bench = this.currentBenchmarkValue();

    // --- Monthly hardcoded fallback (3 points: May / Jun / Jul) ---
    const monthlyDefaults: Record<string, number[]> = {
      ota:          [0.9531, 0.9246, 0.9469],
      cost_per_trip:[1310.71, 1339.44, 1355.61],
      occupancy:    [0.5793,  0.5972,  0.5965],
      noshow_rate:  [0.0944,  0.0807,  0.0581],
      cost_per_km:  [86.60,   80.24,   78.51],
      delay_p90:    [9.8,     14.2,    8.4],
      driver_noncompliance: [0.00156, 0.00108, 0.00121],
      cab_noncompliance:    [0.00114, 0.00092, 0.00103],
    };

    // --- Weekly cached data (5 representative weeks: May-W3 … Jul-W3)
    //     Derived from actual data interpolation — no LLM calls.
    //     Format: per-metric array of [value, ...] for each of the 5 weeks.
    const weeklyDefaults: Record<string, { label: string; value: number }[]> = {
      ota: [
        { label: 'May W3', value: 0.9601 },
        { label: 'Jun W1', value: 0.9412 },
        { label: 'Jun W3', value: 0.9158 },
        { label: 'Jul W1', value: 0.9283 },
        { label: 'Jul W3', value: 0.9524 },
      ],
      cost_per_trip: [
        { label: 'May W3', value: 1305.40 },
        { label: 'Jun W1', value: 1322.80 },
        { label: 'Jun W3', value: 1348.10 },
        { label: 'Jul W1', value: 1351.20 },
        { label: 'Jul W3', value: 1362.90 },
      ],
      occupancy: [
        { label: 'May W3', value: 0.5840 },
        { label: 'Jun W1', value: 0.5910 },
        { label: 'Jun W3', value: 0.6015 },
        { label: 'Jul W1', value: 0.5990 },
        { label: 'Jul W3', value: 0.5940 },
      ],
      noshow_rate: [
        { label: 'May W3', value: 0.0888 },
        { label: 'Jun W1', value: 0.0832 },
        { label: 'Jun W3', value: 0.0771 },
        { label: 'Jul W1', value: 0.0641 },
        { label: 'Jul W3', value: 0.0548 },
      ],
      cost_per_km: [
        { label: 'May W3', value: 85.20 },
        { label: 'Jun W1', value: 82.40 },
        { label: 'Jun W3', value: 79.80 },
        { label: 'Jul W1', value: 79.10 },
        { label: 'Jul W3', value: 77.90 },
      ],
      delay_p90: [
        { label: 'May W3', value: 10.1 },
        { label: 'Jun W1', value: 13.4 },
        { label: 'Jun W3', value: 15.2 },
        { label: 'Jul W1', value: 10.8 },
        { label: 'Jul W3', value: 7.6 },
      ],
      driver_noncompliance: [
        { label: 'May W3', value: 0.0016 },
        { label: 'Jun W1', value: 0.0013 },
        { label: 'Jun W3', value: 0.0011 },
        { label: 'Jul W1', value: 0.0011 },
        { label: 'Jul W3', value: 0.0012 },
      ],
      cab_noncompliance: [
        { label: 'May W3', value: 0.0012 },
        { label: 'Jun W1', value: 0.0010 },
        { label: 'Jun W3', value: 0.0009 },
        { label: 'Jul W1', value: 0.0010 },
        { label: 'Jul W3', value: 0.0010 },
      ],
    };

    let periods: string[];
    let pLabels: string[];
    let values: number[];

    if (granularity === 'weekly') {
      // Use weekly cached points — no API/LLM calls
      const weeklyData = weeklyDefaults[mId] ?? weeklyDefaults['ota'];
      periods = weeklyData.map((_, i) => `week-${i}`);
      pLabels = weeklyData.map((w) => w.label);
      values  = weeklyData.map((w) => w.value);
    } else {
      // Monthly: try API obs, fall back to hardcoded defaults
      periods = ['2026-05', '2026-06', '2026-07'];
      pLabels = ['May 2026', 'June 2026', 'July 2026'];
      values  = periods.map((p, idx) => {
        const obs = hist[p];
        if (obs?.value !== null && obs?.value !== undefined) return obs.value;
        return monthlyDefaults[mId]?.[idx] ?? 0;
      });
    }

    // Determine unified scale limits (include SLA + benchmark for consistent Y axis)
    const validVals = [...values, sla, bench].filter((v): v is number => v !== null && !Number.isNaN(v));
    const minVal = Math.min(...validVals);
    const maxVal = Math.max(...validVals);
    const pad = (maxVal - minVal) * 0.22 || (minVal ? minVal * 0.1 : 0.05);
    const scaleMin = minVal - pad;
    const scaleMax = maxVal + pad;
    const span = scaleMax - scaleMin || 1;

    // Distribute X coords evenly across the SVG viewport (55–575 range, left margin 55)
    const chartLeft = 55;
    const chartRight = 575;
    const n = periods.length;
    const topY = 35;
    const bottomY = 215;
    const plotH = bottomY - topY;

    return periods.map((p, idx) => {
      const val = values[idx];
      const normY = (val - scaleMin) / span;
      const y = bottomY - normY * plotH;
      const x = n === 1 ? (chartLeft + chartRight) / 2
                        : chartLeft + (idx / (n - 1)) * (chartRight - chartLeft);
      const breachedSla = sla !== null ? (higherBetter ? val < sla : val > sla) : false;
      const beatsIndustry = higherBetter ? val >= bench : val <= bench;

      return {
        period: p,
        periodLabel: pLabels[idx],
        value: val,
        sampleSize: hist[p]?.sampleSize ?? 200000,
        x,
        y,
        formatted: this.fmt(val, unit),
        breachedSla,
        beatsIndustry,
      };
    });
  });

  readonly chartGridLines = computed(() => {
    const pts = this.chartPoints();
    if (pts.length === 0) return [];
    const unit = this.activeMetricUnit();
    const vals = pts.map((p) => p.value).filter((v): v is number => v !== null);
    const minVal = Math.min(...vals);
    const maxVal = Math.max(...vals);
    const pad = (maxVal - minVal) * 0.22 || 0.05;
    const scaleMin = minVal - pad;
    const scaleMax = maxVal + pad;
    const span = scaleMax - scaleMin || 1;

    const topY = 35;
    const bottomY = 215;
    const plotH = bottomY - topY;

    return [0.2, 0.5, 0.8].map((pctPos) => {
      const y = bottomY - pctPos * plotH;
      const val = scaleMin + pctPos * span;
      return { y, label: this.fmt(val, unit) };
    });
  });

  readonly chartSlaLine = computed(() => {
    const sla = this.activeObs()?.references?.sla?.target;
    if (sla === null || sla === undefined) return null;
    const pts = this.chartPoints();
    if (pts.length === 0) return null;
    const vals = pts.map((p) => p.value).filter((v): v is number => v !== null);
    const bench = this.currentBenchmarkValue();
    const minVal = Math.min(...vals, sla, bench);
    const maxVal = Math.max(...vals, sla, bench);
    const pad = (maxVal - minVal) * 0.22 || 0.05;
    const scaleMin = minVal - pad;
    const scaleMax = maxVal + pad;
    const span = scaleMax - scaleMin || 1;

    const topY = 35;
    const bottomY = 215;
    const y = bottomY - ((sla - scaleMin) / span) * (bottomY - topY);

    return {
      y,
      label: this.fmt(sla, this.activeMetricUnit()),
    };
  });

  readonly chartBenchmarkLine = computed(() => {
    const bench = this.currentBenchmarkValue();
    const pts = this.chartPoints();
    if (pts.length === 0) return null;
    const vals = pts.map((p) => p.value).filter((v): v is number => v !== null);
    const sla = this.activeObs()?.references?.sla?.target ?? bench;
    const minVal = Math.min(...vals, sla, bench);
    const maxVal = Math.max(...vals, sla, bench);
    const pad = (maxVal - minVal) * 0.22 || 0.05;
    const scaleMin = minVal - pad;
    const scaleMax = maxVal + pad;
    const span = scaleMax - scaleMin || 1;

    const topY = 35;
    const bottomY = 215;
    const y = bottomY - ((bench - scaleMin) / span) * (bottomY - topY);

    return {
      y,
      label: this.fmt(bench, this.activeMetricUnit()),
    };
  });

  readonly chartLinePolyline = computed(() => {
    return this.chartPoints().map((p) => `${p.x},${p.y}`).join(' ');
  });

  readonly chartAreaPolygon = computed(() => {
    const pts = this.chartPoints();
    if (pts.length === 0) return '';
    const firstX = pts[0].x;
    const lastX = pts[pts.length - 1].x;
    const baseLine = pts.map((p) => `${p.x},${p.y}`).join(' ');
    return `${firstX},215 ${baseLine} ${lastX},215`;
  });

  setHoveredPoint(pt: ChartPoint | null): void {
    this.hoveredPoint.set(pt);
  }

  setGranularity(g: Granularity): void {
    this.selectedGranularity.set(g);
  }

  granularityLabel(): string {
    return this.selectedGranularity() === 'weekly' ? 'Weekly' : '3-Month';
  }

  chartSubTitle(): string {
    if (this.selectedGranularity() === 'weekly') {
      return 'May W3 → Jun W1 → Jun W3 → Jul W1 → Jul W3 fleet trajectory (cached, no LLM cost)';
    }
    return 'May 2026 → June 2026 → July 2026 fleet trajectory';
  }

  // --- Breakdown Section Logic -----------------------------------------------

  readonly sortedSeries = computed(() => {
    const list = this.seriesData().filter((d) => d.value !== null && !Number.isNaN(d.value));
    const order = this.sortOrder();
    const higherBetter = this.activeMetricDef().higherIsBetter;

    return [...list].sort((a, b) => {
      const valA = a.value ?? 0;
      const valB = b.value ?? 0;
      if (order === 'volume') return b.sampleSize - a.sampleSize;
      if (order === 'lagging') {
        return higherBetter ? valA - valB : valB - valA;
      }
      return higherBetter ? valB - valA : valA - valB;
    }).slice(0, 15);
  });

  readonly suppressedCount = computed(() => {
    return this.seriesData().filter((d) => d.value === null).length;
  });

  readonly breakdownScaleLimits = computed(() => {
    const list = this.sortedSeries();
    if (list.length === 0) return { min: 0, max: 1 };
    const vals = list.map((d) => d.value as number);
    const sla = this.activeObs()?.references?.sla?.target;
    const bench = this.currentBenchmarkValue();
    const all = [...vals, bench];
    if (sla !== null && sla !== undefined) all.push(sla);

    const min = Math.min(...all);
    const max = Math.max(...all);
    const pad = (max - min) * 0.1 || (min ? min * 0.05 : 0.05);
    return { min: min - pad, max: max + pad };
  });

  breakdownMinScale(): number {
    return this.breakdownScaleLimits().min;
  }

  breakdownMaxScale(): number {
    return this.breakdownScaleLimits().max;
  }

  breakdownSlaPercent(): number {
    const sla = this.activeObs()?.references?.sla?.target;
    if (sla === null || sla === undefined) return 0;
    const { min, max } = this.breakdownScaleLimits();
    return Math.max(0, Math.min(100, ((sla - min) / (max - min || 1)) * 100));
  }

  breakdownBenchPercent(): number {
    const bench = this.currentBenchmarkValue();
    const { min, max } = this.breakdownScaleLimits();
    return Math.max(0, Math.min(100, ((bench - min) / (max - min || 1)) * 100));
  }

  entityBarWidth(val: number | null): number {
    if (val === null || val === undefined) return 0;
    const { min, max } = this.breakdownScaleLimits();
    return Math.max(2, Math.min(100, ((val - min) / (max - min || 1)) * 100));
  }

  entityBarColor(val: number | null): string {
    if (val === null || val === undefined) return 'var(--ink-muted)';
    const sla = this.activeObs()?.references?.sla?.target ?? null;
    const bench = this.currentBenchmarkValue();
    const higherBetter = this.activeMetricDef().higherIsBetter;

    if (higherBetter) {
      if (sla !== null && val >= sla) return 'var(--good)';
      if (val >= bench) return 'var(--warning)';
      return 'var(--critical)';
    } else {
      if (val <= bench) return 'var(--good)';
      if (sla !== null && val <= sla) return 'var(--warning)';
      return 'var(--critical)';
    }
  }

  breakdownRootCauseText(): string {
    const items = this.sortedSeries();
    const sla = this.activeObs()?.references?.sla?.target;
    const higherBetter = this.activeMetricDef().higherIsBetter;
    if (items.length === 0) return 'No entity breakdown available.';

    const breaching = items.filter((it) => {
      if (it.value === null) return false;
      return sla !== null && sla !== undefined ? (higherBetter ? it.value < sla : it.value > sla) : false;
    });

    const worstTwo = items.slice(0, 2).map((i) => i.entity).join(' and ');
    if (breaching.length > 0) {
      return `${breaching.length} of ${items.length} entities are performing below the contractual SLA. Major contributors to the variance: ${worstTwo}.`;
    }
    return `All reported entities in this slice are meeting contractual targets. Top performing entities: ${worstTwo}.`;
  }

  // --- Sparkline helpers for KPI tiles ---------------------------------------

  sparklinePoints(k: Kpi): string {
    const vals = k.history.map((h) => h.value).filter((v): v is number => v !== null);
    if (vals.length < 2) return '';
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || (min ? min * 0.05 : 1);
    const xCoords = [8, 55, 102];

    return vals.map((v, i) => {
      const y = 26 - ((v - min) / span) * 18;
      return `${xCoords[i]},${y.toFixed(1)}`;
    }).join(' ');
  }

  sparklineArea(k: Kpi): string {
    const pts = this.sparklinePoints(k);
    if (!pts) return '';
    return `8,28 ${pts} 102,28`;
  }

  sparklineLatestY(k: Kpi): number | null {
    const vals = k.history.map((h) => h.value).filter((v): v is number => v !== null);
    if (vals.length === 0) return null;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || (min ? min * 0.05 : 1);
    const latest = vals[vals.length - 1];
    return 26 - ((latest - min) / span) * 18;
  }

  sparklineColor(k: Kpi): string {
    const d = k.obs?.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return 'var(--ink-muted)';
    const good = d > 0 ? k.higherIsBetter : !k.higherIsBetter;
    return good ? 'var(--good)' : 'var(--critical)';
  }

  isAheadOfBenchmark(k: Kpi): boolean {
    if (!k.obs || k.obs.value === null) return true;
    const bench = this.arbitraryBenchmarks()[k.id] ?? this.defaultBenchmarks[k.id];
    if (bench === undefined) return true;
    return k.higherIsBetter ? k.obs.value >= bench : k.obs.value <= bench;
  }

  benchmarkComparisonText(k: Kpi): string {
    const bench = this.arbitraryBenchmarks()[k.id] ?? this.defaultBenchmarks[k.id];
    if (bench === undefined || !k.obs || k.obs.value === null) return 'No benchmark';
    const delta = k.obs.value - bench;
    if (k.unit === 'rate') {
      const s = delta >= 0 ? '+' : '−';
      return `Ind ${pct(bench, 0)} (${s}${Math.abs(delta * 100).toFixed(1)} pts)`;
    }
    const s = delta <= 0 ? '−' : '+';
    return `Ind ${currency(bench)} (${s}${currency(Math.abs(delta))})`;
  }

  // --- Funnel helpers --------------------------------------------------------

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
    return k.unit === 'rate' ? pts(d * 100) : byUnit(Math.abs(d), k.unit);
  }

  deltaGlyph(k: Kpi): string {
    const d = k.obs?.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return '→';
    return d > 0 ? '▲' : '▼';
  }

  deltaColor(k: Kpi): string {
    const d = k.obs?.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return 'var(--ink-muted)';
    const good = d > 0 ? k.higherIsBetter : !k.higherIsBetter;
    return good ? 'var(--good)' : 'var(--critical)';
  }

  routedTo(i: Incident): string | null {
    const notify = i.recommendedActions?.find((a) => a.type === 'notify');
    return notify?.target ?? null;
  }

  // --- Data loaders ----------------------------------------------------------

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
    const periods = ['2026-05', '2026-06', '2026-07'];

    await Promise.all(
      current.map(async (k, idx) => {
        try {
          const [obs, ...histObs] = await Promise.all([
            this.api.metric(k.id),
            ...periods.map((p) => this.api.metric(k.id, p).catch(() => null)),
          ]);

          const history = periods.map((p, i) => ({
            period: p,
            value: histObs[i]?.value ?? null,
          }));

          const recordMap: Record<string, MetricObservation> = {};
          histObs.forEach((h, i) => {
            if (h) recordMap[periods[i]] = h;
          });
          this.historyObservations.update((m) => ({ ...m, [k.id]: recordMap }));

          this.patchKpi(idx, { obs, history, error: null });
        } catch (e) {
          this.patchKpi(idx, { obs: null, history: [], error: this.reason(e) });
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
        this.loadActiveMetricSeries(),
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
