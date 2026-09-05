import {
  Component,
  Input,
  OnChanges,
  OnInit,
  SimpleChanges,
  inject,
  signal,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import type {
  Action,
  AttributionView,
  Contribution,
  Incident,
  MetricObservation,
} from '../core/models';
import {
  num,
  pct,
  periodLabel,
  pts,
  severityColor,
  shortTime,
  signed,
} from '../core/format';

interface WaterfallRow {
  c: Contribution;
  /** 0..100, share of the widest absolute contribution in the set */
  width: number;
  negative: boolean;
}

/**
 * The incident detail — the screen the whole platform exists to produce.
 *
 * Four things have to survive scrutiny here:
 *
 *  1. The four reference frames are shown together. A number with no trend, no
 *     SLA, no peer cohort and no industry benchmark is not a finding, it is a
 *     reading, and the difference is the entire product.
 *  2. The attribution waterfall decomposes the movement across the dimension
 *     that best explains it — chosen by scanning every dimension, not assumed.
 *     On this dataset vendor mix shifts by at most 0.79 points, so a narrative
 *     blaming vendors would be fabricated; the ranked list below the chart
 *     keeps the losing dimensions visible so that claim is checkable.
 *  3. The reconciliation line states whether the parts actually sum to the
 *     total. A decomposition that does not close means entities were held back
 *     by the volume gate, and hiding that would be the dishonest option.
 *  4. Actions the policy layer refuses are rendered disabled with the refusal
 *     reason attached, rather than omitted. An action you cannot see was
 *     blocked looks identical to one that was never considered.
 */
@Component({
  selector: 'mi-incident',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    @if (!incidentId) {
      <section class="panel empty">
        <h2>No incident selected</h2>
        <p class="hint">
          Pick one from the Dashboard, or choose from the open list below.
        </p>
        @if (allIncidents().length) {
          <ul class="picker">
            @for (i of allIncidents(); track i.id) {
              <li>
                <button (click)="select(i.id)">
                  <span class="stripe" [style.background]="severityColor(i.severity)"></span>
                  <span class="sev" [style.color]="severityColor(i.severity)">{{ i.severity }}</span>
                  <span class="ptitle">{{ i.title }}</span>
                  <span class="idtag mono">{{ i.id }}</span>
                </button>
              </li>
            }
          </ul>
        }
      </section>
    } @else if (error()) {
      <section class="panel"><p class="error">{{ error() }}</p></section>
    } @else if (!incident()) {
      <section class="panel"><p class="hint">Loading incident…</p></section>
    } @else {
      <!-- Angular only permits an "as" binding on a primary @if, never on an
           @else if — so the alias is opened in a nested primary block here. -->
      @if (incident(); as inc) {

      <!-- ============ header ============ -->
      <section class="panel head">
        <span class="stripe tall" [style.background]="severityColor(inc.severity)"></span>
        <div class="head-body">
          <div class="row1">
            <span class="sev" [style.color]="severityColor(inc.severity)">{{ inc.severity }}</span>
            <span class="tag num">Priority {{ inc.priority }}</span>
            <span class="tag mono">{{ inc.id }}</span>
            <span class="tag">{{ inc.status }}</span>
          </div>
          <h1>{{ inc.title }}</h1>
          <p class="why"><b>Why now:</b> {{ inc.whyNow }}</p>
          <p class="detected">
            Detected {{ shortTime(inc.detectedAt) }}
            @if (inc.followUpAt) { &middot; follow-up {{ shortTime(inc.followUpAt) }} }
          </p>
        </div>
      </section>

      <!-- ============ explanation ============ -->
      <section class="panel">
        <h2>Explanation</h2>
        <p class="explanation">{{ inc.explanation }}</p>

        @if (inc.evidence?.length) {
          <h3>Evidence</h3>
          <ul class="evidence">
            @for (e of inc.evidence; track e.claim) {
              <li>
                <span class="claim">{{ e.claim }}</span>
                @if (e.metricId) {
                  <span class="cite mono">{{ e.metricId }}@if (e.entity) {&middot;{{ e.entity }}}</span>
                }
              </li>
            }
          </ul>
        }
      </section>

      <!-- ============ four reference frames ============ -->
      <section class="panel">
        <h2>Reference frames &middot; fleet-wide</h2>
        <p class="hint">
          One value read four ways. A movement that is large against its own history but
          normal against the peer cohort is a different problem from one that is out of
          line on every frame.
        </p>
        <p class="hint">
          <strong>Scope:</strong> these frames read the fleet-wide series for this metric, not the
          slice named in the headline above. That is deliberate — the question they answer is
          "is the fleet as a whole out of line?", which is what tells you whether one slice is a
          local problem or the visible edge of a general one. It does mean the movement here will
          not equal the headline movement, and the two are not meant to reconcile.
        </p>

        @if (observation(); as o) {
          <div class="frames">
            <!-- 1 - trend -->
            <div class="frame">
              <div class="frame-h">Trend</div>
              <div class="frame-v num" [style.color]="trendColor(o)">
                {{ fmtDelta(o.references?.trend?.delta) }}
              </div>
              <!-- The z decides the wording; it is not the wording. Printing "robust z −5.8" here
                   put a statistic directly under prose that had just described the same movement in
                   plain English, and the frame is the one with a number in it, so the frame is what
                   gets read. -->
              <div class="frame-s num">
                prior {{ fmtValue(o.references?.trend?.prior ?? null) }}
                @if (unusualness(o); as u) { &middot; {{ u }} }
              </div>
            </div>

            <!-- 2 - SLA -->
            <div class="frame">
              <div class="frame-h">SLA</div>
              @if (o.references?.sla?.target !== null && o.references?.sla?.target !== undefined) {
                <div class="frame-v num"
                     [style.color]="o.references!.sla!.breached ? 'var(--critical)' : 'var(--good)'">
                  {{ o.references!.sla!.breached ? 'Breached' : 'Met' }}
                </div>
                <div class="frame-s num">
                  target {{ fmtValue(o.references!.sla!.target) }}
                  @if (o.references?.sla?.delta !== null && o.references?.sla?.delta !== undefined) {
                    &middot; {{ fmtDelta(o.references!.sla!.delta) }} away
                  }
                </div>
              } @else {
                <div class="frame-v na">Not applicable</div>
                <div class="frame-s">No target is written against this metric.</div>
              }
            </div>

            <!-- 3 - peer -->
            <div class="frame">
              <div class="frame-h">Peer cohort</div>
              @if (o.references?.peer?.cohortMedian !== null && o.references?.peer?.cohortMedian !== undefined) {
                <div class="frame-v num">{{ o.references!.peer!.rank ?? '—' }}</div>
                <div class="frame-s num">
                  median {{ fmtValue(o.references!.peer!.cohortMedian) }}
                  @if (o.references?.peer?.percentile !== null && o.references?.peer?.percentile !== undefined) {
                    &middot; p{{ num(o.references!.peer!.percentile, 0) }}
                  }
                </div>
              } @else {
                <div class="frame-v na">No cohort</div>
                <div class="frame-s">Too few comparable entities cleared the volume gate.</div>
              }
            </div>

            <!-- 4 - industry -->
            <div class="frame">
              <div class="frame-h">Industry</div>
              @if (o.references?.industry?.benchmark !== null && o.references?.industry?.benchmark !== undefined) {
                <div class="frame-v num">{{ fmtValue(o.references!.industry!.benchmark) }}</div>
                <div class="frame-s">{{ o.references!.industry!.source ?? 'benchmark' }}</div>
              } @else {
                <div class="frame-v na">No benchmark</div>
                <div class="frame-s">No external reference is published for this metric.</div>
              }
            </div>
          </div>

          <div class="obs-foot num">
            {{ o.metricId }} &middot; {{ o.grain }}={{ o.entity }} &middot;
            {{ periodLabel(o.period) }} &middot; value <b>{{ fmtValue(o.value) }}</b> &middot;
            n={{ num(o.sampleSize) }}
          </div>
        } @else {
          <p class="hint">No observation could be loaded for this incident's metric.</p>
        }
      </section>

      <!-- ============ attribution waterfall ============ -->
      <section class="panel">
        <h2>Attribution</h2>

        @if (attribution(); as a) {
          <p class="hint">
            {{ a.note }}
          </p>

          @if (a.winner; as w) {
            <div class="wf-head">
              <div>
                <span class="wf-dim">{{ w.dimension }}</span>
                <span class="wf-sub num">
                  explanatory power {{ num(w.explanatoryPower, 2) }} &middot;
                  concentration {{ num(w.concentration, 2) }} &middot;
                  {{ w.entityCount }} entities &middot; n={{ num(w.sampleSize) }}
                </span>
              </div>
              <div class="wf-total num">
                aggregate delta <b [style.color]="a.actualDelta < 0 ? 'var(--neg)' : 'var(--pos)'">
                  {{ fmtDelta(a.actualDelta) }}
                </b>
              </div>
            </div>

            <!-- Waterfall. Sign is carried by which side of the centre line the
                 bar grows toward AND by the signed label on every row. Colour is
                 a third, redundant channel — red/green is invisible to a deutan
                 reader (measured CVD dE 4.1), so it is never the only cue. -->
            <div class="waterfall" role="img"
                 [attr.aria-label]="'Contribution to ' + a.metricId + ' by ' + w.dimension">
              @for (r of waterfall(); track r.c.entity) {
                <div class="wf-row">
                  <div class="wf-label" [title]="r.c.entity">{{ r.c.entity }}</div>

                  <div class="wf-track">
                    <div class="wf-axis"></div>
                    <div
                      class="wf-bar"
                      [class.neg]="r.negative"
                      [style.width.%]="r.width / 2"
                      [style.left.%]="r.negative ? 50 - r.width / 2 : 50"></div>
                  </div>

                  <div class="wf-value num" [class.neg]="r.negative">
                    <span aria-hidden="true">{{ r.negative ? '▼' : '▲' }}</span>
                    {{ fmtDelta(r.c.total) }}
                  </div>

                  <div class="wf-split num" [title]="splitTitle(r.c)">
                    rate {{ fmtDelta(r.c.rateEffect) }} &middot; mix {{ fmtDelta(r.c.mixEffect) }}
                  </div>
                </div>
              }
            </div>

            <!-- Reconciliation: do the parts sum to the total? -->
            @if (a.reconciliation; as rec) {
              <div class="recon" [class.bad]="!rec.reconciles">
                <span class="recon-icon" aria-hidden="true">{{ rec.reconciles ? '✓' : '!' }}</span>
                <!-- The raw tolerance is deliberately not shown. It is a RELATIVE bound — 0.005 means
                     half a percent of the movement, not half a rupee — so printing the constant beside
                     an absolute error produced "error 0.007241745 (tolerance 0.005000000) —
                     reconciles", which reads as the verdict contradicting the arithmetic beside it.
                     What a reader needs is how big the gap is against the movement it belongs to. -->
                <span class="num">
                  <b>Parts sum to total:</b>
                  {{ fmtDelta(rec.explainedSum) }} explained vs {{ fmtDelta(rec.actualDelta) }} actual
                  &mdash; <b>{{ rec.reconciles ? 'reconciles' : 'does not reconcile' }}</b>
                  <span class="recon-gap">{{ reconGap(rec) }}</span>
                </span>
                @if (rec.note) { <span class="recon-note">{{ rec.note }}</span> }
              </div>
            }
          } @else {
            <p class="hint idle">
              No dimension could be decomposed for this movement — every candidate
              entity fell below the volume gate.
            </p>
          }

          <!-- The dimensions that lost. Keeping them on the record is what makes
               "this is not a vendor problem" a finding rather than an assumption. -->
          @if (a.ranked?.length) {
            <h3>Dimensions scanned, ranked</h3>
            <div class="scroll-x">
              <table class="ranked">
                <thead>
                  <tr>
                    <th>Dimension</th>
                    <th class="r">Explanatory power</th>
                    <th class="r">Concentration</th>
                    <th class="r">Dispersion</th>
                    <th class="r">Explained delta</th>
                    <th class="r">Entities</th>
                  </tr>
                </thead>
                <tbody>
                  @for (d of a.ranked; track d.dimension) {
                    <tr [class.win]="a.winner && d.dimension === a.winner.dimension">
                      <td>{{ d.dimension }}</td>
                      <td class="r num">{{ num(d.explanatoryPower, 3) }}</td>
                      <td class="r num">{{ num(d.concentration, 3) }}</td>
                      <td class="r num">{{ num(d.dispersion, 3) }}</td>
                      <td class="r num">{{ fmtDelta(d.explainedDelta) }}</td>
                      <td class="r num">{{ d.entityCount }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        } @else if (attributionError()) {
          <p class="hint idle">{{ attributionError() }}</p>
        } @else {
          <p class="hint idle">Decomposing…</p>
        }
      </section>

      <!-- ============ data quality ============ -->
      @if (inc.quality; as q) {
        <section class="panel quality">
          <h2>Data quality</h2>
          <div class="q-head num">
            Coverage <b>{{ pct(q.coverage, 1) }}</b> &middot;
            confidence <b>{{ q.confidence }}</b>
          </div>
          @if (q.caveats?.length) {
            <ul class="caveats">
              @for (c of q.caveats; track c) {
                <li>{{ c }}</li>
              }
            </ul>
          } @else {
            <p class="hint">No caveats recorded for this incident.</p>
          }
        </section>
      }

      <!-- ============ policy + actions ============ -->
      <section class="panel">
        <h2>Recommended actions</h2>

        @if (inc.policy; as p) {
          <div class="policy num">
            <span class="tag mono">{{ p.ruleId }}</span>
            <span>
              {{ p.breached ? 'Breached' : 'Not breached' }} &middot;
              {{ p.consecutivePeriods }} consecutive period{{ p.consecutivePeriods === 1 ? '' : 's' }} &middot;
              band {{ p.severityBand }} &middot;
              escalation {{ p.escalationPermitted ? 'permitted' : 'withheld' }}
            </span>
          </div>
        }

        @if (inc.recommendedActions?.length) {
          <div class="actions">
            @for (a of inc.recommendedActions; track a.type + a.target) {
              <button
                class="action"
                [class.blocked]="!a.permitted"
                [disabled]="acting() || (!clickable(a))"
                [title]="a.permitted ? a.reason : 'Blocked: ' + a.reason"
                (click)="onAction(a)">
                <span class="a-type">{{ a.type }}</span>
                <span class="a-target">{{ a.target }}</span>
                @if (!a.permitted) { <span class="a-lock" aria-hidden="true">&#128274;</span> }
              </button>
            }
          </div>

          <div class="ops">
            <label class="recheck">
              Re-check period
              <input type="text" [(ngModel)]="recheckPeriod" size="9" />
            </label>
            <button class="ghost" (click)="runRecheck()" [disabled]="acting()">
              Run follow-up now
            </button>
            <button class="ghost" (click)="dismiss()" [disabled]="acting()">Dismiss</button>
          </div>

          @if (actionMessage()) {
            <p class="action-msg" [class.bad]="actionError()">{{ actionMessage() }}</p>
          }

          <ul class="reasons">
            @for (a of inc.recommendedActions; track a.type + a.target) {
              @if (!a.permitted) {
                <li><b>{{ a.type }} &rarr; {{ a.target }}</b> blocked: {{ a.reason }}</li>
              }
            }
          </ul>
        } @else {
          <p class="hint idle">No actions were proposed for this incident.</p>
        }
      </section>
      }
    }
  `,
  styles: [
    `
      :host {
        display: block;
      }

      .panel {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 14px 15px;
        margin-bottom: 14px;
      }

      h1 {
        margin: 5px 0 0;
        font-size: 19px;
        font-weight: 650;
        letter-spacing: -0.015em;
        line-height: 1.3;
      }

      h2 {
        margin: 0 0 4px;
        font-size: 13px;
        font-weight: 650;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        color: var(--ink-2);
      }

      h3 {
        margin: 16px 0 6px;
        font-size: 11.5px;
        font-weight: 650;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--ink-muted);
      }

      .hint {
        margin: 4px 0 0;
        font-size: 12px;
        color: var(--ink-muted);
        max-width: 78ch;
      }

      .hint.idle {
        padding: 10px 0 2px;
      }

      .error {
        margin: 0;
        color: var(--critical);
        font-size: 13px;
      }

      .mono {
        font-family: var(--mono);
      }

      /* ---- header ---- */
      .head {
        display: flex;
        gap: 13px;
        padding: 0;
        overflow: hidden;
      }

      .stripe {
        width: 4px;
        flex: none;
      }

      .stripe.tall {
        align-self: stretch;
      }

      .head-body {
        padding: 13px 15px 14px 2px;
        min-width: 0;
      }

      .row1 {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }

      .sev {
        font-size: 10.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }

      .tag {
        font-size: 10.5px;
        color: var(--ink-muted);
        padding: 1px 6px;
        border-radius: 4px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
      }

      .why {
        margin: 8px 0 0;
        font-size: 13px;
        color: var(--ink-2);
        max-width: 82ch;
      }

      .detected {
        margin: 6px 0 0;
        font-size: 11px;
        color: var(--ink-muted);
      }

      .explanation {
        margin: 8px 0 0;
        font-size: 13.5px;
        line-height: 1.62;
        color: var(--ink);
        max-width: 82ch;
        white-space: pre-wrap;
      }

      .evidence {
        list-style: none;
        margin: 6px 0 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 5px;
      }

      .evidence li {
        display: flex;
        gap: 9px;
        align-items: baseline;
        flex-wrap: wrap;
        font-size: 12.5px;
        color: var(--ink-2);
        padding: 6px 9px;
        background: var(--surface-2);
        border-left: 2px solid var(--accent-line);
        border-radius: 0 4px 4px 0;
      }

      .cite {
        font-size: 10.5px;
        color: var(--ink-muted);
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        padding: 1px 5px;
        border-radius: 4px;
        white-space: nowrap;
      }

      /* ---- reference frames ---- */
      .frames {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(172px, 1fr));
        gap: 1px;
        margin-top: 11px;
        background: var(--line);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        overflow: hidden;
      }

      .frame {
        background: var(--surface-2);
        padding: 10px 11px;
      }

      .frame-h {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--ink-muted);
        font-weight: 600;
      }

      .frame-v {
        font-size: 19px;
        font-weight: 620;
        margin-top: 3px;
        letter-spacing: -0.015em;
      }

      .frame-v.na {
        font-size: 14px;
        color: var(--ink-muted);
        font-weight: 500;
      }

      .frame-s {
        font-size: 11px;
        color: var(--ink-muted);
        margin-top: 2px;
      }

      .obs-foot {
        margin-top: 9px;
        font-size: 11px;
        color: var(--ink-muted);
      }

      /* ---- waterfall ---- */
      .wf-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 14px;
        flex-wrap: wrap;
        margin: 12px 0 8px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--line);
      }

      .wf-dim {
        font-size: 14px;
        font-weight: 650;
        color: var(--ink);
        margin-right: 9px;
      }

      .wf-sub,
      .wf-total {
        font-size: 11px;
        color: var(--ink-muted);
      }

      .wf-total b {
        font-size: 13px;
      }

      .waterfall {
        display: flex;
        flex-direction: column;
        gap: 5px;
      }

      .wf-row {
        display: grid;
        grid-template-columns: minmax(96px, 150px) 1fr 86px minmax(0, 148px);
        align-items: center;
        gap: 10px;
      }

      .wf-label {
        font-size: 12px;
        color: var(--ink-2);
        font-weight: 550;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .wf-track {
        position: relative;
        height: 17px;
        background: var(--surface-sunken);
        border-radius: 3px;
        overflow: hidden;
      }

      /* The centre line IS the zero baseline — it is what makes the sign legible
         without relying on the bar's colour. */
      .wf-axis {
        position: absolute;
        left: 50%;
        top: 0;
        bottom: 0;
        width: 1px;
        background: var(--line-strong);
      }

      .wf-bar {
        position: absolute;
        top: 3px;
        bottom: 3px;
        background: var(--pos);
        border-radius: 0 3px 3px 0;
        min-width: 2px;
      }

      .wf-bar.neg {
        background: var(--neg);
        border-radius: 3px 0 0 3px;
      }

      .wf-value {
        font-size: 12px;
        font-weight: 650;
        text-align: right;
        color: var(--pos);
        white-space: nowrap;
      }

      .wf-value.neg {
        color: var(--neg);
      }

      .wf-split {
        font-size: 10.5px;
        color: var(--ink-muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /* ---- reconciliation ---- */
      .recon {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 13px;
        padding: 9px 11px;
        border-radius: var(--radius);
        background: color-mix(in srgb, var(--good) 9%, transparent);
        border: 1px solid color-mix(in srgb, var(--good) 32%, transparent);
        font-size: 12px;
        color: var(--ink-2);
      }

      .recon.bad {
        background: color-mix(in srgb, var(--warning) 12%, transparent);
        border-color: color-mix(in srgb, var(--warning) 45%, transparent);
      }

      .recon-icon {
        font-weight: 700;
        color: var(--good);
      }

      .recon.bad .recon-icon {
        color: var(--warning);
      }

      .recon-note {
        flex-basis: 100%;
        color: var(--ink-muted);
        font-size: 11.5px;
      }

      /* ---- ranked table ---- */
      table.ranked {
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
        min-width: 620px;
      }

      table.ranked th {
        text-align: left;
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
        font-weight: 600;
        padding: 5px 9px;
        border-bottom: 1px solid var(--line-strong);
        white-space: nowrap;
      }

      table.ranked td {
        padding: 6px 9px;
        border-bottom: 1px solid var(--line);
        color: var(--ink-2);
        white-space: nowrap;
      }

      table.ranked th.r,
      table.ranked td.r {
        text-align: right;
      }

      table.ranked tr.win td {
        background: var(--accent-bg);
        color: var(--ink);
        font-weight: 600;
      }

      /* ---- quality ---- */
      .quality {
        border-left: 3px solid var(--warning);
      }

      .q-head {
        font-size: 12.5px;
        color: var(--ink-2);
        margin-top: 6px;
      }

      .caveats {
        margin: 8px 0 0;
        padding-left: 17px;
        display: flex;
        flex-direction: column;
        gap: 5px;
      }

      .caveats li {
        font-size: 12px;
        color: var(--ink-2);
        line-height: 1.55;
        max-width: 88ch;
      }

      /* ---- actions ---- */
      .policy {
        display: flex;
        align-items: center;
        gap: 9px;
        flex-wrap: wrap;
        font-size: 12px;
        color: var(--ink-muted);
        margin: 8px 0 12px;
      }

      .actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      button.action {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: var(--accent);
        color: #fff;
        border: 1px solid transparent;
        border-radius: var(--radius);
        padding: 7px 13px;
        font-size: 12.5px;
        font-weight: 600;
      }

      button.action:hover:not(:disabled) {
        filter: brightness(1.08);
      }

      button.action.blocked {
        background: var(--surface-sunken);
        color: var(--ink-muted);
        border-color: var(--line-strong);
        border-style: dashed;
        text-decoration: line-through;
        text-decoration-color: var(--ink-muted);
      }

      .a-target {
        font-family: var(--mono);
        font-size: 11px;
        opacity: 0.9;
      }

      .a-lock {
        font-size: 10px;
        text-decoration: none;
      }

      .reasons {
        margin: 10px 0 0;
        padding-left: 17px;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .reasons li {
        font-size: 11.5px;
        color: var(--ink-muted);
        max-width: 88ch;
      }

      .ops {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        margin-top: 12px;
      }

      .recheck {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
        font-weight: 600;
      }

      .recheck input {
        font: inherit;
        font-size: 12.5px;
        text-transform: none;
        letter-spacing: 0;
        font-weight: 500;
        padding: 5px 8px;
        border-radius: var(--radius);
        border: 1px solid var(--line-strong);
        background: var(--surface-2);
        color: var(--ink);
      }

      button.ghost {
        background: var(--surface-2);
        color: var(--ink-2);
        border: 1px solid var(--line-strong);
        border-radius: var(--radius);
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 550;
      }

      .action-msg {
        margin: 10px 0 0;
        font-size: 12.5px;
        color: var(--ink-2);
      }

      .action-msg.bad {
        color: var(--critical);
      }

      /* ---- picker ---- */
      .empty h2 {
        margin-bottom: 2px;
      }

      .picker {
        list-style: none;
        margin: 12px 0 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      .picker button {
        width: 100%;
        display: flex;
        align-items: center;
        gap: 10px;
        text-align: left;
        background: var(--surface-2);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 0 12px 0 0;
        overflow: hidden;
      }

      .picker button:hover {
        border-color: var(--accent-line);
      }

      .picker .stripe {
        align-self: stretch;
        min-height: 34px;
      }

      .ptitle {
        flex: 1;
        font-size: 12.5px;
        font-weight: 550;
        color: var(--ink);
        padding: 8px 0;
      }

      .idtag {
        font-size: 10.5px;
        color: var(--ink-muted);
      }
    `,
  ],
})
export class IncidentComponent implements OnInit, OnChanges {
  private readonly api = inject(ApiService);

  @Input() incidentId: string | null = null;

  readonly incident = signal<Incident | null>(null);
  readonly observation = signal<MetricObservation | null>(null);
  readonly attribution = signal<AttributionView | null>(null);
  readonly attributionError = signal<string | null>(null);
  readonly error = signal<string | null>(null);
  readonly allIncidents = signal<Incident[]>([]);
  readonly acting = signal(false);
  readonly actionMessage = signal<string | null>(null);
  readonly actionError = signal(false);
  recheckPeriod = '2026-07';

  /** The metric unit drives value formatting across every frame on this page. */
  private readonly unit = signal<string>('rate');

  /**
   * Bars are scaled against the widest absolute contribution, so the largest
   * mover fills the track and everything else is read relative to it. Scaling
   * against the aggregate delta instead would make every bar a sliver whenever
   * the contributions offset each other.
   */
  readonly waterfall = computed<WaterfallRow[]>(() => {
    const w = this.attribution()?.winner;
    if (!w?.contributions?.length) return [];
    const max = Math.max(...w.contributions.map((c) => Math.abs(c.total)));
    if (!Number.isFinite(max) || max === 0) return [];
    return w.contributions.map((c) => ({
      c,
      width: (Math.abs(c.total) / max) * 100,
      negative: c.total < 0,
    }));
  });

  // re-exported for the template
  readonly num = num;
  readonly pct = pct;
  readonly pts = pts;
  readonly signed = signed;
  readonly periodLabel = periodLabel;
  readonly shortTime = shortTime;
  readonly severityColor = severityColor;

  async ngOnInit(): Promise<void> {
    if (!this.incidentId) void this.loadPicker();
    else void this.load();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['incidentId']) {
      if (this.incidentId) void this.load();
      else void this.loadPicker();
    }
  }

  select(id: string): void {
    this.incidentId = id;
    void this.load();
  }

  clickable(a: Action): boolean {
    return a.type === 'notify' || a.type === 'vendor_escalation';
  }

  async onAction(a: Action): Promise<void> {
    if (!this.incidentId) return;
    this.acting.set(true);
    this.actionError.set(false);
    this.actionMessage.set(null);
    try {
      if (a.type === 'notify') {
        const sent = await this.api.notifyIncident(this.incidentId);
        this.actionMessage.set(`Sent to ${sent.recipient} (${sent.status}). Open Outbox to read it.`);
      } else if (a.type === 'vendor_escalation') {
        const result = await this.api.escalateIncident(this.incidentId);
        if (result.status === 403 || !result.body.escalated) {
          this.actionError.set(true);
          this.actionMessage.set(result.body.action?.reason ?? 'Vendor escalation refused by policy.');
        } else {
          this.incident.set(result.body.incident);
          this.actionMessage.set(`Escalated to ${result.body.action.target}.`);
        }
      }
    } catch (e) {
      this.actionError.set(true);
      this.actionMessage.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.acting.set(false);
    }
  }

  async runRecheck(): Promise<void> {
    if (!this.incidentId) return;
    this.acting.set(true);
    this.actionError.set(false);
    this.actionMessage.set(null);
    try {
      const result = await this.api.recheckIncident(this.incidentId, this.recheckPeriod.trim() || undefined);
      this.incident.set(result.incident);
      const follow = result.followUp?.status ?? 'unknown';
      const extra = result.escalations?.length
        ? ` Raised ${result.escalations.map((e) => e.id).join(', ')}.`
        : '';
      this.actionMessage.set(
        `Follow-up ${follow} — incident is now ${result.incident.status}.${extra} Check Outbox.`,
      );
    } catch (e) {
      this.actionError.set(true);
      this.actionMessage.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.acting.set(false);
    }
  }

  async dismiss(): Promise<void> {
    if (!this.incidentId) return;
    this.acting.set(true);
    this.actionError.set(false);
    try {
      const dismissed = await this.api.dismissIncident(this.incidentId, 'dismissed from console');
      this.incident.set(dismissed);
      this.actionMessage.set('Dismissed. The ranker will suppress this pattern on the next run.');
    } catch (e) {
      this.actionError.set(true);
      this.actionMessage.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.acting.set(false);
    }
  }

  fmtValue(v: number | null): string {
    if (v === null || v === undefined) return '—';
    return this.unit() === 'currency'
      ? `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
      : this.unit() === 'rate'
        ? pct(v)
        : num(v, 2);
  }

  /**
   * A signed movement in the metric's own unit.
   *
   * Every delta this component renders — the attribution waterfall, the reconciliation line, the
   * dimension table, the trend and SLA frames — arrives from the API on the metric's NATIVE scale.
   * For a rate that means a fraction: OTA moving 2.23 percentage points is delivered as 0.0223, and
   * a contribution of 1.65 points as 0.0165. So the rate branch scales; the others already carry
   * their own units.
   *
   * The unit switch exists because `pts` is right for a rate and wrong for everything else — cost
   * per trip moving by fifty rupees was once shown as "+50.74 pts". Percentage points are a unit,
   * not a decoration.
   *
   * There used to be a second formatter here, split off on the belief that attribution deltas were
   * already in points while only the reference frames were fractions. That belief was wrong — the
   * API was never checked, it was inferred from the incident TITLE, which is built server-side from
   * Finding.deltaPts and genuinely is in points. Nothing in this component reads deltaPts. The split
   * therefore fixed the two frames and left every figure in the waterfall a hundred times too small,
   * which is worse than the bug it replaced: a wrong number in the panel that exists to prove the
   * arithmetic reconciles. One formatter, one documented scale, verified against a live response.
   */
  fmtDelta(v: number | null | undefined): string {
    if (v === null || v === undefined || !Number.isFinite(v)) return '—';
    const scaled = this.unit() === 'rate' ? v * 100 : v;
    const sign = scaled > 0 ? '+' : scaled < 0 ? '−' : '';
    const magnitude = Math.abs(scaled);
    switch (this.unit()) {
      case 'currency':
        return `${sign}₹${magnitude.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
      case 'minutes':
        return `${sign}${magnitude.toFixed(1)} min`;
      case 'rate':
        return `${sign}${magnitude.toFixed(2)} pts`;
      default:
        return `${sign}${magnitude.toFixed(2)}`;
    }
  }

  /**
   * The residual, expressed against the movement it belongs to.
   *
   * An absolute error means nothing on its own: 0.0072 is floating-point dust against a movement of
   * 16.16 and a serious gap against a movement of 0.03. Stating it as a share of the total is the
   * only form a reader can judge, and it matches how the backend actually decides — the tolerance
   * is relative, which is why the raw constant looked violated when it was not.
   */
  reconGap(rec: { error?: number | null; actualDelta?: number | null }): string {
    const err = Math.abs(rec.error ?? 0);
    const total = Math.abs(rec.actualDelta ?? 0);
    if (!Number.isFinite(err) || err === 0) return '(exact)';
    if (total === 0) return '';
    const share = (err / total) * 100;
    return share < 0.01 ? '(rounding only)' : `(gap ${share.toFixed(2)}% of the movement)`;
  }

  /**
   * How unusual this movement is, in words — the same three bands the backend narrators use.
   *
   * Returns '' when there is no score, which the template treats as "print nothing" rather than
   * printing an empty separator.
   */
  unusualness(o: MetricObservation): string {
    const z = o.references?.trend?.robustZ;
    if (z === null || z === undefined || !Number.isFinite(z)) return '';
    const a = Math.abs(z);
    if (a >= 3) return 'far outside its usual range';
    if (a >= 2) return 'larger than its usual monthly move';
    return 'within its usual range';
  }

  trendColor(o: MetricObservation): string {
    const d = o.references?.trend?.delta;
    if (d === null || d === undefined || d === 0) return 'var(--ink-muted)';
    return d < 0 ? 'var(--neg)' : 'var(--pos)';
  }

  splitTitle(c: Contribution): string {
    return (
      `rate effect ${signed(c.rateEffect)} · mix effect ${signed(c.mixEffect)} · ` +
      `share ${pct(c.shareBefore, 2)} → ${pct(c.shareAfter, 2)}`
    );
  }

  private async loadPicker(): Promise<void> {
    try {
      this.allIncidents.set(await this.api.incidents());
    } catch {
      /* the empty state already reads correctly with no list */
    }
  }

  private async load(): Promise<void> {
    const id = this.incidentId;
    if (!id) return;

    this.error.set(null);
    this.incident.set(null);
    this.observation.set(null);
    this.attribution.set(null);
    this.attributionError.set(null);

    let inc: Incident;
    try {
      inc = await this.api.incident(id);
      this.incident.set(inc);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      return;
    }

    // The metric this incident is about comes off its first cited evidence.
    const metricId = inc.evidence?.find((e) => !!e.metricId)?.metricId ?? 'ota';

    void this.resolveUnit(metricId);

    void (async () => {
      try {
        this.observation.set(await this.api.metric(metricId));
      } catch {
        this.observation.set(null);
      }
    })();

    void (async () => {
      try {
        this.attribution.set(await this.api.attribution(metricId));
      } catch (e) {
        this.attributionError.set(
          e instanceof Error ? e.message : 'attribution unavailable',
        );
      }
    })();
  }

  private async resolveUnit(metricId: string): Promise<void> {
    try {
      const catalog = await this.api.metricCatalog();
      const def = catalog.find((m) => m.id === metricId);
      if (def) this.unit.set(def.unit);
    } catch {
      /* default 'rate' is correct for OTA, the headline metric */
    }
  }
}
