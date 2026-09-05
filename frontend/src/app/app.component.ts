import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from './core/api.service';
import type { Health } from './core/models';
import { DashboardComponent } from './dashboard/dashboard.component';
import { IncidentComponent } from './incident/incident.component';
import { ChatComponent } from './chat/chat.component';
import { BriefComponent } from './brief/brief.component';
import { OutboxComponent } from './outbox/outbox.component';

type Tab = 'dashboard' | 'incident' | 'chat' | 'brief' | 'outbox';

/**
 * Root shell. Five tabs, no router — the console is one page and a router would
 * add a dependency and a URL contract for no operational gain.
 *
 * The selected incident id lives here rather than in a store so the dashboard
 * can hand off to the incident view by plain input binding. That is the entire
 * cross-view state in this application.
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
    <header class="top">
      <div class="brand">
        <span class="mark" aria-hidden="true"></span>
        <div>
          <h1>Mobility Intelligence</h1>
          <p class="sub">Agentic ops console &middot; Campus transport &middot; May–Jul 2026</p>
        </div>
      </div>

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

    <nav class="tabs" role="tablist">
      @for (t of tabs; track t.id) {
        <button
          role="tab"
          [attr.aria-selected]="tab() === t.id"
          [class.active]="tab() === t.id"
          (click)="tab.set(t.id)">
          {{ t.label }}
          @if (t.id === 'incident' && selectedIncident()) {
            <span class="pill">{{ selectedIncident() }}</span>
          }
        </button>
      }
    </nav>

    <main>
      @switch (tab()) {
        @case ('dashboard') {
          <mi-dashboard
            (openIncident)="openIncident($event)"
            (healthChanged)="health.set($event)" />
        }
        @case ('incident') {
          <mi-incident [incidentId]="selectedIncident()" />
        }
        @case ('chat') {
          <mi-chat />
        }
        @case ('brief') {
          <mi-brief />
        }
        @case ('outbox') {
          <mi-outbox />
        }
      }
    </main>
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
        padding: 14px 20px;
        background: var(--surface);
        border-bottom: 1px solid var(--line);
      }

      .brand {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .mark {
        width: 30px;
        height: 30px;
        border-radius: 7px;
        background: linear-gradient(135deg, var(--accent) 0%, #78350f 100%);
        flex: none;
      }

      h1 {
        margin: 0;
        font-size: 15px;
        font-weight: 650;
        letter-spacing: -0.01em;
      }

      .sub {
        margin: 1px 0 0;
        font-size: 11.5px;
        color: var(--ink-muted);
      }

      .status {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        color: var(--ink-2);
      }

      .dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex: none;
      }

      .statustext {
        font-variant-numeric: tabular-nums;
      }

      .tier {
        padding: 2px 7px;
        border-radius: 999px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        font-size: 11px;
        color: var(--ink-muted);
        white-space: nowrap;
      }

      .tabs {
        display: flex;
        gap: 2px;
        padding: 0 20px;
        background: var(--surface);
        border-bottom: 1px solid var(--line);
        overflow-x: auto;
      }

      .tabs button {
        appearance: none;
        background: none;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 9px 14px;
        font-size: 13px;
        font-weight: 500;
        color: var(--ink-muted);
        white-space: nowrap;
        display: inline-flex;
        align-items: center;
        gap: 7px;
      }

      .tabs button:hover {
        color: var(--ink);
      }

      .tabs button.active {
        color: var(--ink);
        border-bottom-color: var(--accent);
        font-weight: 600;
      }

      .pill {
        font-family: var(--mono);
        font-size: 10px;
        padding: 1px 5px;
        border-radius: 4px;
        background: var(--accent-bg);
        border: 1px solid var(--accent-line);
        color: var(--accent);
      }

      main {
        padding: 18px 20px 56px;
        max-width: 1280px;
        margin: 0 auto;
      }
    `,
  ],
})
export class AppComponent implements OnInit {
  private readonly api = inject(ApiService);

  readonly tabs: { id: Tab; label: string }[] = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'incident', label: 'Incident' },
    { id: 'chat', label: 'Chat' },
    { id: 'brief', label: 'Brief' },
    { id: 'outbox', label: 'Outbox' },
  ];

  readonly tab = signal<Tab>('dashboard');
  readonly selectedIncident = signal<string | null>(null);
  readonly health = signal<Health | null>(null);
  readonly healthError = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    try {
      this.health.set(await this.api.health());
    } catch (e) {
      this.healthError.set(e instanceof Error ? e.message : 'health check failed');
    }
  }

  openIncident(id: string): void {
    this.selectedIncident.set(id);
    this.tab.set('incident');
  }
}
