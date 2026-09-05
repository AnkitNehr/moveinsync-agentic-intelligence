import { Injectable } from '@angular/core';
import type {
  ApiError,
  AttributionView,
  Brief,
  ChatResponse,
  Communication,
  EscalateResponse,
  FollowUp,
  Glossary,
  Health,
  Incident,
  LatestRun,
  MetricObservation,
  MetricSummary,
  RecheckResponse,
  RunProgress,
  RunSummary,
} from './models';

/** Thrown for any non-2xx response, carrying the backend's ApiError body when it sent one. */
export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body: ApiError | null,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

/**
 * Typed fetch wrappers over the platform API.
 *
 * Plain `fetch` on purpose — there is no state library and no HttpClient here.
 * Every method returns a Promise so components can `await` in an event handler
 * and keep their own loading flags, which is the whole of the state management
 * this console needs.
 *
 * The backend returns 404 for "no run has completed yet" and 503 for "the fact
 * store has no data". Those are meaningful states, not crashes, so callers are
 * expected to catch HttpError and render the reason rather than a blank pane.
 */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly base = '/api';

  // --- plumbing ----------------------------------------------------------

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.base}${path}`, {
        headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
        ...init,
      });
    } catch (cause) {
      // Network-level failure: the backend is almost certainly not running.
      throw new HttpError(
        0,
        'Cannot reach the API. Is the backend running (or is Docker Compose up)?',
        null,
      );
    }

    const text = await res.text();
    const parsed = text ? this.tryParse(text) : null;

    if (!res.ok) {
      const body = (parsed ?? null) as ApiError | null;
      throw new HttpError(
        res.status,
        body?.message ?? `${res.status} ${res.statusText}`,
        body,
      );
    }
    return parsed as T;
  }

  private tryParse(text: string): unknown {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  private async requestText(path: string): Promise<string> {
    const res = await fetch(`${this.base}${path}`);
    if (!res.ok) {
      throw new HttpError(res.status, `${res.status} ${res.statusText}`, null);
    }
    return res.text();
  }

  private query(params: Record<string, string | number | null | undefined>): string {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== null && v !== undefined && v !== '') q.set(k, String(v));
    }
    const s = q.toString();
    return s ? `?${s}` : '';
  }

  // --- endpoints ---------------------------------------------------------

  /** Platform health. Always 200 — a degraded platform still reports. */
  health(): Promise<Health> {
    return this.request<Health>('/health');
  }

  /** Executes one sense-reason-act pass. This is the demo button. */
  run(period?: string, priorPeriod?: string): Promise<RunSummary> {
    return this.request<RunSummary>('/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ period: period ?? null, priorPeriod: priorPeriod ?? null }),
    });
  }

  /** Live funnel. Always 200 — idle returns running:false rather than 404. */
  runProgress(): Promise<RunProgress> {
    return this.request<RunProgress>('/runs/progress');
  }

  /** The most recent run plus its incidents. 404 when nothing has run since boot. */
  latestRun(): Promise<LatestRun> {
    return this.request<LatestRun>('/runs/latest');
  }

  incidents(status?: string, limit = 0): Promise<Incident[]> {
    return this.request<Incident[]>(`/incidents${this.query({ status, limit })}`);
  }

  incident(id: string): Promise<Incident> {
    return this.request<Incident>(`/incidents/${encodeURIComponent(id)}`);
  }

  dismissIncident(id: string, reason: string): Promise<Incident> {
    return this.request<Incident>(`/incidents/${encodeURIComponent(id)}/dismiss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
  }

  notifyIncident(id: string): Promise<Communication> {
    return this.request<Communication>(`/incidents/${encodeURIComponent(id)}/notify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
  }

  /**
   * 200 when permitted, 403 when policy refuses. The 403 body is the same
   * EscalateResponse with {@code escalated: false} — not an ApiError — so this
   * does not go through {@link request}.
   */
  async escalateIncident(id: string, note?: string): Promise<{ status: number; body: EscalateResponse }> {
    const res = await fetch(`${this.base}/incidents/${encodeURIComponent(id)}/escalate`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ note: note ?? '' }),
    });
    const text = await res.text();
    const parsed = text ? (this.tryParse(text) as EscalateResponse) : null;
    if (!parsed) {
      throw new HttpError(res.status, `${res.status} ${res.statusText}`, null);
    }
    return { status: res.status, body: parsed };
  }

  recheckIncident(id: string, period?: string): Promise<RecheckResponse> {
    return this.request<RecheckResponse>(`/incidents/${encodeURIComponent(id)}/recheck`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ period: period ?? null }),
    });
  }

  outbox(incidentId?: string): Promise<Communication[]> {
    return this.request<Communication[]>(`/outbox${this.query({ incidentId })}`);
  }

  outboxItem(id: string): Promise<Communication> {
    return this.request<Communication>(`/outbox/${encodeURIComponent(id)}`);
  }

  sendOutbox(id: string): Promise<Communication> {
    return this.request<Communication>(`/outbox/${encodeURIComponent(id)}/send`, {
      method: 'POST',
    });
  }

  followUps(): Promise<FollowUp[]> {
    return this.request<FollowUp[]>('/followups');
  }

  /** Ranked decomposition across every dimension the metric declares. */
  attribution(metric: string, period?: string, prior?: string): Promise<AttributionView> {
    return this.request<AttributionView>(
      `/attribution${this.query({ metric, period, prior })}`,
    );
  }

  chat(question: string, period?: string): Promise<ChatResponse> {
    return this.request<ChatResponse>('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, period: period ?? null }),
    });
  }

  brief(period?: string, persona?: string): Promise<Brief> {
    return this.request<Brief>(`/reports/brief${this.query({ period, persona })}`);
  }

  briefMarkdown(period?: string, persona?: string): Promise<string> {
    return this.requestText(
      `/reports/brief${this.query({ period, persona, format: 'markdown' })}`,
    );
  }

  personas(): Promise<string[]> {
    return this.request<string[]>('/reports/personas');
  }

  metricCatalog(): Promise<MetricSummary[]> {
    return this.request<MetricSummary[]>('/metrics');
  }

  glossary(): Promise<Glossary> {
    return this.request<Glossary>('/glossary');
  }

  /** One fully contextualised observation, with trend / SLA / peer / industry frames. */
  metric(
    metricId: string,
    period?: string,
    dimension?: string,
    entity?: string,
  ): Promise<MetricObservation> {
    return this.request<MetricObservation>(
      `/metrics/${encodeURIComponent(metricId)}${this.query({ period, dimension, entity })}`,
    );
  }

  metricPeriods(metricId: string): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>(
      `/metrics/${encodeURIComponent(metricId)}/periods`,
    );
  }
}
