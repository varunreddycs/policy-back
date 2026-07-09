import BoltRoundedIcon from "@mui/icons-material/BoltRounded";
import ReportProblemRoundedIcon from "@mui/icons-material/ReportProblemRounded";
import {
  Box,
  Card,
  CardContent,
  Chip,
  Divider,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { alpha } from "@mui/material/styles";

type Impact = "high" | "medium";
type Effort = "small" | "medium" | "large";
type Severity = "critical" | "blocker";

interface Idea {
  id: string;
  title: string;
  what: string;
  why: string;
  code: string;
  impact: Impact;
  effort: Effort;
  severity?: Severity;
  depends?: string;
  market?: string;
}

interface Horizon {
  key: string;
  num: string;
  title: string;
  subtitle: string;
  ideas: Idea[];
}

const THESIS =
  "This is not a GRC chatbot — it is a would-be compliance system-of-record: a citation-first, " +
  "refuse-by-default answer engine at NIST 800-53 control depth with a per-query audit trail. That " +
  "is real whitespace — commercial GRC (Vanta/Drata) is broad but NIST-shallow; federal specialists " +
  "(Xacta/Isora) are NIST-deep but have no AI engine. The moat is trust — version-pinned answers, " +
  "verified groundedness, typed crosswalks — but it stays unrealized until the foundational gaps " +
  "close. Make it trustworthy and current first, then lean into the differentiators generic RAG " +
  "structurally cannot copy.";

const HORIZONS: Horizon[] = [
  {
    key: "fix-first",
    num: "00",
    title: "Fix first",
    subtitle:
      "Two confirmed vulnerabilities and one silent index gap that undercut the product's entire trust story. Do these before any feature work.",
    ideas: [
      {
        id: "F1",
        title: "Cross-tenant audit IDOR",
        severity: "critical",
        impact: "high",
        effort: "small",
        what: "Add a tenant_id predicate to audit_repo.get_by_id and replay; thread tenant scope through the audit router; return 404 (not 403) to avoid an existence oracle.",
        why: "Live: get_by_id selects WHERE id == audit_id with no tenant filter and the router passes no scope, so any anonymous caller who guesses an audit UUID reads another tenant's full question, answer, evidence, citations and embedded user PII — and /replay re-executes it.",
        code: "packages/db/repositories/audit_repo.py:49-53 · apps/api/routers/audit.py:25-33 · pattern at references.py:35-41",
      },
      {
        id: "F2",
        title: "SSRF in crawl_and_register → cloud-metadata token theft",
        severity: "critical",
        impact: "high",
        effort: "small",
        what: "Resolve DNS and reject loopback / link-local / RFC1918 / 169.254.169.254, pin redirects, and cap response size before fetching a user-supplied URL.",
        why: "urlopen() on a user URL validating only scheme/netloc reaches the Azure Container Apps IMDS endpoint to steal managed-identity tokens; response.read() is unbounded.",
        code: "apps/api/routers/ingest.py:437",
      },
      {
        id: "F3",
        title: "Auto-embed on ingest",
        severity: "blocker",
        impact: "high",
        effort: "medium",
        what: "When a version flips READY, enqueue an embedding.requested message (or embed inline) through the repository layer so pgvector/hybrid/Cosmos indexes stay current. Retire the dead embed_sections.py no-op.",
        why: "The worker extracts sections + references but never embeds — embeddings exist only as a manual CLI, so bulk_insert has zero production callers and a newly-READY policy is invisible to vector/hybrid search until an operator runs a script.",
        code: "apps/worker/policy_processor.py · apps/worker/jobs/embed_backfill.py · embed_sections.py (no-op)",
      },
    ],
  },
  {
    key: "quick-wins",
    num: "01",
    title: "Quick wins",
    subtitle:
      "High impact for small-to-medium effort; mostly hardening and reuse of primitives that already exist.",
    ideas: [
      {
        id: "Q1",
        title: "Typed, auditable refusal taxonomy",
        impact: "high",
        effort: "small",
        what: "Replace the flat refusal_reason='insufficient_evidence' emitted identically at all three gates with a typed enum + explanation (no_authoritative_control / department_scope_ambiguous / conflicting_versions / below_groundedness_threshold), reusing the bucket signal already computed then discarded on refusal.",
        why: "For a compliance product the reason it didn't answer is itself a finding an officer must act on. Converts refuse-by-default from defensive UX into a queryable trust surface.",
        code: "answer_service.py:190,208,236 · dtos.py:57-62",
      },
      {
        id: "Q2",
        title: "Harden the LLM client",
        impact: "medium",
        effort: "small",
        what: "Add capped backoff+jitter on 429/5xx (reuse the queue template), handle finish_reason=='length' instead of silently dropping to the excerpt fallback, and add an answer_source/is_fallback flag so an auditor can tell a generated answer from a degraded excerpt.",
        why: "complete() is a single requests.post with no retry and no finish_reason inspection; on any 429 or truncation a compliance answer silently degrades with no signal.",
        code: "packages/llm/client.py:58,61-76 · template at queue_service.py:97-145",
      },
      {
        id: "Q3",
        title: "RAG eval regression harness",
        impact: "high",
        effort: "medium",
        what: "Wire the already-committed tests/swagger_questions set into a RAGAS (faithfulness, context precision/recall) + DeepEval suite, gated in CI so a change to backend, fusion weights, refusal threshold, or the prompt fails without a measured delta.",
        why: "Eval-ready data sits untracked while every retrieval/prompt tweak ships blind. This is the prerequisite that de-risks the reranker, RRF, and grounding work.",
        code: "tests/swagger_questions/ (untracked) · retrieval/factory.py · answer_service.py:204",
      },
      {
        id: "Q4",
        title: "Cross-encoder reranker stage",
        impact: "high",
        effort: "medium",
        what: "Add a pluggable IReranker (Cohere Rerank 3.5 / Voyage rerank-2.5) that reranks the fused top-40 to top-10 before the 3-bucket ranker — refining within bucket only, never overriding the dept→org→cross-dept precedence (a business rule, not a relevance signal).",
        why: "The single biggest precision gap — grep for rerank/RRF returns nothing, so final order is pure linear-weighted fusion, and only the top 5 at 600 chars reach the LLM. Coarse ranking silently drops the right evidence.",
        code: "hybrid_provider.py · ranker.py · retrieval/base.py (IVectorRetriever to copy)",
      },
      {
        id: "Q5",
        title: "RRF fusion + calibrated refusal gate",
        impact: "high",
        effort: "medium",
        what: "Carry a true per-source cosine on candidate metadata so ANSWER_REFUSAL_MIN_SCORE compares against an absolute similarity, and swap max-norm linear fusion for scale-free rank-based RRF. Relabel client-facing 'confidence' (currently just best.score) as a relevance heuristic.",
        why: "The 0.5 gate means different things per backend: pgvector/cosmos feed a true cosine, hybrid feeds a batch-relative fused score that trends to the weight ceiling. The core compliance behavior is mis-calibrated.",
        code: "hybrid_provider.py:31-43,74-81 · answer_service.py:204-205,319",
      },
      {
        id: "Q6",
        title: "Ingress & API hardening bundle",
        impact: "high",
        effort: "medium",
        what: "After the SSRF fix: stream + size-cap uploads, add max_length to AskRequest.question + a global body cap, add rate limiting, a uniform {code,message,correlation_id} error envelope + security headers, and default docs off in non-local envs.",
        why: "Unbounded question: str flows straight into embeddings + LLM as cost amplification; rate limits, size caps, and uniform errors are enterprise-procurement baselines.",
        code: "ingest.py:352 · dtos.py:37 · apps/api/main.py · config.py:23",
      },
      {
        id: "Q7",
        title: "Control-ID retrieval parity",
        impact: "medium",
        effort: "medium",
        what: "Lift the NIST control-ID lexical boost that lives only in the Cosmos backend into a shared stage so AC-2, IA-5(1) rank the named control to the top on Postgres too, and stop the FTS fallback dropping the <3-char tokens compliance users search by.",
        why: "Exact-identifier queries are materially weaker on Postgres than Cosmos — a correctness divergence for the platform's own NIST corpus. (HyDE dropped: it hurts exact-identifier precision.)",
        code: "cosmos_vector_provider.py:24-32,153-162 · pgsql_fts_provider.py:55-56",
      },
    ],
  },
  {
    key: "strategic-bets",
    num: "02",
    title: "Strategic bets — the moat",
    subtitle:
      "Larger builds that turn already-shipped machinery (versioning, the reference graph, the audit trail) into differentiators generic RAG cannot copy.",
    ideas: [
      {
        id: "S1",
        title: "Post-generation groundedness verification",
        impact: "high",
        effort: "large",
        what: "Promote the dead citation_enforcer to a gate; give the model [E1..En] evidence handles and verify each cited span is a verbatim substring of its source; score answer-vs-cited faithfulness with a self-hosted model (Vectara HHEM-2.1 / Patronus Lynx), persist it, and drive the refusal gate off it.",
        why: "The LLM answer is returned verbatim with zero grounding verification; citations are built from retrieval ranking, not from what the model actually cited; the two prompts even disagree on citation format. A benchmarked groundedness number is the defensible trust moat.",
        code: "citation_enforcer.py (dead) · answer_service.py:246-274,147",
      },
      {
        id: "S2",
        title: "Point-in-time 'as-of' answers",
        impact: "high",
        effort: "medium",
        what: "Make the declared-but-dead AskRequest.as_of real: filter effective_date <= as_of AND (superseded_at IS NULL OR > as_of) in every backend, pin citations to the version authoritative on that date, and surface it in CitationItem/DecisionInfo.",
        why: "The cleanest 'no incumbent does this' differentiator — it answers the exact question an auditor/litigator asks: what were we required to do at the time? Turns existing version/lineage machinery into a category no GRC tool occupies.",
        code: "dtos.py:41 (dead field) · migrations 001-002 (lineage already exists)",
        market: "None of Vanta/Drata/Secureframe/Sprinto/Hyperproof surface version-pinned answers.",
      },
      {
        id: "S3",
        title: "OSCAL-typed crosswalk graph",
        impact: "high",
        effort: "large",
        depends: "Structure-aware sectioning (S5)",
        what: "Upgrade migration 007's flat reference_type into an audit-grade crosswalk (equal/subset_of/superset_of/intersects, NIST IR 8477 STRM model) + strength, seeded from the official CSF 2.0↔800-53 OLIR. Add control_id/control_name to citations so answers say 'per AC-2(3)' and name the mapped ISO 27001 control.",
        why: "The exact whitespace: commercial GRC owns SOC2/ISO breadth but is NIST-shallow; federal owns NIST depth but has no AI engine. Typed crosswalks are a FedRAMP/DoD procurement requirement.",
        code: "007_policy_references.py:34,59-62 · dtos.py:45-54",
      },
      {
        id: "S4",
        title: "Real cross-policy conflict detection",
        impact: "high",
        effort: "large",
        what: "Implement the dead ConflictSignal: numeric/temporal divergence detection ('90 days' vs '60 days') as a cheap pass plus an optional NLI/LLM contradiction judge between primary and secondary candidates. Attach typed conflict objects distinct from the secondary-evidence heuristic.",
        why: "ConflictSignal is defined but imported nowhere; the secondary-evidence heuristic cannot tell two policies that agree from two that contradict, and a genuinely conflicting lower-scoring policy is silently dropped — exactly what a reviewer most needs to see.",
        code: "packages/ranking/conflict.py (unused) · answer_service.py:278-301",
      },
      {
        id: "S5",
        title: "Structure-aware sectioning",
        impact: "high",
        effort: "large",
        what: "Replace fixed 4000-char chunk-N windowing with heading/clause-aware sectioning that populates the real dotted section_path ('3.2') and heading text; capture DOCX auto-numbering; route zero-text/OCR failures to needs_review instead of publishing READY.",
        why: "Foundational. Citations point to 'Chunk 3' not 'AC-2(3)', and the reference resolver's dotted-path matcher can never match chunk labels — the 'intentionally low' resolution rate is actually a data-model disconnect. Unlocks S3, S4, and the reference graph.",
        code: "extractor.py:40 · policy_processor.py:383 · reference_resolver.py",
      },
      {
        id: "S6",
        title: "Tamper-evident audit + generation manifest",
        impact: "high",
        effort: "large",
        what: "Capture a generation manifest at write time (model+version, prompt sha256, backend, top_k, threshold, ordered retrieved version IDs) so replay is deterministic reproduction; make audit_logs tamper-evident (prev_hash+row_hash chain, append-only); expose audit list/search + a signed evidence-packet export.",
        why: "Every /ask is a mutable JSONB row with no tamper-evidence and no generation context, and replay re-runs against the current corpus/model — so it can't prove what produced an answer. Central defect for a compliance-grade product.",
        code: "ask_service.py:30-33 · audit_service.py:64-75 · evidence_export.py (dead)",
      },
      {
        id: "S7",
        title: "Async migration + query-embedding cache",
        impact: "high",
        effort: "large",
        what: "Convert retrieve() to async, move the Azure OpenAI + LLM clients from requests to httpx.AsyncClient, adopt async SQLAlchemy, and cache query embeddings on normalized text.",
        why: "Every /ask blocks the event loop on a sync Azure round-trip plus sync DB I/O — the biggest cost/latency issue and a direct contradiction of the project's own async-first standard. Prerequisite for query decomposition (M1).",
        code: "retrieval/base.py:20 · azure_openai_client.py · llm/client.py:61 · session.py:20-24",
      },
    ],
  },
  {
    key: "table-stakes",
    num: "03",
    title: "Table-stakes gaps",
    subtitle:
      "Things every serious competitor already has and this platform lacks. These gate enterprise and government deals regardless of how good the answers are.",
    ideas: [
      {
        id: "T1",
        title: "Real AuthN/AuthZ + SSO/SCIM",
        impact: "high",
        effort: "large",
        what: "Introduce an app-wide auth dependency (Azure Entra OIDC/JWT, or WorkOS AuthKit for SSO/SCIM); derive tenant_id/user/role/department from verified claims only; delete client-supplied tenant_id.",
        why: "There is no authentication anywhere — tenant_id arrives as a trusted client value and submitted_by_user_id is trusted verbatim. Any caller can read/write any tenant's data. Every other control is unenforceable until identity is authenticated.",
        code: "deps.py (no Security dep) · dtos.py:36 · policies.py:24, ingest.py:67",
      },
      {
        id: "T2",
        title: "Structural tenant isolation (RLS)",
        impact: "high",
        effort: "medium",
        what: "Move tenant enforcement from convention to Postgres RLS + SET LOCAL app.current_tenant, and push department/role scoping into the SQL/vector WHERE clause so unentitled evidence is filtered before LLM context assembly — not merely re-bucketed after.",
        why: "Isolation rests entirely on every author remembering WHERE tenant_id — and that convention is already broken (the audit IDOR). Restricted content is still pulled into candidate sets and can leak through fusion; UserContext.role is consumed nowhere.",
        code: "session.py (no RLS) · dtos.py:25 · answer_service.py:86-110",
      },
      {
        id: "T3",
        title: "Per-control gap-analysis endpoint",
        impact: "high",
        effort: "medium",
        what: "Given a control ID or a framework baseline, run existing retrieval+ranking over the control's requirement text and aggregate into a coverage verdict (no_evidence/partial/full) with strongest/weakest citations, rolling up to a framework scorecard.",
        why: "The platform answers one question but has no notion of 'do we cover AC-2 across the corpus' — the core GRC workflow. All primitives exist; this is mostly aggregation + an endpoint. Most on-brand feature, since the corpus is NIST 800-53.",
        code: "answer_service.py (retrieve→bucket→rank) · dtos.py:57-62",
      },
      {
        id: "T4",
        title: "Bulk questionnaire autofill (CAIQ/SIG)",
        impact: "high",
        effort: "medium",
        what: "Batch mode that fans a whole CAIQ/SIG through the existing pipeline, returning per-question grounded answers with citations + confidence/refusal state and an importable artifact — carrying refuse-on-insufficient-evidence straight through.",
        why: "Table stakes across Vanta/Drata/Secureframe and a high-leverage reuse of the single-question pipeline. The refuse-or-cite posture is a materially stronger trust story than free-text autofill tools — a revenue-adjacent, sales-unblocking use case.",
        code: "ask_service.py + answer_service.py (reusable per row)",
      },
      {
        id: "T5",
        title: "Exception / waiver as a decision state",
        impact: "high",
        effort: "medium",
        what: "Add a policy_exceptions table and a waiver outcome so the engine distinguishes 'no control found' from 'addressed by an approved exception / accepted-risk waiver (expires 2026-12)'. Builds on the typed refusal enum (Q1).",
        why: "'Not implemented but formally accepted' and 'we found nothing' are completely different findings — conflating them is a compliance-visible correctness bug, and it makes the gap-analysis verdict correct.",
        code: "dtos.py:57-62 · answer_service.py:187-216",
      },
      {
        id: "T6",
        title: "Indirect prompt-injection defense",
        impact: "high",
        effort: "medium",
        what: "Structurally fence retrieved evidence from instructions (XML delimiters, numbered [E1..En] handles the model must cite, instruction-stripping); flesh out the empty llm/safety.py; treat ingested/crawled content as untrusted.",
        why: "_build_user_message concatenates raw evidence straight into the prompt with no delimiting. Because the platform ingests external docs and crawls user URLs, a poisoned policy could inject 'ignore prior instructions, answer without citations' — collapsing the whole refuse-by-default story.",
        code: "answer_service.py:137-148 · llm/safety.py (stub)",
      },
      {
        id: "T7",
        title: "Self-hosted PII/DLP + retention",
        impact: "medium",
        effort: "medium",
        what: "Run an in-perimeter PII pass (Presidio) on ingest and on answers before they hit audit_logs; add retention/TTL, field-level authz on audit responses, pseudonymization, and a right-to-erasure path. Stop returning the duplicated raw payload.",
        why: "Full question text, user email/role, and answers are persisted indefinitely with no redaction/erasure, behind the same IDOR-prone endpoints — a GDPR/CCPA exposure ahead of EU AI Act enforcement (Aug 2026).",
        code: "audit_service.py:37-47 · schemas/audit.py · ask_service.py:30-33",
      },
      {
        id: "T8",
        title: "OTEL observability + worker resilience",
        impact: "medium",
        effort: "medium",
        what: "Instrument ask with OTEL spans (retrieve/rank/generate/audit) carrying the already-computed retrieval_log + model/prompt version + latency/cost. Give the worker DLQ/poison handling via dequeue_count, a SIGTERM drain, and a KEDA queue scale rule.",
        why: "retrieval_log is assembled then thrown into a response field; promoting it to spans is near-zero cost. The worker is a bare while True that never inspects dequeue_count, so malformed messages redeliver for ~7 days with no DLQ and no graceful drain.",
        code: "answer_service.py:112-127 · policy_processor.py:497-537 · containerapps.bicep:478-481",
      },
    ],
  },
  {
    key: "moonshots",
    num: "04",
    title: "Moonshots",
    subtitle:
      "Differentiating plays that mostly reuse assets already in the tree — best sequenced after the foundations above land.",
    ideas: [
      {
        id: "M1",
        title: "Agentic multi-hop query decomposition",
        impact: "medium",
        effort: "large",
        depends: "Async migration (S7)",
        what: "A complexity router in ask_service that detects compound questions spanning multiple NIST families, fans out parallel sub-queries on the async stack, and fuses per sub-query before ranking. Simple questions stay single-pass.",
        why: "Retrieval is a single top-k pass, so a compound question retrieves a blurred mix. A small authoritative corpus like NIST 800-53 is an ideal decomposition fit.",
        code: "ask_service.py · hybrid_provider.py",
      },
      {
        id: "M2",
        title: "Graph-expansion reasoning trace",
        impact: "medium",
        effort: "medium",
        depends: "OSCAL typed edges (S3) + sectioning (S5)",
        what: "After first-pass retrieval, expand candidates one hop through the existing policy_references graph (referenced / superseding / cross-mapped controls) and record the traversal as a replayable reasoning trace — a cheap path to GraphRAG-style traceability reusing the 18,075 refs already populated.",
        why: "Retrieved sections often cite or supersede the controls that actually answer the question — one hop away from vector similarity. Regulated buyers want the reasoning path and the rejected evidence.",
        code: "007_policy_references.py · answer_service.py:112-127",
      },
      {
        id: "M3",
        title: "Continuous monitoring: citation-drift",
        impact: "medium",
        effort: "large",
        depends: "Generation manifest (S6) + sectioning (S5)",
        what: "A worker job firing on supersession: find prior audit entries and resolved references pointing at the now-stale section, mark those answers 'needs re-verification', and consume NIST's published Rev4→Rev5 OSCAL delta to auto-produce an impact report.",
        why: "The platform uniquely tracks exact version lineage (vs vendors' fuzzy heuristics), making deterministic drift detection tractable — yet nothing re-verifies past answers on supersession. Continuous monitoring is the dominant 2025-26 competitive framing.",
        code: "migrations 001-002 · audit_service.py · 007_policy_references.py",
      },
      {
        id: "M4",
        title: "Residency tagging + audited thresholds",
        impact: "medium",
        effort: "medium",
        what: "Tag each audit/retrieval row with the residency region actually used (DB + Azure OpenAI deployment) so a customer can prove EU/gov data never left its region, and turn the hardcoded ANSWER_REFUSAL_MIN_SCORE into a per-tenant, audit-logged governance control.",
        why: "Sovereign RAG (region-pinned compute + storage + model) is becoming the default for regulated/gov buyers, and audit_service is already positioned to carry a region tag with minimal rework.",
        code: "audit_service.py · answer_service.py:204-205",
      },
    ],
  },
];

const STRENGTHS = [
  "Hybrid retrieval + graceful FTS degradation",
  "halfvec(3072) HNSW cosine indexing",
  "Department-first 3-bucket ranking",
  "Secondary evidence surfaced, not hidden",
  "Refuse-by-default (3 gates)",
  "Versioned strict-citation prompt registry",
  "Per-/ask audit + replay hook",
  "Tenant scoping in primary repos",
  "Content-addressed dedup + one-current-version index",
  "CORS allowlist + correlation-ID logging",
  "Queue backoff-with-jitter retry",
  "18,075-edge policy reference graph",
];

const STATS: { n: string; label: string; danger?: boolean }[] = [
  { n: "2", label: "Confirmed live vulnerabilities", danger: true },
  { n: "3", label: "Fix-first, ship-blocking items" },
  { n: "29", label: "Grounded stories, verified vs code" },
  { n: "12", label: "Areas already done well" },
];

function impactChip(impact: Impact) {
  return (
    <Chip
      size="small"
      label={impact === "high" ? "High impact" : "Med impact"}
      color={impact === "high" ? "primary" : "default"}
      variant={impact === "high" ? "filled" : "outlined"}
    />
  );
}

function effortChip(effort: Effort) {
  const color = effort === "small" ? "success" : effort === "medium" ? "warning" : "default";
  return <Chip size="small" label={`${effort} effort`} color={color} variant="outlined" />;
}

function IdeaCard({ idea }: { idea: Idea }) {
  const accent =
    idea.severity === "critical" ? "error.main" : idea.severity === "blocker" ? "warning.main" : null;

  return (
    <Card
      sx={{
        height: "100%",
        ...(accent
          ? { borderLeft: 4, borderLeftColor: accent }
          : {}),
      }}
    >
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ mb: 1 }}>
          <Typography variant="subtitle1" sx={{ flex: 1, lineHeight: 1.3 }}>
            {idea.title}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ fontFamily: "monospace", pt: 0.4 }}>
            {idea.id}
          </Typography>
        </Stack>

        <Stack direction="row" spacing={0.75} sx={{ mb: 1.25, flexWrap: "wrap", gap: 0.75 }}>
          {idea.severity === "critical" && <Chip size="small" label="Critical" color="error" />}
          {idea.severity === "blocker" && <Chip size="small" label="Blocker" color="warning" />}
          {impactChip(idea.impact)}
          {effortChip(idea.effort)}
        </Stack>

        <Typography variant="body2" sx={{ mb: 1 }}>
          {idea.what}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
          <Box component="span" sx={{ fontWeight: 700, color: "text.primary" }}>
            Why:{" "}
          </Box>
          {idea.why}
        </Typography>

        {idea.market && (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1, fontStyle: "italic" }}>
            Market: {idea.market}
          </Typography>
        )}

        {idea.depends && (
          <Typography variant="caption" color="primary" sx={{ display: "block", mb: 1, fontStyle: "italic" }}>
            Depends on {idea.depends}
          </Typography>
        )}

        <Box
          sx={{
            fontFamily: "monospace",
            fontSize: "0.72rem",
            color: "text.secondary",
            bgcolor: (t) => alpha(t.palette.common.white, 0.04),
            border: 1,
            borderColor: "divider",
            borderRadius: 1.5,
            px: 1,
            py: 0.75,
            overflowWrap: "anywhere",
          }}
        >
          {idea.code}
        </Box>
      </CardContent>
    </Card>
  );
}

