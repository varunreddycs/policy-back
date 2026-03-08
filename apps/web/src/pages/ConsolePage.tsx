import AutoFixHighRoundedIcon from "@mui/icons-material/AutoFixHighRounded";
import { Alert, Button, Card, CardContent, Grid, Snackbar, Stack, Typography } from "@mui/material";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { policyApi } from "../api/policyApi";
import type { AskRequest, AskResponse } from "../api/types";
import AnswerStream from "../components/AnswerStream";
import AskForm from "../components/AskForm";
import DepartmentSelect from "../components/DepartmentSelect";
import EvidenceDrawer from "../components/EvidenceDrawer";
import QuickReplyChips from "../components/QuickReplyChips";

const QUICK_REPLIES = [
  "Summarize the current requirements",
  "What changed in the latest version?",
  "What are the approval steps?",
  "List retention and archival rules",
  "What controls are mandatory?"
];

const TENANT_ID = import.meta.env.VITE_TENANT_ID || "00000000-0000-0000-0000-000000000001";
const DEFAULT_EMAIL = import.meta.env.VITE_DEFAULT_EMAIL || "dev@local";
const DEFAULT_ROLE = import.meta.env.VITE_DEFAULT_ROLE || "user";
const DEFAULT_DEPARTMENT = import.meta.env.VITE_DEFAULT_DEPARTMENT || "operations";

export default function ConsolePage() {
  const navigate = useNavigate();
  const [department, setDepartment] = useState(DEFAULT_DEPARTMENT);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<AskResponse[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(() => localStorage.getItem("evidence_drawer_open") === "true");
  const [snack, setSnack] = useState<{ open: boolean; message: string }>({ open: false, message: "" });

  const latest = useMemo(() => answers[0] ?? null, [answers]);

  const ask = async () => {
    if (!question.trim()) {
      return;
    }

    setLoading(true);
    setError(null);

    const payload: AskRequest = {
      tenant_id: TENANT_ID,
      question: question.trim(),
      mode: "strict",
      user: {
        tenant_id: TENANT_ID,
        email: DEFAULT_EMAIL,
        role: DEFAULT_ROLE,
        department: department || "unknown"
      },
      scope: {
        only_current: true
      }
    };

    try {
      const result = await policyApi.ask(payload);
      setAnswers((prev) => [result, ...prev].slice(0, 10));
      setQuestion("");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `Request failed (${err.status}): ${err.message}${err.body ? ` — ${JSON.stringify(err.body)}` : ""}`
          : "Unexpected error while asking question.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setSnack({ open: true, message: `${label} copied` });
    } catch {
      setSnack({ open: true, message: "Copy failed" });
    }
  };

  return (
    <>
      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Stack spacing={2}>
            <Card>
              <CardContent>
                <Stack spacing={2}>
                  <DepartmentSelect department={department} onChange={setDepartment} />
                  <AskForm question={question} loading={loading} onChangeQuestion={setQuestion} onSubmit={ask} />
                  <QuickReplyChips options={QUICK_REPLIES} onSelect={setQuestion} />
                  <Stack direction="row" justifyContent="flex-end">
                    <Button
                      variant="outlined"
                      startIcon={<AutoFixHighRoundedIcon />}
                      onClick={() => {
                        const next = !drawerOpen;
                        setDrawerOpen(next);
                        localStorage.setItem("evidence_drawer_open", String(next));
                      }}
                    >
                      Evidence
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>

            {error && <Alert severity="error">{error}</Alert>}

            <AnswerStream
              answers={answers}
              tenantId={TENANT_ID}
              department={department || "unknown"}
              onCopy={handleCopy}
              onOpenAudit={(auditId) => navigate(`/audit?id=${encodeURIComponent(auditId)}`)}
              onOpenEvidence={() => {
                setDrawerOpen(true);
                localStorage.setItem("evidence_drawer_open", "true");
              }}
            />

            {!answers.length && (
              <Typography variant="body2" color="text.secondary" textAlign="center">
                Premium evidence and citations view becomes available after your first answer.
              </Typography>
            )}
          </Stack>
        </Grid>
      </Grid>

      <EvidenceDrawer
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          localStorage.setItem("evidence_drawer_open", "false");
        }}
        answer={latest}
        onCopy={handleCopy}
      />

      <Snackbar
        open={snack.open}
        autoHideDuration={2600}
        onClose={() => setSnack({ open: false, message: "" })}
        message={snack.message}
      />
    </>
  );
}
