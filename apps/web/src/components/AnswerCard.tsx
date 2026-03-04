import LaunchRoundedIcon from "@mui/icons-material/LaunchRounded";
import WarningAmberRoundedIcon from "@mui/icons-material/WarningAmberRounded";
import { Alert, Button, Card, CardContent, Chip, Divider, Stack, Typography } from "@mui/material";
import type { AskResponse } from "../api/types";
import CitationsChips from "./CitationsChips";
import CopyButton from "./CopyButton";

interface AnswerCardProps {
  answer: AskResponse;
  department: string;
  onCopy: (value: string, label: string) => void;
  onOpenAudit: (auditId: string) => void;
  onOpenEvidence: () => void;
}

function bucketLabel(answer: AskResponse, department: string) {
  const isDepartmentSpecific = answer.evidence.some((item) => item.metadata.department_scope === department);
  return isDepartmentSpecific ? "Dept-specific" : "Org-wide";
}

function topAuthority(answer: AskResponse) {
  const level = answer.evidence.reduce((max, item) => Math.max(max, item.metadata.authority_level), 0);
  return level > 0 ? `A${level}` : "N/A";
}

export default function AnswerCard({ answer, department, onCopy, onOpenAudit, onOpenEvidence }: AnswerCardProps) {
  const bucket = bucketLabel(answer, department);

  return (
    <Card>
      <CardContent>
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label="Mode: strict" color="primary" />
            <Chip label={`Department: ${department || "unknown"}`} variant="outlined" />
            {typeof answer.confidence === "number" && <Chip label={`Confidence: ${Math.round(answer.confidence * 100)}%`} />}
            {answer.refusal_reason && (
              <Chip icon={<WarningAmberRoundedIcon />} label={`Refusal: ${answer.refusal_reason}`} color="warning" variant="outlined" />
            )}
          </Stack>

          {answer.refusal_reason === "insufficient_evidence" && (
            <Alert severity="warning">Insufficient evidence. The model could not answer with high confidence.</Alert>
          )}

          <Typography variant="body1" sx={{ whiteSpace: "pre-wrap" }}>
            {answer.answer}
          </Typography>

          <Divider />

          <Typography variant="body2" color="text.secondary">
            Evidence: {answer.evidence.length} · Top authority: {topAuthority(answer)} · Selected bucket: {bucket}
          </Typography>

          <CitationsChips citations={answer.citations} onCopy={(citation) => onCopy(citation, "citation")} />

          <Stack direction="row" alignItems="center" spacing={1} useFlexGap flexWrap="wrap">
            <Typography variant="body2" color="text.secondary">
              Audit ID: {answer.audit_id}
            </Typography>
            <CopyButton value={answer.audit_id} label="audit id" onCopied={() => onCopy(answer.audit_id, "audit id")} />
            <Button size="small" endIcon={<LaunchRoundedIcon />} onClick={() => onOpenAudit(answer.audit_id)}>
              Open Audit
            </Button>
            <Button size="small" variant="outlined" onClick={onOpenEvidence}>
              Evidence
            </Button>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
