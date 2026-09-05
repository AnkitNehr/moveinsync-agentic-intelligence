/**
 * Wire types — a one-to-one mirror of the Java records the API serialises.
 *
 * Every field that the backend can legitimately leave null is typed `| null`
 * rather than optional. That is deliberate: a null here is a *finding* (an
 * unacknowledged alert, an incomplete leg, a metric with no SLA written against
 * it), not an absence to be papered over. Typing them as nullable forces every
 * call site to decide what to render instead of silently printing "undefined".
 */

export interface Quality {
  coverage: number;
  confidence: string;
  caveats: string[];
}

export interface Trend {
  prior: number | null;
  delta: number | null;
  robustZ: number | null;
}

export interface Sla {
  target: number | null;
  delta: number | null;
  breached: boolean;
}

export interface Peer {
  cohortMedian: number | null;
  rank: string | null;
  percentile: number | null;
}

export interface Industry {
  benchmark: number | null;
  source: string | null;
}

export interface References {
  trend: Trend | null;
  sla: Sla | null;
  peer: Peer | null;
  industry: Industry | null;
}

export interface MetricObservation {
  metricId: string;
  grain: string;
  entity: string;
  period: string;
  value: number | null;
  sampleSize: number;
  references: References | null;
  severity: number;
  quality: Quality | null;
}

export interface Contribution {
  entity: string;
  rateEffect: number;
  mixEffect: number;
  total: number;
  shareBefore: number;
  shareAfter: number;
}

export interface Finding {
  id: string;
  metricId: string;
  dimension: string;
  entity: string;
  period: string;
  priorPeriod: string;
  current: number;
  prior: number;
  deltaPts: number;
  sampleSize: number;
  robustZ: number;
  score: number;
  observation: MetricObservation | null;
  contributions: Contribution[] | null;
}

export interface Evidence {
  claim: string;
  metricId: string | null;
  entity: string | null;
}

export interface Action {
  type: string;
  target: string;
  permitted: boolean;
  reason: string;
}

export interface Communication {
  id: string;
  incidentId: string;
  actionType: string;
  persona: string;
  channel: string;
  recipient: string;
  subject: string;
  body: string;
  status: string;
  blockedReason: string | null;
  createdAt: string;
}

export interface EscalateResponse {
  incident: Incident;
  action: Action;
  escalated: boolean;
}

export interface RecheckResponse {
  incident: Incident;
  escalations: Incident[];
  followUp: FollowUp | null;
}

export interface FollowUp {
  incidentId: string;
  metricId: string | null;
  dimension: string | null;
  entity: string | null;
  period: string | null;
  dueAt: string;
  status: string;
  note: string | null;
}

export interface PolicyDecision {
  ruleId: string;
  breached: boolean;
  consecutivePeriods: number;
  escalationPermitted: boolean;
  severityBand: string;
}

export interface Incident {
  id: string;
  title: string;
  whyNow: string;
  priority: number;
  severity: string;
  findingIds: string[];
  explanation: string;
  evidence: Evidence[] | null;
  recommendedActions: Action[] | null;
  policy: PolicyDecision | null;
  quality: Quality | null;
  detectedAt: string;
  followUpAt: string | null;
  status: string;
}

export interface RunSummary {
  runId: string;
  startedAt: string;
  trips: number;
  seriesEvaluated: number;
  candidates: number;
  incidents: number;
  promptTokens: number;
  completionTokens: number;
  estimatedCostUsd: number;
  wallClockMs: number;
  stageTimings: string[];
}

export interface StageTiming {
  stage: string;
  millis: number;
  promptTokens: number;
  completionTokens: number;
}

/** Live funnel snapshot from GET /api/runs/progress. Counts are null until that stage lands. */
export interface RunProgress {
  running: boolean;
  runId: string | null;
  startedAt: string | null;
  currentStage: string | null;
  completed: StageTiming[];
  trips: number | null;
  seriesEvaluated: number | null;
  findings: number | null;
  candidates: number | null;
  incidents: number | null;
}

export interface LatestRun {
  summary: RunSummary;
  incidents: Incident[];
  tiers: Record<string, string>;
  running: boolean;
}

export interface Health {
  status: string;
  datasetReady: boolean;
  rows: Record<string, number>;
  rowsRead: number;
  rowsKept: number;
  droppedRows: number;
  coverage: number;
  qualityFlags: Record<string, number>;
  caveats: string[];
  metrics: string[];
  llmAvailable: boolean;
  llmReason: string | null;
  stageTiers: Record<string, string>;
  nightlyEnabled: boolean;
  runInProgress: boolean;
  lastRunId: string | null;
  openIncidents: number;
  totalIncidents: number;
  checkedAt: string;
}

export interface DimensionView {
  dimension: string;
  explanatoryPower: number;
  concentration: number;
  dispersion: number;
  explainedDelta: number;
  entityCount: number;
  sampleSize: number;
  contributions: Contribution[];
}

export interface Reconciliation {
  actualDelta: number;
  explainedSum: number;
  error: number;
  tolerance: number;
  reconciles: boolean;
  note: string;
}

export interface AttributionView {
  metricId: string;
  period: string;
  priorPeriod: string;
  actualDelta: number;
  winner: DimensionView | null;
  ranked: DimensionView[];
  reconciliation: Reconciliation | null;
  note: string;
}

export interface ResolvedCall {
  tool: string;
  metricId: string;
  dimension: string;
  entity: string;
  period: string;
}

export interface Usage {
  promptTokens: number;
  completionTokens: number;
  calls: number;
  estimatedCostUsd: number;
}

export interface ChatResponse {
  answer: string;
  resolvedCall: ResolvedCall | null;
  citations: Evidence[] | null;
  usage: Usage | null;
  declined: boolean;
  tier: string;
  knownMetrics: string[] | null;
}

export interface Brief {
  period: string;
  persona: string;
  markdown: string;
  headline: string[];
  incidentIds: string[];
  tier: string;
  generatedAt: string;
}

export interface MetricSummary {
  id: string;
  label: string;
  description: string;
  version: number;
  unit: string;
  rateMetric: boolean;
  direction: string;
  sourceView: string;
  grains: string[];
  minSample: number;
  slaTarget: number | null;
  industryBenchmark: number | null;
  segmentBy: string | null;
  validSegments: string[] | null;
  periods: string[];
  caveats: string[];
}

/** The shape the backend's GlobalExceptionHandler returns on every error. */
export interface ApiError {
  error: string;
  message: string;
  path: string;
  timestamp: string;
}
