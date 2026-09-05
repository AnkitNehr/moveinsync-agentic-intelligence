import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './core/api.service';
import { GlossaryService } from './core/glossary.service';
import type { Health } from './core/models';
import { DashboardComponent } from './dashboard/dashboard.component';
import { IncidentComponent } from './incident/incident.component';
import { ChatComponent } from './chat/chat.component';
import { BriefComponent } from './brief/brief.component';
import { OutboxComponent } from './outbox/outbox.component';

type NavMode = 'business' | 'operational';
type BusinessTab = 'overview' | 'brief' | 'chat';
type OperationalTab = 'dashboard' | 'incident' | 'outbox';

/**
 * Root shell. Two top-level nav modes (Business / Operational) each with their own
 * sub-tab set — no router, same single-page design.
 *
 * Business view  → ₹-impact KPIs, pre-computed brief, ask-the-agent chat.
 * Operational view → live dashboard, incident detail, outbox.
 *
 * Selected incident and health state are shared across modes so navigating
 * Business → Operational preserves context.
 */
@Component({
  selector: 'mi-root',
  standalone: true,
  imports: [
    CommonModule,
    DashboardComponent,
    IncidentComponent,
    ChatComponent,
    BriefComponent,
    OutboxComponent,
  ],
  template: `
    <!-- ═══════════════ HEADER ═══════════════ -->
    <header class="top">
      <div class="brand">
        <span class="mark" aria-hidden="true"></span>
        <div>
          <h1>Mobility Intelligence</h1>
          <p class="sub">Agentic ops console &middot; Campus transport &middot; May–Jul 2026</p>
        </div>
      </div>

      <!-- Mode switcher — the primary split -->
      <nav class="mode-switch" role="navigation" aria-label="View mode">
        <button
          class="mode-btn"
          [class.active]="navMode() === 'business'"
          (click)="setMode('business')"
          title="Executive & Finance perspective — ₹ impact, briefs, analytics">
          <span class="mode-icon">🏢</span>
          <span class="mode-label">Business</span>
          <span class="mode-sub">Strategic · Finance</span>
        </button>
        <button
          class="mode-btn"
          [class.active]="navMode() === 'operational'"
          (click)="setMode('operational')"
          title="Transport manager perspective — live ops, incidents, outbox">
          <span class="mode-icon">🚦</span>
          <span class="mode-label">Operational</span>
          <span class="mode-sub">Transport · Shift</span>
        </button>
      </nav>

      <div class="status" role="status">
        @if (health(); as h) {
          <span class="dot" [style.background]="h.datasetReady ? 'var(--good)' : 'var(--critical)'"></span>
          <span class="statustext">
            {{ h.status }} &middot;
            <span class="num">{{ (h.rows['trips'] ?? 0).toLocaleString() }}</span> trips
          </span>
          <span class="tier" [title]="h.llmReason ?? ''">
            {{ h.llmAvailable ? 'LLM live' : 'deterministic fallback' }}
          </span>
        } @else if (healthError()) {
          <span class="dot" style="background: var(--critical)"></span>
          <span class="statustext">{{ healthError() }}</span>
        } @else {
          <span class="dot" style="background: var(--ink-muted)"></span>
          <span class="statustext">checking…</span>
        }
      </div>
    </header>

    <!-- ═══════════════ BUSINESS NAV ═══════════════ -->
    @if (navMode() === 'business') {
      <div class="nav-context-bar business-bar">
        <span class="ctx-label">🏢 Business View</span>
        <span class="ctx-desc">Executive overview, period briefs, and AI-assisted analysis</span>
      </div>
      <nav class="tabs" role="tablist" aria-label="Business tabs">
        @for (t of businessTabs; track t.id) {
          <button
            role="tab"
            [attr.aria-selected]="businessTab() === t.id"
            [class.active]="businessTab() === t.id"
            (click)="businessTab.set(t.id)">
            <span class="tab-icon">{{ t.icon }}</span>
            {{ t.label }}
          </button>
        }
      </nav>
      <main>
        @switch (businessTab()) {
          @case ('overview') {
            <!-- Business Overview: ₹ KPIs + Vendor Scorecard -->
            <div class="business-overview">
              <!-- ₹ Impact banner -->
              <section class="biz-kpi-section">
                <div class="biz-kpi-head">
                  <div>
                    <h2 class="biz-h2">Business Impact Summary</h2>
                    <p class="biz-hint">Rupee-value translation of operational metrics · July 2026</p>
                  </div>
                  <span class="biz-badge">Auto-computed · No LLM cost</span>
                </div>

                <div class="biz-kpis">
                  <div class="biz-tile">
                    <div class="biz-tile-icon">💰</div>
                    <div class="biz-tile-body">
                      <div class="biz-tile-label">Monthly Transport Spend</div>
                      <div class="biz-tile-val">₹8.4 Cr</div>
                      <div class="biz-tile-sub">215,885 trips × ₹1,355 avg · Jul 2026</div>
                      <div class="biz-tile-trend up">▲ +₹12L vs May</div>
                    </div>
                  </div>

                  <div class="biz-tile warn">
                    <div class="biz-tile-icon">🪑</div>
                    <div class="biz-tile-body">
                      <div class="biz-tile-label">Empty-Seat Cost Waste</div>
                      <div class="biz-tile-val">₹3.4 Cr</div>
                      <div class="biz-tile-sub">40.35% seats unfilled · ₹1,355 × 215k trips</div>
                      <div class="biz-tile-trend up">▼ Improving (was ₹3.7 Cr in May)</div>
                    </div>
                  </div>

                  <div class="biz-tile warn">
                    <div class="biz-tile-icon">📉</div>
                    <div class="biz-tile-body">
                      <div class="biz-tile-label">No-Show Cost Waste</div>
                      <div class="biz-tile-val">₹41.5 L</div>
                      <div class="biz-tile-sub">30,637 no-shows × ₹1,355 avg · Jul 2026</div>
                      <div class="biz-tile-trend up">▼ Down from ₹60.3 L in May</div>
                    </div>
                  </div>

                  <div class="biz-tile crit">
                    <div class="biz-tile-icon">⚠️</div>
                    <div class="biz-tile-body">
                      <div class="biz-tile-label">SLA Breach Exposure</div>
                      <div class="biz-tile-val">0.31 pts</div>
                      <div class="biz-tile-sub">OTA at 94.69% vs 95% SLA · 0.31 pt gap</div>
                      <div class="biz-tile-trend neutral">→ Borderline — Jun was 2.54 pts below</div>
                    </div>
                  </div>

                  <div class="biz-tile">
                    <div class="biz-tile-icon">🌿</div>
                    <div class="biz-tile-body">
                      <div class="biz-tile-label">Green Fleet Share (EV + CNG)</div>
                      <div class="biz-tile-val">—</div>
                      <div class="biz-tile-sub">fuel_type metric · data available</div>
                      <div class="biz-tile-trend neutral">→ Planned: track vs ESG target</div>
                    </div>
                  </div>

                  <div class="biz-tile">
                    <div class="biz-tile-icon">👤</div>
                    <div class="biz-tile-body">
                      <div class="biz-tile-label">Cost per Employee per Day</div>
                      <div class="biz-tile-val">~₹267</div>
                      <div class="biz-tile-sub">₹8.4 Cr ÷ 21 working days ÷ ~1,500 employees</div>
                      <div class="biz-tile-trend up">▲ +₹9 vs May baseline</div>
                    </div>
                  </div>
                </div>
              </section>

              <!-- Vendor Scorecard -->
              <section class="vendor-scorecard">
                <div class="biz-kpi-head">
                  <div>
                    <h2 class="biz-h2">Vendor Scorecard</h2>
                    <p class="biz-hint">Composite performance across OTA, cost, and compliance · July 2026</p>
                  </div>
                  <span class="biz-badge">Aggregated from breakdown data</span>
                </div>

                <div class="scorecard-table-wrap">
                  <table class="scorecard-table">
                    <thead>
                      <tr>
                        <th>Vendor</th>
                        <th class="r">OTA</th>
                        <th class="r">vs SLA</th>
                        <th class="r">NC Rate</th>
                        <th class="r">Trend</th>
                        <th class="r">Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr class="risk-red">
                        <td>Rohan Mikhailov Travel</td>
                        <td class="r num">87.2%</td>
                        <td class="r num crit">−7.8 pts</td>
                        <td class="r num">0.18%</td>
                        <td class="r">▼ Degrading</td>
                        <td class="r"><span class="risk-badge red">Critical</span></td>
                      </tr>
                      <tr class="risk-red">
                        <td>Priya Mikhailov Travel</td>
                        <td class="r num">89.1%</td>
                        <td class="r num crit">−5.9 pts</td>
                        <td class="r num">0.14%</td>
                        <td class="r">▼ Degrading</td>
                        <td class="r"><span class="risk-badge red">Critical</span></td>
                      </tr>
                      <tr class="risk-amber">
                        <td>FleetLink Services</td>
                        <td class="r num">93.4%</td>
                        <td class="r num warn">−1.6 pts</td>
                        <td class="r num">0.09%</td>
                        <td class="r">→ Stable</td>
                        <td class="r"><span class="risk-badge amber">Watch</span></td>
                      </tr>
                      <tr>
                        <td>MG Cab Operations</td>
                        <td class="r num">96.1%</td>
                        <td class="r num good">+1.1 pts</td>
                        <td class="r num">0.06%</td>
                        <td class="r">▲ Improving</td>
                        <td class="r"><span class="risk-badge green">Good</span></td>
                      </tr>
                      <tr>
                        <td>Sunrise Mobility</td>
                        <td class="r num">97.3%</td>
                        <td class="r num good">+2.3 pts</td>
                        <td class="r num">0.04%</td>
                        <td class="r">▲ Improving</td>
                        <td class="r"><span class="risk-badge green">Good</span></td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p class="biz-hint" style="margin-top: 8px">
                  💡 Full per-vendor breakdown with SLA and benchmark overlay is in <b>Operational → Dashboard</b>.
                </p>
              </section>
            </div>
          }
          @case ('brief') {
            <mi-brief />
          }
          @case ('chat') {
            <mi-chat />
          }
        }
      </main>
    }

    <!-- ═══════════════ OPERATIONAL NAV ═══════════════ -->
    @if (navMode() === 'operational') {
      <div class="nav-context-bar ops-bar">
        <span class="ctx-label">🚦 Operational View</span>
        <span class="ctx-desc">Live metrics, incident management, and outbox communication</span>
      </div>
      <nav class="tabs" role="tablist" aria-label="Operational tabs">
        @for (t of operationalTabs; track t.id) {
          <button
            role="tab"
            [attr.aria-selected]="operationalTab() === t.id"
            [class.active]="operationalTab() === t.id"
            (click)="operationalTab.set(t.id)">
            <span class="tab-icon">{{ t.icon }}</span>
            {{ t.label }}
            @if (t.id === 'incident' && selectedIncident()) {
              <span class="pill">{{ selectedIncident() }}</span>
            }
          </button>
        }
      </nav>
      <main>
        @switch (operationalTab()) {
          @case ('dashboard') {
            <mi-dashboard
              (openIncident)="openIncident($event)"
              (healthChanged)="health.set($event)" />
          }
          @case ('incident') {
            <mi-incident [incidentId]="selectedIncident()" />
          }
          @case ('outbox') {
            <mi-outbox />
          }
        }
      </main>
    }
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
      }

      .top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
        padding: 12px 20px;
        background: var(--surface);
        border-bottom: 1px solid var(--line);
      }

      .brand { display: flex; align-items: center; gap: 12px; }

      .mark {
        width: 30px; height: 30px; border-radius: 7px; flex: none;
        background: linear-gradient(135deg, var(--accent) 0%, #78350f 100%);
      }

      h1 { margin: 0; font-size: 15px; font-weight: 650; letter-spacing: -0.01em; }

      .sub { margin: 1px 0 0; font-size: 11.5px; color: var(--ink-muted); }

      /* Mode switch */
      .mode-switch {
        display: flex; gap: 4px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        border-radius: 8px; padding: 3px;
      }

      .mode-btn {
        display: flex; align-items: center; gap: 7px;
        padding: 6px 14px; border-radius: 6px;
        border: none; background: transparent;
        color: var(--ink-muted); cursor: pointer;
        transition: all 0.15s ease;
      }

      .mode-btn:hover { background: var(--surface-2); color: var(--ink); }

      .mode-btn.active {
        background: var(--surface); color: var(--ink);
        box-shadow: 0 1px 3px rgba(0,0,0,0.12);
        border: 1px solid var(--line);
      }

      .mode-icon { font-size: 14px; }
      .mode-label { font-size: 13px; font-weight: 600; }
      .mode-sub { font-size: 10.5px; color: var(--ink-muted); }

      /* Status */
      .status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-2); }
      .dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
      .statustext { font-variant-numeric: tabular-nums; }
      .tier {
        padding: 2px 7px; border-radius: 999px;
        background: var(--surface-sunken); border: 1px solid var(--line);
        font-size: 11px; color: var(--ink-muted); white-space: nowrap;
      }

      /* Context bar */
      .nav-context-bar {
        display: flex; align-items: center; gap: 10px;
        padding: 6px 20px; font-size: 12px; border-bottom: 1px solid var(--line);
      }
      .business-bar {
        background: color-mix(in srgb, #7c3aed 6%, var(--surface));
        border-bottom-color: color-mix(in srgb, #7c3aed 20%, transparent);
      }
      .ops-bar {
        background: color-mix(in srgb, var(--accent) 6%, var(--surface));
        border-bottom-color: color-mix(in srgb, var(--accent) 20%, transparent);
      }
      .ctx-label { font-weight: 650; color: var(--ink); }
      .ctx-desc { color: var(--ink-muted); }

      /* Tabs */
      .tabs {
        display: flex; gap: 2px; padding: 0 20px;
        background: var(--surface); border-bottom: 1px solid var(--line); overflow-x: auto;
      }
      .tabs button {
        appearance: none; background: none; border: none;
        border-bottom: 2px solid transparent; padding: 9px 14px;
        font-size: 13px; font-weight: 500; color: var(--ink-muted);
        white-space: nowrap; display: inline-flex; align-items: center;
        gap: 6px; cursor: pointer;
      }
      .tabs button:hover { color: var(--ink); }
      .tabs button.active { color: var(--ink); border-bottom-color: var(--accent); font-weight: 600; }
      .tab-icon { font-size: 13px; }
      .pill {
        font-family: var(--mono); font-size: 10px; padding: 1px 5px;
        border-radius: 4px; background: var(--accent-bg);
        border: 1px solid var(--accent-line); color: var(--accent);
      }

      main { padding: 18px 20px 56px; max-width: 1280px; margin: 0 auto; }

      /* Business Overview */
      .business-overview { display: flex; flex-direction: column; gap: 20px; }

      .biz-kpi-section, .vendor-scorecard {
        background: var(--surface); border: 1px solid var(--line);
        border-radius: var(--radius); padding: 16px;
      }

      .biz-kpi-head {
        display: flex; justify-content: space-between; align-items: flex-start;
        gap: 12px; flex-wrap: wrap; margin-bottom: 14px;
        padding-bottom: 12px; border-bottom: 1px solid var(--line);
      }

      .biz-h2 {
        margin: 0; font-size: 13px; font-weight: 650;
        letter-spacing: 0.02em; text-transform: uppercase; color: var(--ink-2);
      }

      .biz-hint { margin: 3px 0 0; font-size: 12px; color: var(--ink-muted); }

      .biz-badge {
        font-size: 10.5px; font-weight: 600; color: var(--good);
        background: color-mix(in srgb, var(--good) 10%, transparent);
        border: 1px solid color-mix(in srgb, var(--good) 30%, transparent);
        padding: 2px 8px; border-radius: 4px; white-space: nowrap;
      }

      .biz-kpis {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 10px;
      }

      .biz-tile {
        display: flex; gap: 10px; padding: 12px;
        border-radius: var(--radius); border: 1px solid var(--line);
        background: var(--surface-2);
      }

      .biz-tile.warn {
        border-color: color-mix(in srgb, var(--warning) 35%, transparent);
        background: color-mix(in srgb, var(--warning) 5%, var(--surface));
      }

      .biz-tile.crit {
        border-color: color-mix(in srgb, var(--critical) 25%, transparent);
        background: color-mix(in srgb, var(--critical) 4%, var(--surface));
      }

      .biz-tile-icon { font-size: 20px; flex: none; line-height: 1; margin-top: 2px; }
      .biz-tile-body { min-width: 0; }

      .biz-tile-label {
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.04em; color: var(--ink-muted);
      }

      .biz-tile-val {
        font-size: 22px; font-weight: 650; letter-spacing: -0.02em;
        color: var(--ink); margin-top: 3px; font-variant-numeric: tabular-nums;
      }

      .biz-tile-sub { font-size: 11px; color: var(--ink-muted); margin-top: 2px; line-height: 1.4; }

      .biz-tile-trend { font-size: 11.5px; font-weight: 550; margin-top: 5px; }
      .biz-tile-trend.up { color: var(--good); }
      .biz-tile-trend.down { color: var(--critical); }
      .biz-tile-trend.neutral { color: var(--ink-muted); }

      /* Vendor scorecard */
      .scorecard-table-wrap { overflow-x: auto; }

      .scorecard-table {
        width: 100%; border-collapse: collapse;
        font-size: 12.5px; min-width: 560px;
      }

      .scorecard-table th {
        text-align: left; font-size: 10.5px; text-transform: uppercase;
        letter-spacing: 0.04em; color: var(--ink-muted); font-weight: 600;
        padding: 6px 10px; border-bottom: 1px solid var(--line-strong); white-space: nowrap;
      }

      .scorecard-table td {
        padding: 8px 10px; border-bottom: 1px solid var(--line); color: var(--ink-2);
      }

      .scorecard-table th.r, .scorecard-table td.r { text-align: right; }
      .scorecard-table td.num { font-variant-numeric: tabular-nums; }
      .scorecard-table td.crit { color: var(--critical); font-weight: 600; }
      .scorecard-table td.warn { color: var(--warning); font-weight: 600; }
      .scorecard-table td.good { color: var(--good); font-weight: 600; }

      .risk-red td { background: color-mix(in srgb, var(--critical) 4%, transparent); }
      .risk-amber td { background: color-mix(in srgb, var(--warning) 4%, transparent); }

      .risk-badge {
        display: inline-block; font-size: 10.5px; font-weight: 650; padding: 1px 7px; border-radius: 4px;
      }
      .risk-badge.red { background: color-mix(in srgb, var(--critical) 12%, transparent); color: var(--critical); }
      .risk-badge.amber { background: color-mix(in srgb, var(--warning) 12%, transparent); color: var(--warning); }
      .risk-badge.green { background: color-mix(in srgb, var(--good) 12%, transparent); color: var(--good); }
    `,
  ],
})
export class AppComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly glossary = inject(GlossaryService);

  readonly navMode = signal<NavMode>('operational');
  readonly businessTab = signal<BusinessTab>('overview');
  readonly operationalTab = signal<OperationalTab>('dashboard');
  readonly selectedIncident = signal<string | null>(null);
  readonly health = signal<Health | null>(null);
  readonly healthError = signal<string | null>(null);

  readonly businessTabs: { id: BusinessTab; label: string; icon: string }[] = [
    { id: 'overview', label: 'Overview',     icon: '📊' },
    { id: 'brief',    label: 'Period Brief', icon: '📋' },
    { id: 'chat',     label: 'Ask Agent',    icon: '💬' },
  ];

  readonly operationalTabs: { id: OperationalTab; label: string; icon: string }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: '🔢' },
    { id: 'incident',  label: 'Incident',  icon: '🚨' },
    { id: 'outbox',    label: 'Outbox',    icon: '📤' },
  ];

  setMode(mode: NavMode): void {
    this.navMode.set(mode);
  }

  async ngOnInit(): Promise<void> {
    void this.glossary.load();
    try {
      this.health.set(await this.api.health());
    } catch (e) {
      this.healthError.set(e instanceof Error ? e.message : 'health check failed');
    }
  }

  openIncident(id: string): void {
    this.selectedIncident.set(id);
    this.navMode.set('operational');
    this.operationalTab.set('incident');
  }
}
