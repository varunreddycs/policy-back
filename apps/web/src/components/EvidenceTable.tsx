import ContentCopyRoundedIcon from "@mui/icons-material/ContentCopyRounded";
import ExpandLessRoundedIcon from "@mui/icons-material/ExpandLessRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import {
  Box,
  Collapse,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography
} from "@mui/material";
import { useState } from "react";
import type { EvidenceItem } from "../api/types";

interface EvidenceTableProps {
  evidence: EvidenceItem[];
  onCopy: (value: string, label: string) => void;
}

export default function EvidenceTable({ evidence, onCopy }: EvidenceTableProps) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  if (!evidence.length) {
    return (
      <Box sx={{ py: 3 }}>
        <Typography variant="body2" color="text.secondary">
          No evidence rows available.
        </Typography>
      </Box>
    );
  }

  return (
    <TableContainer sx={{ maxHeight: "calc(100vh - 220px)", border: 1, borderColor: "divider", borderRadius: 2 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell width={44} />
            <TableCell>Title</TableCell>
            <TableCell>Score</TableCell>
            <TableCell>Authority</TableCell>
            <TableCell>Scope</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {evidence.map((item, index) => {
            const isExpanded = !!expanded[index];
            return (
              <>
                <TableRow key={`${item.section_id}-${index}`}>
                  <TableCell>
                    <IconButton size="small" onClick={() => setExpanded((prev) => ({ ...prev, [index]: !isExpanded }))}>
                      {isExpanded ? <ExpandLessRoundedIcon fontSize="small" /> : <ExpandMoreRoundedIcon fontSize="small" />}
                    </IconButton>
                  </TableCell>
                  <TableCell>{item.metadata.title || "Untitled"}</TableCell>
                  <TableCell>{item.score.toFixed(4)}</TableCell>
                  <TableCell>{item.metadata.authority_level}</TableCell>
                  <TableCell>{item.metadata.department_scope || "org"}</TableCell>
                  <TableCell align="right">
                    <Stack direction="row" justifyContent="flex-end" spacing={1}>
                      <Tooltip title="Copy IDs">
                        <IconButton
                          size="small"
                          onClick={() =>
                            onCopy(
                              JSON.stringify(
                                {
                                  policy_id: item.policy_id,
                                  policy_version_id: item.policy_version_id,
                                  section_id: item.section_id
                                },
                                null,
                                2
                              ),
                              "IDs"
                            )
                          }
                        >
                          <ContentCopyRoundedIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Copy text">
                        <IconButton size="small" onClick={() => onCopy(item.text, "text")}>
                          <ContentCopyRoundedIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell colSpan={6} sx={{ py: 0 }}>
                    <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                      <Box sx={{ p: 2, bgcolor: "background.default", borderTop: 1, borderColor: "divider" }}>
                        <Typography variant="caption" color="text.secondary">
                          Section Path: {item.metadata.section_path}
                        </Typography>
                        <Typography variant="body2" sx={{ mt: 1, whiteSpace: "pre-wrap" }}>
                          {item.text}
                        </Typography>
                      </Box>
                    </Collapse>
                  </TableCell>
                </TableRow>
              </>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
