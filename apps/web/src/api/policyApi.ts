import { apiRequest } from "./client";
import type { AskRequest, AskResponse } from "./types";

export const policyApi = {
  ask(request: AskRequest) {
    return apiRequest<AskResponse>("/v1/ask", {
      method: "POST",
      body: JSON.stringify(request)
    });
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
  }
};
