export type DepartmentValue = "claims_ops" | "privacy_office" | "finance" | "hr" | "it" | string;

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
  confidence: number | null;
  refusal_reason: "insufficient_evidence" | null;
  evidence: EvidenceItem[];
  created_at: string;
}

export interface CitationItem {
  policy_id: string;
  policy_version_id: string;
  section_id: string | null;
  policy_name: string | null;
  section_title: string | null;
  section_path: string | null;
  snippet: string;
  score: number;
  public_url: string | null;
}

export interface DecisionInfo {
  selected_bucket: "department_specific" | "org_wide" | string;
  reason: string;
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
