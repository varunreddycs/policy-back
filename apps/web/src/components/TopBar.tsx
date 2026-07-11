import GavelRoundedIcon from "@mui/icons-material/GavelRounded";
import { AppBar, Box, Button, Stack, Toolbar, Typography } from "@mui/material";
import { NavLink, useLocation } from "react-router-dom";

export default function TopBar() {
  const location = useLocation();

  return (
    <AppBar position="sticky" color="transparent" sx={{ borderBottom: 1, borderColor: "divider" }}>
      <Toolbar variant="dense" sx={{ minHeight: 52 }}>
        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems: "center",
            flex: 1
          }}>
          <GavelRoundedIcon color="primary" fontSize="small" />
          <Typography variant="subtitle1">Mistrv Policy Console</Typography>
        </Stack>
        <Box sx={{ display: "flex", gap: 1 }}>
          <Button
            component={NavLink}
            to="/console"
            variant={location.pathname.startsWith("/console") ? "contained" : "outlined"}
            size="small"
          >
            Console
          </Button>
          <Button
            component={NavLink}
            to="/audit"
            variant={location.pathname.startsWith("/audit") ? "contained" : "outlined"}
            size="small"
          >
            Audit
          </Button>
          <Button
            component={NavLink}
            to="/ingest"
            variant={location.pathname.startsWith("/ingest") ? "contained" : "outlined"}
            size="small"
          >
            Ingest
          </Button>
          <Button
            component={NavLink}
            to="/roadmap"
            variant={location.pathname.startsWith("/roadmap") ? "contained" : "outlined"}
            size="small"
          >
            Roadmap
          </Button>
        </Box>
      </Toolbar>
    </AppBar>
  );
}
