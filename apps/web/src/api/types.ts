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
  confidence: number | null;
  refusal_reason: "insufficient_evidence" | null;
  evidence: EvidenceItem[];
  created_at: string;
}
