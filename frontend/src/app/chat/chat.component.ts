import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { GlossaryService } from '../core/glossary.service';
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

    @for (turn of turns(); track $index) {
      <!-- The question is echoed above its own answer. Without it the thread is a column of
           replies to questions the reader has to remember, which is the failure mode of every
           analytics chat that treats the answer as the artefact. -->
      <div class="asked"><span class="asked-q">{{ turn.question }}</span></div>

      @if (turn.response; as r) {
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
                  <span class="cite">{{ metricLabel(c.metricId) }}@if (c.entity) { · {{ c.entity }}}</span>
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
    }

    @if (loading()) {
      <div class="asked"><span class="asked-q">{{ question }}</span></div>
      <section class="panel thinking"><p class="hint">Resolving against the metric catalog…</p></section>
    }
  `,
  styles: [
    `
      :host {
        display: block;
      }

      /* The asked question, right-aligned above its answer — the one visual cue that says
         "conversation" rather than "report". Deliberately quiet: the answer is the content. */
      .asked {
        display: flex;
        justify-content: flex-end;
        margin: 18px 0 6px;
      }
      .asked-q {
        max-width: min(680px, 82%);
        padding: 9px 14px;
        border-radius: 14px 14px 3px 14px;
        background: color-mix(in srgb, var(--accent, #4a7dff) 14%, transparent);
        border: 1px solid color-mix(in srgb, var(--accent, #4a7dff) 26%, transparent);
        font-size: 14px;
        line-height: 1.45;
      }

      .panel.thinking {
        opacity: 0.72;
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
  private readonly glossary = inject(GlossaryService);

  question = '';
  /**
   * The conversation so far, oldest first.
   *
   * Previously one `response` signal, replaced on every ask — so the screen showed a single answer
   * and the question that produced it was already gone from the input. That is a query box, not a
   * conversation: a reader could not compare July against June without re-reading two screens, and
   * the natural next move after any answer is to ask something adjacent to it.
   *
   * Keeping the turns is also what makes the resolved tool call worth showing. One call in isolation
   * is a curiosity; a column of them beside a column of answers is the claim this screen exists to
   * make — that every reply came from a metric-layer call, visibly, every time.
   */
  readonly turns = signal<{ question: string; response: ChatResponse }[]>([]);
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
    void this.glossary.load();
  }

  metricLabel(id: string | null | undefined): string {
    return this.glossary.metricLabel(id);
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
      const prior = this.turns();
      const previousQuestion = prior.length ? prior[prior.length - 1].question : undefined;
      const response = await this.api.chat(q, undefined, previousQuestion);
      this.turns.update((t) => [...t, { question: q, response }]);
      // The box empties on success only. A failed ask leaves the text where it was so the question
      // can be retried or edited rather than retyped.
      this.question = '';
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.loading.set(false);
    }
  }
}
