import ForumRoundedIcon from "@mui/icons-material/ForumRounded";
import { Box, Stack, Typography } from "@mui/material";
import type { AskResponse } from "../api/types";
import AnswerCard from "./AnswerCard";

interface AnswerStreamProps {
  answers: AskResponse[];
  tenantId: string;
  department: string;
  onCopy: (value: string, label: string) => void;
  onOpenAudit: (auditId: string) => void;
  onOpenEvidence: () => void;
}

export default function AnswerStream({ answers, tenantId, department, onCopy, onOpenAudit, onOpenEvidence }: AnswerStreamProps) {
  if (!answers.length) {
    return (
      <Box
        sx={{
          p: 5,
          border: 1,
          borderColor: "divider",
          borderRadius: 2,
          textAlign: "center",
          bgcolor: "background.paper"
        }}
      >
        <ForumRoundedIcon color="primary" />
        <Typography variant="h6" sx={{ mt: 1 }}>
          Ask your first policy question
        </Typography>
        <Typography variant="body2" sx={{
          color: "text.secondary"
        }}>
          Answers and evidence will stream here.
        </Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      {answers.map((answer) => (
        <AnswerCard
          key={`${answer.audit_id}-${answer.created_at}`}
          answer={answer}
          tenantId={tenantId}
          department={department}
          onCopy={onCopy}
          onOpenAudit={onOpenAudit}
          onOpenEvidence={onOpenEvidence}
        />
      ))}
    </Stack>
  );
}
