import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import type { Brief } from '../core/models';
import { periodLabel, shortTime } from '../core/format';
import { renderMarkdown } from './markdown';

/**
 * The facilities-head brief, rendered as something you would actually forward.
 *
 * This view is deliberately a document and not a dashboard: it is the artefact
 * that leaves the building. Hence the paper-like column, the copy / download /
 * print affordances, and the provenance footer — a brief that arrives in an
 * inbox without the period, the persona and which tier generated it cannot be
 * checked by the person receiving it.
 */
@Component({
  selector: 'mi-brief',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="panel controls">
      <div class="ctl">
        <label for="persona">Reader</label>
        <select id="persona" [(ngModel)]="persona" (ngModelChange)="reload()" [disabled]="loading()">
          @for (p of personas(); track p) {
            <option [value]="p">{{ p }}</option>
          }
        </select>
      </div>

      <div class="ctl">
        <label for="period">Period</label>
        <input
          id="period"
          type="text"
          [(ngModel)]="period"
          (blur)="reload()"
          placeholder="latest"
          size="9"
          autocomplete="off" />
      </div>

      <div class="spacer"></div>

      <button class="ghost" (click)="reload()" [disabled]="loading()">
        {{ loading() ? 'Rendering…' : 'Refresh' }}
      </button>
      <button class="ghost" (click)="copy()" [disabled]="!brief()">
        {{ copied() ? 'Copied' : 'Copy markdown' }}
      </button>
      <button class="ghost" (click)="download()" [disabled]="!brief()">Download .md</button>
      <button class="primary" (click)="print()" [disabled]="!brief()">Print / PDF</button>
    </section>

    @if (error()) {
      <section class="panel"><p class="error">{{ error() }}</p></section>
    }

    @if (brief(); as b) {
      <article class="document" id="brief-doc">
        <header class="doc-head">
          <div>
            <div class="eyebrow">Operations brief &middot; {{ b.persona }}</div>
            <h1>Campus Transport &mdash; {{ periodLabel(b.period) }}</h1>
          </div>
          <div class="seal" aria-hidden="true"></div>
        </header>

        @if (b.headline?.length) {
          <div class="headline">
            <div class="hl-h">Headline figures</div>
            <ul>
              @for (h of b.headline; track h) {
                <li class="num">{{ h }}</li>
              }
            </ul>
          </div>
        }

        <!-- Rendered from the backend's markdown. Angular's sanitizer is left
             switched on: the content is escaped before any tag is introduced,
             and the binding is sanitised again on the way in. -->
        <div class="md" [innerHTML]="html()"></div>

        <footer class="doc-foot">
          <div>
            @if (b.incidentIds?.length) {
              Covers {{ b.incidentIds.length }} open incident{{ b.incidentIds.length === 1 ? '' : 's' }}:
              <span class="mono">{{ b.incidentIds.join(', ') }}</span>
            } @else {
              No open incidents for this period.
            }
          </div>
          <div class="prov">
            Generated {{ shortTime(b.generatedAt) }} &middot; tier
            <span class="mono">{{ b.tier }}</span> &middot; period
            <span class="mono">{{ b.period }}</span>
          </div>
        </footer>
      </article>
    } @else if (loading()) {
      <section class="panel"><p class="hint">Rendering brief…</p></section>
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
        padding: 11px 13px;
        margin-bottom: 14px;
      }

      .controls {
        display: flex;
        align-items: center;
        gap: 9px;
        flex-wrap: wrap;
      }

      .ctl {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
        font-weight: 600;
      }

      select,
      input {
        font: inherit;
        font-size: 12.5px;
        padding: 5px 9px;
        border-radius: var(--radius);
        border: 1px solid var(--line-strong);
        background: var(--surface-2);
        color: var(--ink);
      }

      select:focus,
      input:focus {
        outline: none;
        border-color: var(--accent);
      }

      .spacer {
        flex: 1;
      }

      button.ghost {
        background: var(--surface-2);
        color: var(--ink-2);
        border: 1px solid var(--line-strong);
        border-radius: var(--radius);
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 550;
      }

      button.ghost:hover:not(:disabled) {
        border-color: var(--accent);
        color: var(--accent);
      }

      button.primary {
        background: var(--accent);
        color: #fff;
        border: none;
        border-radius: var(--radius);
        padding: 6px 15px;
        font-size: 12px;
        font-weight: 600;
      }

      button:disabled {
        opacity: 0.5;
      }

      .hint {
        margin: 0;
        font-size: 12px;
        color: var(--ink-muted);
      }

      .error {
        margin: 0;
        color: var(--critical);
        font-size: 12.5px;
      }

      /* ---- the document ---- */
      .document {
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 30px 36px 22px;
        max-width: 78ch;
        margin: 0 auto;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
      }

      .doc-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        padding-bottom: 14px;
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
        margin: 5px 0 0;
        font-size: 22px;
        font-weight: 650;
        letter-spacing: -0.02em;
        line-height: 1.25;
      }

      .seal {
        width: 28px;
        height: 28px;
        border-radius: 7px;
        background: linear-gradient(135deg, var(--accent) 0%, #78350f 100%);
        flex: none;
      }

      .headline {
        margin: 16px 0 4px;
        padding: 11px 13px;
        background: var(--accent-bg);
        border: 1px solid var(--accent-line);
        border-radius: var(--radius);
      }

      .hl-h {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--accent);
        font-weight: 700;
        margin-bottom: 5px;
      }

      .headline ul {
        margin: 0;
        padding-left: 16px;
        display: flex;
        flex-direction: column;
        gap: 3px;
      }

      .headline li {
        font-size: 12.5px;
        color: var(--ink-2);
      }

      /* ---- markdown body ---- */
      .md {
        font-size: 14px;
        line-height: 1.68;
        color: var(--ink);
      }

      .md :first-child {
        margin-top: 8px;
      }

      .md h1,
      .md h2,
      .md h3 {
        letter-spacing: -0.01em;
        line-height: 1.3;
        margin: 22px 0 7px;
      }

      .md h1 {
        font-size: 18px;
        font-weight: 650;
      }

      .md h2 {
        font-size: 15.5px;
        font-weight: 650;
        padding-bottom: 5px;
        border-bottom: 1px solid var(--line);
      }

      .md h3 {
        font-size: 13.5px;
        font-weight: 650;
        color: var(--ink-2);
      }

      .md p {
        margin: 9px 0;
      }

      .md ul,
      .md ol {
        margin: 9px 0;
        padding-left: 21px;
      }

      .md li {
        margin: 3px 0;
      }

      .md strong {
        font-weight: 650;
      }

      .md code {
        font-family: var(--mono);
        font-size: 12px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        border-radius: 3px;
        padding: 1px 4px;
      }

      .md pre {
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        padding: 10px 12px;
        overflow-x: auto;
      }

      .md pre code {
        background: none;
        border: none;
        padding: 0;
        font-size: 11.5px;
      }

      .md blockquote {
        margin: 11px 0;
        padding: 2px 0 2px 13px;
        border-left: 3px solid var(--accent-line);
        color: var(--ink-2);
      }

      .md hr {
        border: none;
        border-top: 1px solid var(--line);
        margin: 20px 0;
      }

      .md table {
        width: 100%;
        border-collapse: collapse;
        font-size: 12.5px;
        margin: 11px 0;
        font-variant-numeric: tabular-nums;
      }

      .md th {
        text-align: left;
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--ink-muted);
        padding: 5px 9px;
        border-bottom: 1px solid var(--line-strong);
      }

      .md td {
        padding: 5px 9px;
        border-bottom: 1px solid var(--line);
        color: var(--ink-2);
      }

      /* Wide tables scroll in their own box; the page never scrolls sideways. */
      .md .table-wrap {
        overflow-x: auto;
      }

      .doc-foot {
        margin-top: 24px;
        padding-top: 12px;
        border-top: 1px solid var(--line);
        display: flex;
        justify-content: space-between;
        gap: 14px;
        flex-wrap: wrap;
        font-size: 11px;
        color: var(--ink-muted);
      }

      .mono {
        font-family: var(--mono);
      }

      .prov {
        text-align: right;
      }

      @media print {
        .controls {
          display: none;
        }

        .document {
          border: none;
          box-shadow: none;
          padding: 0;
          max-width: none;
        }
      }
    `,
  ],
})
export class BriefComponent implements OnInit {
  private readonly api = inject(ApiService);

  persona = 'transport_manager';
  period = '';

  readonly brief = signal<Brief | null>(null);
  readonly personas = signal<string[]>(['transport_manager']);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly copied = signal(false);

  readonly html = computed(() => renderMarkdown(this.brief()?.markdown ?? ''));

  readonly periodLabel = periodLabel;
  readonly shortTime = shortTime;

  async ngOnInit(): Promise<void> {
    try {
      const list = await this.api.personas();
      if (list?.length) {
        this.personas.set(list);
        if (!list.includes(this.persona)) this.persona = list[0];
      }
    } catch {
      /* the single default persona is a valid fallback */
    }
    await this.reload();
  }

  async reload(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      this.brief.set(await this.api.brief(this.period || undefined, this.persona));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      this.brief.set(null);
    } finally {
      this.loading.set(false);
    }
  }

  async copy(): Promise<void> {
    const md = this.brief()?.markdown;
    if (!md) return;
    try {
      await navigator.clipboard.writeText(md);
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1800);
    } catch {
      this.error.set('Clipboard access was denied by the browser.');
    }
  }

  download(): void {
    const b = this.brief();
    if (!b) return;
    const blob = new Blob([b.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `brief-${b.period}-${b.persona}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  print(): void {
    window.print();
  }
}
