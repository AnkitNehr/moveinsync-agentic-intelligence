import { Component, OnInit, inject, signal, ElementRef, ViewChild, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { GlossaryService } from '../core/glossary.service';
import type { ChatResponse } from '../core/models';
import { num, usd } from '../core/format';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  time: string;
  response?: ChatResponse;
}

/**
 * Conversational Ask-the-Data Console.
 *
 * Provides a conversational thread with Ground-Truth Tool Call transparency.
 * Every answer displays the exact resolved metric-layer tool call, citation bindings,
 * and execution tier.
 */
@Component({
  selector: 'mi-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="chat-container">
      <!-- Chat Header -->
      <div class="chat-top-bar">
        <div class="chat-agent-info">
          <div class="agent-avatar">🤖</div>
          <div>
            <div class="agent-name">MoveInSync Intelligence Agent</div>
            <div class="agent-status">
              <span class="pulse-dot"></span>
              Connected &middot; Ground-truth metric SQL & LLM translation
            </div>
          </div>
        </div>
        <button class="btn-clear" (click)="clearChat()" title="Reset conversation">
          🗑️ Clear
        </button>
      </div>

      <!-- Quick Suggestion Pills -->
      <div class="suggestions-bar">
        <span class="sugg-label">Try:</span>
        <div class="chips-scroll">
          @for (s of samples; track s) {
            <button class="sugg-chip" (click)="useSample(s)" [disabled]="loading()">
              {{ s }}
            </button>
          }
        </div>
      </div>

      <!-- Message History Thread -->
      <div class="messages-area" #scrollContainer>
        @for (m of messages(); track m.id) {
          <div class="message-row" [class.user-row]="m.role === 'user'" [class.agent-row]="m.role === 'assistant'">
            @if (m.role === 'assistant') {
              <div class="msg-avatar">🤖</div>
            }

            <div class="msg-bubble" [class.user-bubble]="m.role === 'user'" [class.agent-bubble]="m.role === 'assistant'">
              <div class="msg-header">
                <span class="msg-author">{{ m.role === 'user' ? 'You' : 'Mobility AI' }}</span>
                <span class="msg-time">{{ m.time }}</span>
                @if (m.response?.tier; as tier) {
                  <span class="tier-pill mono">{{ tier }}</span>
                }
              </div>

              <div class="msg-text">{{ m.text }}</div>

              <!-- Tool Call Provenance Box -->
              @if (m.response?.resolvedCall; as c) {
                <div class="tool-call-box">
                  <div class="call-title">⚡ Resolved Tool Call (Deterministic SQL)</div>
                  <code class="mono call-code"
                    >{{ c.tool }}(metric="{{ c.metricId }}", dimension="{{ c.dimension }}",
                    entity="{{ c.entity }}", period="{{ c.period }}")</code
                  >
                </div>
              }

              <!-- Citations -->
              @if (m.response?.citations?.length) {
                <div class="citations-box">
                  <div class="cite-title">Data Citations</div>
                  <div class="cite-list">
                    @for (c of m.response!.citations; track c.claim) {
                      <div class="cite-item">
                        <span class="cite-text">{{ c.claim }}</span>
                        @if (c.metricId) {
                          <span class="cite-metric mono">{{ metricLabel(c.metricId) }}@if (c.entity) { · {{ c.entity }}}</span>
                        }
                      </div>
                    }
                  </div>
                </div>
              }

              <!-- Usage Accounting -->
              @if (m.response?.usage; as u) {
                <div class="usage-meta num">
                  <span>{{ num(u.calls) }} call{{ u.calls === 1 ? '' : 's' }}</span>
                  <span>&middot;</span>
                  <span>{{ num(u.promptTokens + u.completionTokens) }} tokens</span>
                  <span>&middot;</span>
                  <span class="cost-accent">{{ usd(u.estimatedCostUsd) }}</span>
                </div>
              }

              <!-- Declined Hint -->
              @if (m.response?.declined && m.response?.knownMetrics?.length) {
                <div class="declined-box">
                  <div class="declined-title">Available metrics:</div>
                  <div class="known-metrics">
                    @for (km of m.response!.knownMetrics; track km) {
                      <span class="km-chip mono" (click)="useSample('What is ' + km + '?')">{{ km }}</span>
                    }
                  </div>
                </div>
              }
            </div>

            @if (m.role === 'user') {
              <div class="msg-avatar user-icon">👤</div>
            }
          </div>
        }

        <!-- Loading Bubble -->
        @if (loading()) {
          <div class="message-row agent-row">
            <div class="msg-avatar">🤖</div>
            <div class="msg-bubble agent-bubble loading-bubble">
              <span class="dot-typing"></span>
              <span class="loading-label">Resolving against metric layer & LLM query router…</span>
            </div>
          </div>
        }
      </div>

      <!-- Chat Input Dock -->
      <form class="chat-input-dock" (submit)="ask($event)">
        <input
          #inputBox
          type="text"
          [(ngModel)]="question"
          name="question"
          [disabled]="loading()"
          placeholder="Ask anything (e.g., 'What was OTA for Rohan Travel?', 'Why did cost rise in June?')"
          autocomplete="off" />
        <button type="submit" class="btn-send" [disabled]="loading() || !question.trim()">
          <span class="send-icon">➤</span>
          <span>Send</span>
        </button>
      </form>
    </div>
  `,
  styles: [
    `
      :host {
        display: block;
        height: calc(100vh - 165px);
        min-height: 520px;
      }

      .chat-container {
        display: flex;
        flex-direction: column;
        height: 100%;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: var(--radius);
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
      }

      /* Top Header */
      .chat-top-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        background: var(--surface-2);
        border-bottom: 1px solid var(--line);
      }

      .chat-agent-info {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .agent-avatar {
        width: 32px;
        height: 32px;
        border-radius: 8px;
        background: var(--surface-sunken);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 17px;
        border: 1px solid var(--line);
      }

      .agent-name {
        font-size: 13px;
        font-weight: 650;
        color: var(--ink);
      }

      .agent-status {
        font-size: 11px;
        color: var(--ink-muted);
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .pulse-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--good);
        display: inline-block;
      }

      .btn-clear {
        appearance: none;
        background: none;
        border: 1px solid var(--line);
        border-radius: 6px;
        padding: 4px 9px;
        font-size: 11px;
        color: var(--ink-muted);
        cursor: pointer;
        transition: all 0.15s;
      }

      .btn-clear:hover {
        background: var(--surface-sunken);
        color: var(--ink);
      }

      /* Suggestions bar */
      .suggestions-bar {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 7px 16px;
        background: color-mix(in srgb, var(--accent) 3%, var(--surface));
        border-bottom: 1px solid var(--line);
        overflow-x: auto;
      }

      .sugg-label {
        font-size: 11px;
        font-weight: 650;
        text-transform: uppercase;
        color: var(--ink-muted);
        white-space: nowrap;
      }

      .chips-scroll {
        display: flex;
        gap: 6px;
        overflow-x: auto;
      }

      .sugg-chip {
        appearance: none;
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 3px 10px;
        font-size: 11.5px;
        color: var(--ink-2);
        cursor: pointer;
        white-space: nowrap;
        transition: all 0.15s;
      }

      .sugg-chip:hover:not(:disabled) {
        border-color: var(--accent);
        color: var(--accent);
        background: var(--surface-2);
      }

      /* Messages area */
      .messages-area {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        background: var(--surface-sunken);
      }

      .message-row {
        display: flex;
        gap: 10px;
        max-width: 86%;
      }

      .user-row {
        align-self: flex-end;
        flex-direction: row;
      }

      .agent-row {
        align-self: flex-start;
      }

      .msg-avatar {
        width: 28px;
        height: 28px;
        border-radius: 6px;
        background: var(--surface-2);
        border: 1px solid var(--line);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        flex: none;
      }

      .user-icon {
        background: var(--accent);
        color: #fff;
        border: none;
      }

      .msg-bubble {
        padding: 12px 14px;
        border-radius: 10px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        font-size: 13px;
        line-height: 1.55;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
      }

      .user-bubble {
        background: var(--accent);
        color: #fff;
        border-top-right-radius: 2px;
      }

      .agent-bubble {
        background: var(--surface);
        color: var(--ink);
        border: 1px solid var(--line);
        border-top-left-radius: 2px;
      }

      .msg-header {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 10.5px;
        opacity: 0.85;
      }

      .user-bubble .msg-header {
        justify-content: flex-end;
        color: rgba(255, 255, 255, 0.9);
      }

      .agent-bubble .msg-header {
        color: var(--ink-muted);
      }

      .msg-author {
        font-weight: 650;
      }

      .tier-pill {
        font-size: 9.5px;
        font-weight: 700;
        text-transform: uppercase;
        padding: 1px 6px;
        border-radius: 12px;
        background: var(--surface-sunken);
        border: 1px solid var(--line);
        color: var(--accent);
      }

      .msg-text {
        white-space: pre-wrap;
      }

      /* Tool call box */
      .tool-call-box {
        margin-top: 4px;
        padding: 8px 10px;
        border-radius: 6px;
        background: var(--surface-2);
        border: 1px solid var(--line);
      }

      .call-title {
        font-size: 10px;
        font-weight: 650;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        color: var(--ink-muted);
        margin-bottom: 4px;
      }

      .call-code {
        font-size: 11px;
        color: var(--accent);
        display: block;
        word-break: break-all;
      }

      /* Citations */
      .citations-box {
        margin-top: 4px;
        padding: 8px 10px;
        border-radius: 6px;
        background: color-mix(in srgb, var(--good) 6%, var(--surface));
        border: 1px solid color-mix(in srgb, var(--good) 25%, transparent);
      }

      .cite-title {
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        color: var(--good);
        margin-bottom: 4px;
      }

      .cite-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .cite-item {
        font-size: 11.5px;
        color: var(--ink-2);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }

      .cite-metric {
        font-size: 10px;
        padding: 1px 6px;
        border-radius: 4px;
        background: var(--surface);
        border: 1px solid var(--line);
        color: var(--ink-muted);
      }

      /* Usage meta */
      .usage-meta {
        font-size: 10.5px;
        color: var(--ink-muted);
        display: flex;
        gap: 6px;
        align-items: center;
        margin-top: 2px;
      }

      .cost-accent {
        color: var(--accent);
        font-weight: 600;
      }

      /* Declined */
      .declined-box {
        margin-top: 6px;
        padding: 8px;
        border-radius: 6px;
        background: color-mix(in srgb, var(--warning) 8%, var(--surface));
        border: 1px solid color-mix(in srgb, var(--warning) 25%, transparent);
      }

      .declined-title {
        font-size: 10.5px;
        font-weight: 650;
        color: var(--warning);
        margin-bottom: 5px;
      }

      .known-metrics {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
      }

      .km-chip {
        font-size: 10.5px;
        padding: 2px 7px;
        border-radius: 4px;
        background: var(--surface);
        border: 1px solid var(--line);
        cursor: pointer;
        color: var(--ink-2);
      }

      .km-chip:hover {
        border-color: var(--accent);
        color: var(--accent);
      }

      /* Loading indicator */
      .loading-bubble {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        font-size: 12px;
        color: var(--ink-muted);
      }

      .dot-typing {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background-color: var(--accent);
        box-shadow: 12px 0 0 0 var(--accent), 24px 0 0 0 var(--accent);
        animation: dot-pulse 1.2s infinite ease-in-out;
        margin-right: 20px;
      }

      @keyframes dot-pulse {
        0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
        40% { transform: scale(1); opacity: 1; }
      }

      /* Input dock */
      .chat-input-dock {
        display: flex;
        gap: 10px;
        padding: 12px 16px;
        background: var(--surface);
        border-top: 1px solid var(--line);
      }

      .chat-input-dock input {
        flex: 1;
        font: inherit;
        font-size: 13.5px;
        padding: 10px 14px;
        border-radius: 8px;
        border: 1px solid var(--line-strong);
        background: var(--surface-2);
        color: var(--ink);
        outline: none;
        transition: border-color 0.15s;
      }

      .chat-input-dock input:focus {
        border-color: var(--accent);
      }

      .btn-send {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 10px 20px;
        border-radius: 8px;
        border: none;
        background: var(--accent);
        color: #fff;
        font-size: 13px;
        font-weight: 650;
        cursor: pointer;
        transition: filter 0.15s;
      }

      .btn-send:hover:not(:disabled) {
        filter: brightness(1.1);
      }

      .btn-send:disabled {
        opacity: 0.45;
        cursor: default;
      }

      .send-icon {
        font-size: 12px;
      }
    `,
  ],
})
export class ChatComponent implements OnInit, AfterViewChecked {
  private readonly api = inject(ApiService);
  private readonly glossary = inject(GlossaryService);

  @ViewChild('scrollContainer') private scrollContainer?: ElementRef;
  @ViewChild('inputBox') private inputBox?: ElementRef;

  question = '';
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  readonly messages = signal<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      text: 'Hello! I am your MoveInSync mobility analytics agent. Ask any question about fleet performance, on-time arrivals, cost, no-shows, driver/cab compliance, or specific vendors.',
      time: 'Just now',
    },
  ]);

  readonly samples = [
    'Why did on-time arrival drop in June?',
    'What was the cost per trip in July 2026?',
    'Which office had the worst OTA in June?',
    'What is the no-show rate for July?',
    'Tell me about Rohan Mikhailov Travel',
    'What is the vehicle cab non-compliance rate?',
  ];

  readonly num = num;
  readonly usd = usd;

  ngOnInit(): void {
    void this.glossary.load();
  }

  ngAfterViewChecked(): void {
    this.scrollToBottom();
  }

  private scrollToBottom(): void {
    if (this.scrollContainer) {
      try {
        this.scrollContainer.nativeElement.scrollTop = this.scrollContainer.nativeElement.scrollHeight;
      } catch {}
    }
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

  clearChat(): void {
    this.messages.set([
      {
        id: 'reset',
        role: 'assistant',
        text: 'Chat history cleared. How can I help you analyze the fleet data?',
        time: 'Just now',
      },
    ]);
  }

  private async send(): Promise<void> {
    const q = this.question.trim();
    if (!q || this.loading()) return;

    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMsg: ChatMessage = {
      id: 'user-' + Date.now(),
      role: 'user',
      text: q,
      time: timeStr,
    };

    this.messages.update((msgs) => [...msgs, userMsg]);
    this.question = '';
    this.loading.set(true);
    this.error.set(null);

    try {
      const priorUserMsgs = this.messages().slice(0, -1).filter((m) => m.role === 'user');
      const previousQuestion = priorUserMsgs.length ? priorUserMsgs[priorUserMsgs.length - 1].text : undefined;
      const res = await this.api.chat(q, undefined, previousQuestion);
      const agentMsg: ChatMessage = {
        id: 'agent-' + Date.now(),
        role: 'assistant',
        text: res.answer,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        response: res,
      };
      this.messages.update((msgs) => [...msgs, agentMsg]);
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : String(e);
      this.error.set(errMsg);
      this.messages.update((msgs) => [
        ...msgs,
        {
          id: 'err-' + Date.now(),
          role: 'assistant',
          text: 'Error connecting to analytics service: ' + errMsg,
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      this.loading.set(false);
      setTimeout(() => this.inputBox?.nativeElement.focus(), 50);
    }
  }
}
