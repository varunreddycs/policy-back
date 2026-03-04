import React from "react";
import ReactDOM from "react-dom/client";
import { CssBaseline, ThemeProvider } from "@mui/material";
import { buildTheme } from "./theme/buildTheme";
import { useBranding } from "./theme/useBranding";
import App from "./App";
import "./styles/globals.css";

function Root() {
  const branding = useBranding();
  const theme = React.useMemo(() => buildTheme(branding), [branding]);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
