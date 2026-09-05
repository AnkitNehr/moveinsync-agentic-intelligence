import { Injectable, inject, signal } from '@angular/core';
import { ApiService } from './api.service';
import type { Glossary, GlossaryColumn, GlossaryMetric } from './models';

/**
 * Catalog labels plus data-dictionary column meanings. Loaded once; the API still
 * keys everything on snake_case ids.
 */
@Injectable({ providedIn: 'root' })
export class GlossaryService {
  private readonly api = inject(ApiService);
  readonly payload = signal<Glossary | null>(null);
  private pending: Promise<void> | null = null;

  async load(): Promise<void> {
    if (this.payload()) return;
    if (this.pending) return this.pending;
    this.pending = this.api
      .glossary()
      .then((g) => {
        this.payload.set(g);
      })
      .catch(() => {
        /* incident screens still work; ids remain as a fallback */
      })
      .finally(() => {
        this.pending = null;
      });
    return this.pending;
  }

  metric(id: string | null | undefined): GlossaryMetric | null {
    if (!id) return null;
    return this.payload()?.metrics.find((m) => m.id === id) ?? null;
  }

  column(id: string | null | undefined): GlossaryColumn | null {
    if (!id) return null;
    return this.payload()?.columns.find((c) => c.id === id) ?? null;
  }

  metricLabel(id: string | null | undefined): string {
    return this.metric(id)?.label ?? (id ? id.replaceAll('_', ' ') : '');
  }

  grainLabel(id: string | null | undefined): string {
    if (!id || id === 'global' || id === 'ALL') return 'fleet-wide';
    return this.column(id)?.label ?? id.replaceAll('_', ' ');
  }

  grainMeaning(id: string | null | undefined): string | null {
    return this.column(id)?.meaning ?? null;
  }
}
