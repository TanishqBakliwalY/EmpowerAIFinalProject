export type Usage = {
  input_tokens: number
  cached_tokens: number
  output_tokens: number
  reasoning_tokens: number
  requests: number
  tool_calls: number
  cost_usd: number
  cache_hit_pct: number
}

export type Step = {
  key: string
  label: string
  kind: 'agent' | 'code'
  job?: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  started_at?: number
  ended_at?: number
  seconds?: number
  summary?: string
  usage?: Usage
  rounds?: number
  detail?: string
}

export type TraceEvent = { t: number; agent: string; kind: string; text: string; data: unknown }

export type Finding = { kind: string; severity: string; message: string; snippet: string }

export type Feature = { name: string; description: string; priority: string; module_key: string | null }

export type Spec = {
  project_title: string
  client_name: string
  client_country: string
  industry: string
  summary: string
  project_type: string
  platforms: string[]
  features: Feature[]
  integrations: string[]
  non_functional: string[]
  compliance_flags: string[]
  constraints: {
    deadline: string | null
    deadline_date: string | null
    requested_start: string | null
    budget_text: string | null
    budget_max: number | null
    budget_currency: string | null
    preferred_stack: string[]
    languages: string[]
    other: string[]
  }
  existing_client: boolean
  client_history: string | null
  open_questions: string[]
  assumptions: string[]
  suspicious_content: string[]
}

export type Design = {
  feasibility: 'feasible' | 'feasible_with_conditions' | 'not_recommended'
  feasibility_reasons: string[]
  recommended_stack: { layer: string; technology: string; reason: string }[]
  work_packages: { name: string; module_key: string; complexity: string; priority: string; scope_notes: string }[]
  capability_gaps: string[]
  risks: { risk: string; impact: string; mitigation: string }[]
  reference_projects: string[]
}

export type EstimateLine = {
  work_package: string
  module_key: string
  complexity: string
  hours_by_role: Record<string, number>
  total_hours: number
  basis: string
  reference_projects: string[]
  benchmark_hours: number | null
  deviation_pct: number | null
}

export type Estimate = {
  lines: EstimateLine[]
  build_hours_by_role: Record<string, number>
  hours_by_role: Record<string, number>
  build_hours: number
  qa_topup_hours: number
  pm_hours: number
  lead_hours: number
  contingency_pct: number
  contingency_hours: number
  expected_hours: number
  total_hours: number
  low_hours: number
  high_hours: number
  risk_level: string
  historical_underestimate_pct: number | null
  warnings: string[]
}

export type Member = {
  emp_id: string
  name: string
  title: string
  role: string
  office: string
  allocation_pct: number
  free_pct: number
  conflict: string | null
}

export type Schedule = {
  team: Member[]
  start_date: string
  end_date: string
  total_weeks: number
  discovery_weeks: number
  build_weeks: number
  stabilization_weeks: number
  bottleneck_role: string | null
  role_weeks: Record<string, number>
  uncovered_roles: string[]
  gaps: string[]
  warnings: string[]
  meets_deadline: boolean | null
}

export type PriceOption = {
  model: 'fixed' | 'tm'
  label: string
  currency: string
  price: number
  blended_rate: number
  hours: number
  monthly_estimate: number | null
  milestones: { milestone: string; pct: number; amount: number }[]
  terms: string
}

export type Quote = {
  currency: string
  recommended_model: 'fixed' | 'tm'
  discount_pct: number
  options: PriceOption[]
  rate_card: Record<string, number>
  internal_cost: number
  margin_pct_fixed: number
  margin_pct_tm: number
  margin_floor_pct: number
  target_margin_pct: number
  needs_approval: boolean
  approval_reasons: string[]
  budget_fit: string | null
}

export type Phase1 = {
  packages: string[]
  later_packages: string[]
  hours: number
  weeks: number
  go_live: string
  fixed_price: number
  tm_price: number
  margin_pct_fixed: number
  budget_fit: string | null
  share_of_full_scope_pct: number
}

export type Issue = { severity: string; area: string; finding: string; recommendation: string; send_back_to: string }
export type Review = { verdict: 'approve' | 'revise' | 'escalate'; issues: Issue[]; strengths: string[]; go_no_go: string }
export type PricingDecision = { recommended_model: string; discount_pct: number; rationale: string[]; negotiation_notes: string[] }