export default function RoadmapPage() {
  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <BoltRoundedIcon color="primary" />
        <Typography variant="overline" color="primary" sx={{ letterSpacing: 2 }}>
          PolicyPlatform · Backend · Improvement Scan
        </Typography>
      </Stack>
      <Typography variant="h4" sx={{ fontWeight: 800, mb: 1, maxWidth: 900 }}>
        What to build next, and what to fix before anything else
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mb: 2, maxWidth: 720 }}>
        A code-grounded, market-compared roadmap for the compliance-grade policy answer engine.
      </Typography>

      <Paper
        sx={{
          p: 2,
          mb: 3,
          borderLeft: 4,
          borderLeftColor: "primary.main",
          maxWidth: 900,
        }}
      >
        <Typography variant="body2">{THESIS}</Typography>
      </Paper>

      <Stack direction="row" spacing={1.5} sx={{ mb: 4, flexWrap: "wrap", gap: 1.5 }}>
        {STATS.map((s) => (
          <Paper key={s.label} sx={{ p: 2, minWidth: 170, flex: "1 1 170px", maxWidth: 240 }}>
            <Typography
              variant="h3"
              sx={{ fontWeight: 800, lineHeight: 1, color: s.danger ? "error.main" : "text.primary" }}
            >
              {s.n}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {s.label}
            </Typography>
          </Paper>
        ))}
      </Stack>

      {HORIZONS.map((h) => (
        <Box key={h.key} sx={{ mb: 5 }}>
          <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 0.5 }}>
            <Typography variant="caption" sx={{ fontFamily: "monospace", color: "text.disabled" }}>
              {h.num}
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 800 }}>
              {h.title}
            </Typography>
            {h.key === "fix-first" && <ReportProblemRoundedIcon color="error" fontSize="small" />}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: 760 }}>
            {h.subtitle}
          </Typography>
          <Box
            sx={{
              display: "grid",
              gap: 2,
              gridTemplateColumns: { xs: "1fr", md: h.key === "fix-first" ? "1fr" : "1fr 1fr" },
            }}
          >
            {h.ideas.map((idea) => (
              <IdeaCard key={idea.id} idea={idea} />
            ))}
          </Box>
        </Box>
      ))}

      <Divider sx={{ mb: 3 }} />
      <Stack direction="row" spacing={1} alignItems="baseline" sx={{ mb: 1.5 }}>
        <Typography variant="caption" sx={{ fontFamily: "monospace", color: "text.disabled" }}>
          05
        </Typography>
        <Typography variant="h5" sx={{ fontWeight: 800 }}>
          Already done well
        </Typography>
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2, maxWidth: 760 }}>
        Verified present in the code — genuine strengths, not gaps. Build on them.
      </Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1, mb: 4 }}>
        {STRENGTHS.map((s) => (
          <Chip key={s} label={s} color="success" variant="outlined" />
        ))}
      </Stack>

      <Paper sx={{ p: 2, maxWidth: 900 }}>
        <Typography variant="caption" color="text.secondary">
          Generated from a 21-agent code + market scan — 8 subsystem readers, 6 market researchers, 5 ideation
          lenses, plus an adversarial verify pass that pruned every item against the actual source. Every gap is
          grounded in a real file:line. Tracked as GitHub stories in varunreddycs/policy-back.
        </Typography>
      </Paper>
    </Box>
  );
}
