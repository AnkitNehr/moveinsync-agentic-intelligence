import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import type { ChatResponse } from '../core/models';
import { num, usd } from '../core/format';

/**
 * Ask-the-data.
 *
 * The resolved tool call is shown verbatim, in mono, next to every answer. That
 * is the point of this screen: the question is natural language but the answer
 * is not — it is a metric-layer call with a metric id, a grain, an entity and a
 * period, and showing it is what separates a queried figure from a generated
 * one. If the router declines, the vocabulary it *can* answer in is listed so
 * the question can be rephrased rather than merely rejected.
 */
@Component({
  selector: 'mi-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="panel">
      <h2>Ask the data</h2>
      <p class="hint">
        Questions are resolved against the metric catalog. Anything outside that
        vocabulary is declined rather than guessed at.
      </p>

      <form (submit)="ask($event)">
        <input
          type="text"
          [(ngModel)]="question"
          name="question"
          [disabled]="loading()"
          placeholder="Why did on-time arrival drop in June?"
          autocomplete="off" />
        <button type="submit" class="primary" [disabled]="loading() || !question.trim()">
          {{ loading() ? 'Asking…' : 'Ask' }}
        </button>
      </form>

      <div class="suggestions">
        @for (s of samples; track s) {
          <button class="chip" (click)="useSample(s)" [disabled]="loading()">{{ s }}</button>
        }
      </div>

      @if (error()) {
        <p class="error">{{ error() }}</p>
      }
    </section>

    @if (response(); as r) {
      <section class="panel" [class.declined]="r.declined">
        <div class="ans-head">
          <h2>{{ r.declined ? 'Declined' : 'Answer' }}</h2>
          <span class="tier mono">{{ r.tier }}</span>
        </div>

        <p class="answer">{{ r.answer }}</p>

        <!-- The resolved call: small, mono, always visible. -->
        @if (r.resolvedCall; as c) {
          <div class="call">
            <div class="call-h">Resolved tool call</div>
            <code class="mono"
              >{{ c.tool }}(metric="{{ c.metricId }}", dimension="{{ c.dimension }}",
              entity="{{ c.entity }}", period="{{ c.period }}")</code
            >
          </div>
        } @else {
          <div class="call empty">
            <div class="call-h">Resolved tool call</div>
            <code class="mono">— none; the question did not map to a catalog metric</code>
          </div>
        }

        @if (r.citations?.length) {
          <h3>Citations</h3>
          <ul class="cites">
            @for (c of r.citations; track c.claim) {
              <li>
                <span>{{ c.claim }}</span>
                @if (c.metricId) {
                  <span class="cite mono">{{ c.metricId }}@if (c.entity) {&middot;{{ c.entity }}}</span>
                }
              </li>
            }
          </ul>
        }

        @if (r.usage; as u) {
          <div class="usage num">
            <span><b>{{ num(u.calls) }}</b> model call{{ u.calls === 1 ? '' : 's' }}</span>
            <span><b>{{ num(u.promptTokens) }}</b> prompt tokens</span>
            <span><b>{{ num(u.completionTokens) }}</b> completion tokens</span>
            <span class="accent"><b>{{ usd(u.estimatedCostUsd) }}</b> estimated</span>
          </div>
        }

        @if (r.declined && r.knownMetrics?.length) {
          <h3>Vocabulary this endpoint answers in</h3>
          <div class="known">
            @for (m of r.knownMetrics; track m) {
              <span class="chip static mono">{{ m }}</span>
            }
          </div>
        }
      </section>
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

      .panel.declined {
        border-left: 3px solid var(--warning);
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
        margin: 15px 0 6px;
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
        max-width: 74ch;
      }

      form {
        display: flex;
        gap: 8px;
        margin-top: 12px;
      }

      input {
        flex: 1;
        min-width: 0;
        font: inherit;
        font-size: 13.5px;
        padding: 9px 12px;
        border-radius: var(--radius);
        border: 1px solid var(--line-strong);
        background: var(--surface-2);
        color: var(--ink);
      }

      input:focus {
        outline: none;
        border-color: var(--accent);
      }

      input::placeholder {
        color: var(--ink-muted);
      }

      button.primary {
        background: var(--accent);
        color: #fff;
        border: none;
        border-radius: var(--radius);
        padding: 9px 20px;
        font-size: 13px;
        font-weight: 600;
        white-space: nowrap;
      }

      button.primary:hover:not(:disabled) {
        filter: brightness(1.08);
      }

      button.primary:disabled {
        opacity: 0.5;
      }

      .suggestions {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-top: 10px;
      }

      .chip {
        background: var(--surface-2);
        border: 1px solid var(--line);
        border-radius: 999px;
        padding: 4px 11px;
        font-size: 11.5px;
        color: var(--ink-muted);
      }

      .chip:hover:not(:disabled) {
        border-color: var(--accent-line);
        color: var(--accent);
      }

      .chip.static {
        cursor: default;
        border-radius: 4px;
        font-size: 11px;
      }

      .error {
        margin: 10px 0 0;
        color: var(--critical);
        font-size: 12.5px;
      }

      .ans-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }

      .tier {
        font-size: 10.5px;
        padding: 2px 7px;
        border-radius: 999px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        color: var(--ink-muted);
      }

      .mono {
        font-family: var(--mono);
      }

      .answer {
        margin: 10px 0 0;
        font-size: 14px;
        line-height: 1.65;
        color: var(--ink);
        max-width: 82ch;
        white-space: pre-wrap;
      }

      /* The resolved call — small mono, deliberately understated but always there. */
      .call {
        margin-top: 14px;
        padding: 9px 11px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        overflow-x: auto;
      }

      .call.empty code {
        color: var(--ink-muted);
      }

      .call-h {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--ink-muted);
        margin-bottom: 4px;
      }

      .call code {
        font-size: 11.5px;
        color: var(--ink-2);
        white-space: pre;
        display: block;
      }

      .cites {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 5px;
      }

      .cites li {
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

      .usage {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-top: 14px;
        padding-top: 11px;
        border-top: 1px solid var(--line);
        font-size: 11.5px;
        color: var(--ink-muted);
      }

      .usage b {
        color: var(--ink);
        font-weight: 620;
      }

      .usage .accent b {
        color: var(--accent);
      }

      .known {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
      }
    `,
  ],
})
export class ChatComponent implements OnInit {
  private readonly api = inject(ApiService);

  question = '';
  readonly response = signal<ChatResponse | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  readonly samples = [
    'Why did on-time arrival drop in June?',
    'What is the cost per trip for June 2026?',
    'Which office had the worst OTA in June?',
    'What is the no-show rate?',
  ];

  readonly num = num;
  readonly usd = usd;

  ngOnInit(): void {
    /* nothing to preload — the catalog arrives with a declined answer */
  }

  useSample(s: string): void {
    this.question = s;
    void this.send();
  }

  ask(event: Event): void {
    event.preventDefault();
    void this.send();
  }

  private async send(): Promise<void> {
    const q = this.question.trim();
    if (!q || this.loading()) return;

    this.loading.set(true);
    this.error.set(null);
    try {
      this.response.set(await this.api.chat(q));
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }
}
