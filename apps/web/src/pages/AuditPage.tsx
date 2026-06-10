import { Snackbar } from "@mui/material";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { policyApi } from "../api/policyApi";
import AuditViewer from "../components/AuditViewer";

const TENANT_ID = import.meta.env.VITE_TENANT_ID || "00000000-0000-0000-0000-000000000001";

export default function AuditPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [auditId, setAuditId] = useState(searchParams.get("id") ?? "");
  const [loading, setLoading] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [payload, setPayload] = useState<unknown>(null);
  const [replayPayload, setReplayPayload] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [snack, setSnack] = useState<{ open: boolean; message: string }>({ open: false, message: "" });

  const loadAudit = async (id: string) => {
    if (!id.trim()) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = await policyApi.getAudit(id.trim(), TENANT_ID);
      setPayload(result);
      setSnack({ open: true, message: "Audit loaded" });
    } catch (err) {
      const message = err instanceof ApiError ? `Load failed (${err.status}): ${err.message}` : "Failed to load audit.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const replayAudit = async () => {
    if (!auditId.trim()) {
      return;
    }

    setReplayLoading(true);
    setError(null);

    try {
      const result = await policyApi.replayAudit(auditId.trim(), TENANT_ID);
      setReplayPayload(result);
      setSnack({ open: true, message: "Replay completed" });
    } catch (err) {
      const message = err instanceof ApiError ? `Replay failed (${err.status}): ${err.message}` : "Failed to replay audit.";
      setError(message);
    } finally {
      setReplayLoading(false);
    }
  };

  useEffect(() => {
    const queryId = searchParams.get("id");
    if (queryId) {
      setAuditId(queryId);
      loadAudit(queryId);
    }
  }, [searchParams]);

  return (
    <>
      <AuditViewer
        auditId={auditId}
        loading={loading}
        replayLoading={replayLoading}
        payload={payload}
        replayPayload={replayPayload}
        error={error}
        onChangeAuditId={setAuditId}
        onLoad={() => loadAudit(auditId)}
        onReplay={replayAudit}
        onBack={() => navigate("/console")}
      />

      <Snackbar
        open={snack.open}
        autoHideDuration={2400}
        onClose={() => setSnack({ open: false, message: "" })}
        message={snack.message}
      />
    </>
  );
}
