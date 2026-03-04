import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import { Alert, Button, Card, CardContent, Stack, TextField } from "@mui/material";
import JsonPanel from "./JsonPanel";

interface AuditViewerProps {
  auditId: string;
  loading: boolean;
  replayLoading: boolean;
  payload: unknown;
  replayPayload: unknown;
  error: string | null;
  onChangeAuditId: (value: string) => void;
  onLoad: () => void;
  onReplay: () => void;
  onBack: () => void;
}

export default function AuditViewer({
  auditId,
  loading,
  replayLoading,
  payload,
  replayPayload,
  error,
  onChangeAuditId,
  onLoad,
  onReplay,
  onBack
}: AuditViewerProps) {
  return (
    <Stack spacing={2}>
      <Card>
        <CardContent>
          <Stack spacing={1.5}>
            <TextField
              label="Audit ID"
              value={auditId}
              onChange={(event) => onChangeAuditId(event.target.value)}
              fullWidth
            />
            <Stack direction="row" spacing={1}>
              <Button variant="contained" onClick={onLoad} disabled={!auditId.trim() || loading} startIcon={<RefreshRoundedIcon />}>
                {loading ? "Loading..." : "Load"}
              </Button>
              <Button
                variant="outlined"
                onClick={onReplay}
                disabled={!auditId.trim() || replayLoading}
                startIcon={<PlayArrowRoundedIcon />}
              >
                {replayLoading ? "Replaying..." : "Replay"}
              </Button>
              <Button onClick={onBack}>Back to Console</Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      {error && <Alert severity="error">{error}</Alert>}

      {payload !== null && <JsonPanel title="Audit Payload" value={payload} />}
      {replayPayload !== null && <JsonPanel title="Replay Response" value={replayPayload} />}
    </Stack>
  );
}
