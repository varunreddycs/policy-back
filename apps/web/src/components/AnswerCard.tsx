import LaunchRoundedIcon from "@mui/icons-material/LaunchRounded";
import OpenInNewRoundedIcon from "@mui/icons-material/OpenInNewRounded";
import WarningAmberRoundedIcon from "@mui/icons-material/WarningAmberRounded";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  Typography
} from "@mui/material";
import { useState } from "react";
import { policyApi } from "../api/policyApi";
import type { AskResponse, PolicySectionDetailResponse } from "../api/types";
import CitationsChips from "./CitationsChips";
import CopyButton from "./CopyButton";

interface AnswerCardProps {
  answer: AskResponse;
  tenantId: string;
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

export default function AnswerCard({ answer, tenantId, department, onCopy, onOpenAudit, onOpenEvidence }: AnswerCardProps) {
  const bucket = bucketLabel(answer, department);
  const citationItems = answer.citation_items ?? [];
  const secondary = answer.secondary_evidence ?? [];
  const [sectionOpen, setSectionOpen] = useState(false);
  const [sectionLoading, setSectionLoading] = useState(false);
  const [sectionError, setSectionError] = useState<string | null>(null);
  const [sectionDetail, setSectionDetail] = useState<PolicySectionDetailResponse | null>(null);

  const openSectionDetail = async (sectionId: string | null) => {
    if (!sectionId) {
      return;
    }
    setSectionOpen(true);
    setSectionLoading(true);
    setSectionError(null);
    try {
      const detail = await policyApi.getPolicySection(sectionId, tenantId);
      setSectionDetail(detail);
    } catch {
      setSectionDetail(null);
      setSectionError("Unable to load section detail.");
    } finally {
      setSectionLoading(false);
    }
  };

  return (
    <>
      <Card>
        <CardContent>
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} useFlexGap sx={{
              flexWrap: "wrap"
            }}>
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

            <Typography variant="body2" sx={{
              color: "text.secondary"
            }}>
              Evidence: {answer.evidence.length} · Top authority: {topAuthority(answer)} · Selected bucket: {bucket}
            </Typography>

            {answer.decision && (
              <Alert severity="info" variant="outlined">
                Why this answer: {answer.decision.reason} (selected: {answer.decision.selected_bucket}, primary: {answer.decision.primary_candidates}, secondary: {answer.decision.secondary_candidates})
              </Alert>
            )}

            {!!citationItems.length && (
              <Stack spacing={1}>
                <Typography variant="subtitle2">Citations</Typography>
                {citationItems.map((item, index) => (
                  <Box key={`${item.policy_version_id}-${item.section_id}-${index}`} sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 2 }}>
                    <Stack
                      direction="row"
                      spacing={1}
                      useFlexGap
                      sx={{
                        flexWrap: "wrap",
                        mb: 1
                      }}>
                      <Chip size="small" label={item.policy_name || "Policy"} />
                      <Chip size="small" variant="outlined" label={(item.section_title || item.section_path || "Section").slice(0, 60)} />
                      <Chip size="small" variant="outlined" label={`Score ${item.score.toFixed(3)}`} />
                    </Stack>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      {item.snippet}
                    </Typography>
                    <Stack direction="row" spacing={1} useFlexGap sx={{
                      flexWrap: "wrap"
                    }}>
                      {item.public_url && (
                        <Button size="small" endIcon={<OpenInNewRoundedIcon />} onClick={() => window.open(item.public_url || undefined, "_blank", "noopener,noreferrer")}>Open URL</Button>
                      )}
                      {item.section_id && (
                        <Button size="small" variant="outlined" onClick={() => openSectionDetail(item.section_id)}>View section</Button>
                      )}
                      <Button size="small" variant="text" onClick={() => onCopy(item.snippet, "citation snippet")}>Copy snippet</Button>
                    </Stack>
                  </Box>
                ))}
              </Stack>
            )}

            <CitationsChips citations={answer.citations} onCopy={(citation) => onCopy(citation, "citation")} />

            {!!secondary.length && (
              <Accordion disableGutters>
                <AccordionSummary>
                  <Typography variant="subtitle2">Also relevant ({secondary.length})</Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Stack spacing={1}>
                    {secondary.map((item, index) => (
                      <Box key={`${item.policy_version_id}-${item.section_id}-${index}`} sx={{ p: 1, border: 1, borderColor: "divider", borderRadius: 1.5 }}>
                        <Typography variant="body2">
                          {(item.policy_name || "Policy") + " - " + (item.section_title || "Section")}
                        </Typography>
                        <Typography variant="caption" sx={{
                          color: "text.secondary"
                        }}>
                          Score {item.score.toFixed(3)} · Scope {item.department_scope || "all"}
                        </Typography>
                        {!!item.public_url && (
                          <Stack direction="row" sx={{ mt: 0.5 }}>
                            <Button size="small" endIcon={<OpenInNewRoundedIcon />} onClick={() => window.open(item.public_url || undefined, "_blank", "noopener,noreferrer")}>Open URL</Button>
                          </Stack>
                        )}
                      </Box>
                    ))}
                  </Stack>
                </AccordionDetails>
              </Accordion>
            )}

            <Stack
              direction="row"
              spacing={1}
              useFlexGap
              sx={{
                alignItems: "center",
                flexWrap: "wrap"
              }}>
              <Typography variant="body2" sx={{
                color: "text.secondary"
              }}>
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
      <Dialog open={sectionOpen} onClose={() => setSectionOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Section Detail</DialogTitle>
        <DialogContent>
          {sectionLoading && <CircularProgress size={20} />}
          {sectionError && <Alert severity="error">{sectionError}</Alert>}
          {sectionDetail && (
            <Stack spacing={1.5}>
              <Typography variant="subtitle2">{sectionDetail.policy_name}</Typography>
              <Typography variant="body2" sx={{
                color: "text.secondary"
              }}>
                {sectionDetail.section_title || sectionDetail.section_path || `Section ${sectionDetail.section_index}`}
              </Typography>
              <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                {sectionDetail.text}
              </Typography>
              {sectionDetail.public_url && (
                <Button
                  size="small"
                  endIcon={<OpenInNewRoundedIcon />}
                  onClick={() => window.open(sectionDetail.public_url || undefined, "_blank", "noopener,noreferrer")}
                >
                  Open Source URL
                </Button>
              )}
            </Stack>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
