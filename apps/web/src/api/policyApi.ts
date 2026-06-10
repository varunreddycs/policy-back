import { apiRequest } from "./client";
import type {
  AskRequest,
  AskResponse,
  CrawlUrlRegisterRequest,
  IngestionBatchCreateRequest,
  IngestionBatchResponse,
  PolicySectionDetailResponse,
  RegisterDocumentRequest,
  RegisterDocumentResponse,
  SectionReferencesResponse,
  UploadUrlRequest,
  UploadUrlResponse
} from "./types";

export const policyApi = {
  ask(request: AskRequest) {
    return apiRequest<AskResponse>("/v1/ask", {
      method: "POST",
      body: JSON.stringify(request)
    });
  },

  getPolicySection(sectionId: string, tenantId: string) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<PolicySectionDetailResponse>(
      `/v1/policy-sections/${encodeURIComponent(sectionId)}?${params.toString()}`
    );
  },

  getSectionReferences(sectionId: string, tenantId: string) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<SectionReferencesResponse>(
      `/v1/policy-sections/${encodeURIComponent(sectionId)}/references?${params.toString()}`
    );
  },

  getAudit(auditId: string, tenantId: string) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<unknown>(`/v1/audit/${encodeURIComponent(auditId)}?${params.toString()}`);
  },

  replayAudit(auditId: string, tenantId: string) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<unknown>(`/v1/audit/${encodeURIComponent(auditId)}/replay?${params.toString()}`, {
      method: "POST"
    });
  },

  createIngestionBatch(request: IngestionBatchCreateRequest) {
    return apiRequest<IngestionBatchResponse>("/v1/ingest/batches", {
      method: "POST",
      body: JSON.stringify(request)
    });
  },

  createUploadUrl(batchId: string, tenantId: string, request: UploadUrlRequest) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<UploadUrlResponse>(`/v1/ingest/batches/${encodeURIComponent(batchId)}/upload-urls?${params.toString()}`, {
      method: "POST",
      body: JSON.stringify(request)
    });
  },

  registerDocument(batchId: string, tenantId: string, request: RegisterDocumentRequest) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<RegisterDocumentResponse>(`/v1/ingest/batches/${encodeURIComponent(batchId)}/register?${params.toString()}`, {
      method: "POST",
      body: JSON.stringify(request)
    });
  },

  uploadAndRegisterDocument(batchId: string, tenantId: string, formData: FormData) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<RegisterDocumentResponse>(
      `/v1/ingest/batches/${encodeURIComponent(batchId)}/upload-and-register?${params.toString()}`,
      {
        method: "POST",
        body: formData
      }
    );
  },

  crawlUrlAndRegisterDocument(batchId: string, tenantId: string, request: CrawlUrlRegisterRequest) {
    const params = new URLSearchParams({ tenant_id: tenantId });
    return apiRequest<RegisterDocumentResponse>(
      `/v1/ingest/batches/${encodeURIComponent(batchId)}/crawl-and-register?${params.toString()}`,
      {
        method: "POST",
        body: JSON.stringify(request)
      }
    );
  }
};
