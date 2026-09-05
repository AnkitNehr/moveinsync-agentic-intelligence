import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../core/api.service';
import type { Communication } from '../core/models';
import { shortTime } from '../core/format';

/**
 * Every message the platform drafted, sent, or refused. This is the artefact of act.
 */
@Component({
  selector: 'mi-outbox',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>Outbox</h2>
          <p class="hint">
            Notify is sent to the console automatically. Blocked vendor letters stay visible so a
            refusal cannot be mistaken for silence.
          </p>
        </div>
        <button class="ghost" (click)="reload()" [disabled]="loading()">
          {{ loading() ? 'Loading…' : 'Refresh' }}
        </button>
      </div>
      @if (error()) {
        <p class="error">{{ error() }}</p>
      }
    </section>

    <div class="layout">
      <ul class="list">
        @for (m of messages(); track m.id) {
          <li>
            <button [class.active]="selected()?.id === m.id" (click)="select(m)">
              <span class="chip" [attr.data-status]="m.status">{{ m.status }}</span>
              <span class="who">{{ m.recipient }}</span>
              <span class="subj">{{ m.subject }}</span>
              <span class="when num">{{ shortTime(m.createdAt) }}</span>
            </button>
          </li>
        } @empty {
          <li class="idle">No communications yet. Run an analysis — notify is sent on persist.</li>
        }
      </ul>

      @if (selected(); as m) {
        <article class="document" id="outbox-doc">
          <header class="doc-head">
            <div>
              <div class="eyebrow">{{ m.channel }} &middot; {{ m.persona }} &middot; {{ m.actionType }}</div>
              <h1>{{ m.subject }}</h1>
              <p class="to">To: {{ m.recipient }}</p>
            </div>
            <span class="chip" [attr.data-status]="m.status">{{ m.status }}</span>
          </header>
          @if (m.blockedReason) {
            <p class="blocked">{{ m.blockedReason }}</p>
          }
          <pre class="body">{{ m.body }}</pre>
          <footer class="doc-foot">
            <span class="mono">{{ m.id }}</span>
            <span class="mono">{{ m.incidentId }}</span>
            <div class="btns">
              <button class="ghost" (click)="copy(m)">{{ copied() ? 'Copied' : 'Copy' }}</button>
              <button class="primary" (click)="print()">Print / PDF</button>
            </div>
          </footer>
        </article>
      }
    </div>
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
        padding: 11px 13px;
        margin-bottom: 14px;
      }
      .panel-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
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
        max-width: 72ch;
      }
      .error {
        color: var(--critical);
        font-size: 12.5px;
      }
      button.ghost,
      button.primary {
        border-radius: var(--radius);
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 550;
      }
      button.ghost {
        background: var(--surface-2);
        color: var(--ink-2);
        border: 1px solid var(--line-strong);
      }
      button.primary {
        background: var(--accent);
        color: #fff;
        border: none;
        font-weight: 600;
      }
      .layout {
        display: grid;
        grid-template-columns: minmax(240px, 340px) 1fr;
        gap: 14px;
        align-items: start;
      }
      @media (max-width: 840px) {
        .layout {
          grid-template-columns: 1fr;
        }
      }
      .list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .list button {
        width: 100%;
        text-align: left;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 9px 11px;
        display: flex;
        flex-direction: column;
        gap: 3px;
      }
      .list button.active {
        border-color: var(--accent);
        background: var(--accent-bg);
      }
      .who {
        font-size: 12px;
        font-weight: 600;
      }
      .subj {
        font-size: 12px;
        color: var(--ink-2);
      }
      .when {
        font-size: 10.5px;
        color: var(--ink-muted);
      }
      .idle {
        font-size: 12.5px;
        color: var(--ink-muted);
        padding: 12px 4px;
      }
      .chip {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.04em;
        width: fit-content;
        padding: 1px 7px;
        border-radius: 999px;
        border: 1px solid var(--line);
        color: var(--ink-muted);
      }
      .chip[data-status='SENT'] {
        color: var(--good);
        border-color: color-mix(in srgb, var(--good) 40%, var(--line));
      }
      .chip[data-status='BLOCKED'] {
        color: var(--critical);
        border-color: color-mix(in srgb, var(--critical) 40%, var(--line));
      }
      .document {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 22px 26px 16px;
      }
      .doc-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding-bottom: 12px;
        border-bottom: 2px solid var(--ink);
      }
      .eyebrow {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--accent);
        font-weight: 700;
      }
      .doc-head h1 {
        margin: 6px 0 0;
        font-size: 18px;
        font-weight: 650;
        letter-spacing: -0.02em;
      }
      .to {
        margin: 6px 0 0;
        font-size: 12.5px;
        color: var(--ink-2);
      }
      .blocked {
        margin: 12px 0 0;
        padding: 8px 10px;
        background: color-mix(in srgb, var(--critical) 10%, transparent);
        border: 1px solid color-mix(in srgb, var(--critical) 35%, transparent);
        border-radius: var(--radius);
        color: var(--critical);
        font-size: 12.5px;
      }
      .body {
        white-space: pre-wrap;
        font-family: var(--sans);
        font-size: 13.5px;
        line-height: 1.6;
        color: var(--ink);
        margin: 16px 0 0;
      }
      .doc-foot {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
        margin-top: 18px;
        padding-top: 10px;
        border-top: 1px solid var(--line);
        font-size: 11px;
        color: var(--ink-muted);
      }
      .btns {
        margin-left: auto;
        display: flex;
        gap: 8px;
      }
    `,
  ],
})
export class OutboxComponent implements OnInit {
  private readonly api = inject(ApiService);

  readonly shortTime = shortTime;
  readonly messages = signal<Communication[]>([]);
  readonly selected = signal<Communication | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly copied = signal(false);

  ngOnInit(): void {
    void this.reload();
  }

  async reload(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const list = await this.api.outbox();
      this.messages.set(list);
      const current = this.selected();
      const next = current ? list.find((m) => m.id === current.id) ?? list[0] ?? null : list[0] ?? null;
      this.selected.set(next);
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }

  select(m: Communication): void {
    this.selected.set(m);
    this.copied.set(false);
  }

  async copy(m: Communication): Promise<void> {
    try {
      await navigator.clipboard.writeText(`${m.subject}\n\n${m.body}`);
      this.copied.set(true);
    } catch {
      this.copied.set(false);
    }
  }

  print(): void {
    window.print();
  }
}
