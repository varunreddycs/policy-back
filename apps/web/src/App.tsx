import { Box, Chip, Container, Stack, Typography } from "@mui/material";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import TopBar from "./components/TopBar";
import AuditPage from "./pages/AuditPage";
import ConsolePage from "./pages/ConsolePage";
import IngestPage from "./pages/IngestPage";
import RoadmapPage from "./pages/RoadmapPage";
import { API_BASE_URL } from "./api/client";

const tenantId = import.meta.env.VITE_TENANT_ID || "00000000-0000-0000-0000-000000000001";

function AppFooter() {
  return (
    <Box sx={{ py: 2, borderTop: 1, borderColor: "divider" }}>
      <Container maxWidth="xl">
        <Typography variant="caption" sx={{
          color: "text.secondary"
        }}>
          Build {import.meta.env.MODE} · Mistrv Policy Console
        </Typography>
      </Container>
    </Box>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Box sx={{ minHeight: "100%", bgcolor: "background.default", display: "flex", flexDirection: "column" }}>
        <TopBar />
        <Container maxWidth="xl" sx={{ py: 2, flex: 1 }}>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <Chip size="small" label={`API ${API_BASE_URL}`} variant="outlined" />
            <Chip size="small" label={`Tenant ${tenantId.slice(0, 8)}`} variant="outlined" />
          </Stack>
          <Routes>
            <Route path="/console" element={<ConsolePage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/ingest" element={<IngestPage />} />
            <Route path="/roadmap" element={<RoadmapPage />} />
            <Route path="*" element={<Navigate to="/console" replace />} />
          </Routes>
        </Container>
        <AppFooter />
      </Box>
    </BrowserRouter>
  );
}
