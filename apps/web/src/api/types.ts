export type DepartmentValue = string;

export interface AskRequest {
  tenant_id: string;
  question: string;
  mode: "strict";
  user: {
    tenant_id: string;
    email: string;
    role: string;
    department: string;
  };
  scope: {
    only_current: boolean;
  };
}

export interface EvidenceMetadata {
  section_path: string;
  title: string;
  policy_name?: string | null;
  public_url?: string | null;
  section_index: number;
  retriever: string;
  is_current: boolean;
  effective_date: string | null;
  authority_level: number;
  department_scope: string;
  policy_type: string | null;
  user_department: string;
}

export interface EvidenceItem {
  policy_id: string;
  policy_version_id: string;
  section_id: string;
  text: string;
  score: number;
  source: string;
  metadata: EvidenceMetadata;
}

export interface AskResponse {
  answer: string;
  audit_id: string;
  citations: string[];
  citation_items?: CitationItem[];
  decision?: DecisionInfo | null;
  secondary_evidence?: SecondaryEvidenceItem[];
  /** Relevance heuristic from retrieval — NOT a calibrated correctness probability. */
  confidence: number | null;
  /** Absolute similarity the refusal gate evaluated; comparable across backends. */
  grounding_score?: number | null;
  refusal_reason: RefusalCode | null;
  refusal?: RefusalInfo | null;
  answer_source?: AnswerSource;
  is_fallback?: boolean;
  llm_error?: string | null;
  grounding?: GroundingInfo | null;
  evidence: EvidenceItem[];
  created_at: string;
}

export type AnswerSource = "llm" | "excerpt_fallback" | "refusal";

export interface GroundingInfo {
  verified: boolean;
  enforced: boolean;
  faithfulness_score: number | null;
  faithfulness_backend: string | null;
  threshold: number | null;
  cited_handles: string[];
  unknown_handles: string[];
  verified_citations: number;
  unverified_citations: number;
  citation_density: number | null;
  supported_claims: number;
  total_claims: number;
  unsupported_claims: string[];
  failure_reason: string | null;
}

export type RefusalCode =
  | "no_authoritative_control"
  | "department_scope_ambiguous"
  | "conflicting_versions"
  | "below_groundedness_threshold"
  | "ungrounded_answer";

export interface RefusalInfo {
  code: RefusalCode;
  explanation: string;
  selected_bucket: string | null;
  user_department: string | null;
  candidates_considered: number;
  best_score: number | null;
  threshold: number | null;
}

/** S3: a control another framework officially maps to a cited section. */
export interface RelatedControl {
  label: string;
  framework: string;
  control_id: string;
  section_id?: string | null;
  relationship: string;
  mapping_source: string;
}

export interface CitationItem {
  policy_id: string;
  policy_version_id: string;
  section_id: string | null;
  policy_name: string | null;
  section_title: string | null;
  section_path: string | null;
  control_id?: string | null;
  control_name?: string | null;
  snippet: string;
  score: number;
  public_url: string | null;
  /** S2: when the cited version took effect (ISO date). */
  effective_date?: string | null;
  version_label?: string | null;
  related_controls?: RelatedControl[];
  related_controls_truncated?: boolean;
}

export interface DecisionInfo {
  selected_bucket: "department_specific" | "org_wide" | string;
  reason: string;
  /** S2: the point-in-time the answer was evaluated against (ISO date). */
  as_of?: string | null;
  user_department: string | null;
  primary_candidates: number;
  secondary_candidates: number;
}

export interface SecondaryEvidenceItem {
  policy_version_id: string;
  section_id: string | null;
  policy_name: string | null;
  section_title: string | null;
  score: number;
  department_scope: string | null;
  public_url: string | null;
}

export type ReferenceType = "internal_section" | "cross_policy" | "external_authority";
export type ReferenceResolutionStatus = "resolved" | "unresolved" | "external";

export interface PolicyReferenceItem {
  id: string;
  reference_type: ReferenceType;
  resolution_status: ReferenceResolutionStatus;
  matched_text: string;
  match_offset: number | null;
  confidence: number;
  extractor_version: string;
  source_section_id: string;
  source_policy_version_id: string;
  target_section_id: string | null;
  target_policy_id: string | null;
  target_section_title: string | null;
  target_section_path: string | null;
  target_policy_name: string | null;
  target_external_uri: string | null;
  target_external_label: string | null;
  relationship_type?: string | null;
  strength?: number | null;
  mapping_source?: string | null;
  mapping_revision?: string | null;
  source_section_title?: string | null;
  source_section_path?: string | null;
  source_policy_name?: string | null;
  created_at: string;
}

export interface SectionReferencesResponse {
  section_id: string;
  outbound: PolicyReferenceItem[];
  inbound: PolicyReferenceItem[];
}

export interface PolicySectionDetailResponse {
  section_id: string;
  tenant_id: string;
  policy_id: string;
  policy_version_id: string;
  policy_name: string;
  section_index: number;
  section_path: string | null;
  section_title: string | null;
  text: string;
  effective_date: string | null;
  is_current: boolean;
  public_url: string | null;
  metadata: Record<string, unknown>;
}

export interface IngestionBatchCreateRequest {
  tenant_id: string;
  source_system?: string | null;
  submitted_by_user_id?: string | null;
  correlation_id?: string | null;
}

export interface IngestionBatchResponse {
  id: string;
  tenant_id: string;
  source_system: string | null;
  submitted_by_user_id: string | null;
  status: string;
  status_reason: string | null;
  correlation_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadUrlRequest {
  container_name: string;
  blob_path: string;
  expires_in_minutes?: number;
  content_type?: string;
}

export interface UploadUrlResponse {
  upload_sas_url: string;
  blob_uri: string;
  expires_in_minutes: number;
}

export interface RegisterDocumentRequest {
  container_name: string;
  blob_path: string;
  policy_external_id: string;
  policy_name: string;
  version_label?: string | null;
  metadata: Record<string, unknown>;
  correlation_id?: string | null;
  content_type?: string | null;
  content_length?: number | null;
  title?: string | null;
}

export interface RegisterDocumentResponse {
  ingest_item_id: string;
  policy_id: string;
  policy_version_id: string;
  version_number: number;
  content_sha256: string;
  metadata_sha256: string;
  parse_status: string;
}

export interface CrawlUrlRegisterRequest {
  url: string;
  container_name: string;
  policy_external_id: string;
  policy_name: string;
  version_label?: string | null;
  blob_path?: string | null;
  metadata?: Record<string, unknown>;
  correlation_id?: string | null;
  title?: string | null;
}
