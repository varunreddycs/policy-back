import AutoAwesomeRoundedIcon from "@mui/icons-material/AutoAwesomeRounded";
import { Box, Chip, Drawer, Stack, Typography, useMediaQuery, useTheme } from "@mui/material";
import type { AskResponse, EvidenceItem } from "../api/types";
import EvidenceTable from "./EvidenceTable";

interface EvidenceDrawerProps {
  open: boolean;
  onClose: () => void;
  answer: AskResponse | null;
  onCopy: (value: string, label: string) => void;
}

function getTopEvidence(evidence: EvidenceItem[]) {
  if (!evidence.length) {
    return null;
  }
  return [...evidence].sort((a, b) => b.score - a.score)[0];
}

export default function EvidenceDrawer({ open, onClose, answer, onCopy }: EvidenceDrawerProps) {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("md"));
  const evidence = answer?.evidence ?? [];
  const top = getTopEvidence(evidence);

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      PaperProps={{ sx: { width: fullScreen ? "100%" : 540 } }}
    >
      <Box sx={{ p: 2, display: "flex", flexDirection: "column", gap: 2, height: "100%" }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Typography variant="h6">Evidence Console</Typography>
          <Chip label={`${evidence.length} rows`} />
        </Stack>

        {top ? (
          <Box sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 2, bgcolor: "background.default" }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <AutoAwesomeRoundedIcon color="primary" fontSize="small" />
              <Typography variant="subtitle2">Best Candidate</Typography>
            </Stack>
            <Typography variant="body2" sx={{ mb: 1 }}>
              {top.metadata.title || "Untitled"}
            </Typography>
            <Stack direction="row" spacing={1}>
              <Chip size="small" label={`Score ${top.score.toFixed(4)}`} />
              <Chip size="small" label={`Authority ${top.metadata.authority_level}`} />
            </Stack>
          </Box>
        ) : (
          <Box sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 2, bgcolor: "background.default" }}>
            <Typography variant="body2" color="text.secondary">
              No evidence available for this response.
            </Typography>
          </Box>
        )}

        <EvidenceTable evidence={evidence} onCopy={onCopy} />
      </Box>
    </Drawer>
  );
}