export type Deal = {
  id: string
  demo?: boolean
  module: string
  status: 'queued' | 'running' | 'ready' | 'failed' | 'approved' | 'rejected' | 'changes_requested'
  created_at: string
  title: string
  model: string
  input: { brief: string; client_name: string; client_country: string; currency: string; desired_start: string; created_by?: string; via?: string }
  steps: Record<string, Step>
  trace: TraceEvent[]
  usage: Usage
  screen: { findings: Finding[]; injection_suspected?: boolean }
  revisions: number
  decision: { action: string; note: string; approver: string; at: string; manual_hours?: number | null; quality?: number | null; app_minutes?: number } | null
  error: string | null
  results: {
    spec?: Spec
    design?: Design
    estimate?: Estimate
    schedule?: Schedule
    quote?: Quote
    phase1?: Phase1 | null
    pricing_decision?: PricingDecision
    review?: Review
    reviews?: Review[]
    proposal_markdown?: string
    memo_markdown?: string
    leak_findings?: Finding[]
  }
}

export type DealRow = {
  id: string
  title: string
  status: Deal['status']
  created_at: string
  client_name: string
  currency: string
  price: number | null
  model: string | null
  margin_pct: number | null
  hours: number | null
  verdict: string | null
  cost_usd: number | null
  decision: string | null
  flags: number
  demo?: boolean
  created_by?: string
  via?: string
}

export type Sample = { id: string; label: string; client_name: string; client_country: string; currency: string; brief: string }

export type Meta = {
  app: string
  model: string
  api_key_present: boolean
  dataset: { name: string; as_of: string; synthetic: boolean; description: string; employees: number; past_projects: number }
  modules: { key: string; name: string; tagline: string; status: string; agents: string[] }[]
  prices_per_million_tokens_usd: { input_per_m: number; cached_input_per_m: number; output_per_m: number }
  limits: { requests_per_run: number; tool_calls_per_run: number; tokens_per_run: number; daily_budget_usd: number; max_brief_chars: number }
}

export type BoardPerson = {
  emp_id: string
  name: string
  title: string
  role: string
  level: string
  office: string
  skills: string[]
  weekly: number[]
  free_now_pct: number
  free_50_from: string | null
  assignments: { project: string; code: string; client: string; allocation_pct: number; from: string; to: string; kind: string }[]
}

export type Board = {
  as_of: string
  weeks: string[]
  week_ends: string[]
  people: BoardPerson[]
  roles: { role: string; label: string; headcount: number; free_fte_by_week: number[] }[]
  summary: { headcount: number; on_bench_now: number; avg_utilisation_now_pct: number }
}

export type StaffingRun = {
  id: string
  status: string
  input: { question: string }
  results: { answer?: { answer: string; people: { emp_id: string; name: string; title: string; free_pct: number; available_from: string | null; why: string }[]; caveats: string[] } }
  usage: Usage
  trace: TraceEvent[]
  screen?: { findings: Finding[] }
  error: string | null
}

export type UsageReport = {
  totals: { runs: number; input_tokens: number; cached_tokens: number; output_tokens: number; reasoning_tokens: number; cost_usd: number }
  by_agent: { module: string; agent: string; runs: number; input_tokens: number; cached_tokens: number; output_tokens: number; reasoning_tokens: number; requests: number; tool_calls: number; cost_usd: number }[]
  by_day: { day: string; runs: number; input_tokens: number; cached_tokens: number; output_tokens: number; cost_usd: number }[]
  spent_today_usd: number
  daily_budget_usd: number
  prices_per_million_tokens_usd: { input_per_m: number; cached_input_per_m: number; output_per_m: number }
  feedback?: {
    reviews: number
    avg_quality: number | null
    manual_hours_total: number
    app_hours_total: number
    hours_saved_total: number | null
    rows: { deal_id: string; title: string; approver: string; action: string; manual_hours: number | null; quality: number | null; app_minutes: number; note: string }[]
  }
}

export type SafetyEvent = { id: number; ts: string; run_id: string | null; kind: string; severity: string; message: string; detail: unknown }

export type Attachment = {
  id: string
  name: string
  kind: string
  pages: number
  chars: number
  truncated: boolean
  findings: Finding[]
  preview: string
  injection_suspected: boolean
  text?: string
}

export type ChatSummary = { id: string; title: string; created_at: string; updated_at: string }

export type ChatMeta = {
  attachments?: { id: string; name: string; pages: number; chars: number; injection_suspected: boolean }[]
  tools?: { name: string; args: unknown }[]
  usage?: Usage
  seconds?: number
  followups?: string[]
  started_deals?: string[]
  flagged?: Finding[]
  error?: string
}

export type ChatMessage = { id: number; role: 'user' | 'assistant'; content: string; created_at?: string; meta?: ChatMeta | null }
