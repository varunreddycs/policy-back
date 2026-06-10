import { alpha, createTheme } from "@mui/material/styles";

export function buildTheme(branding) {
  const theme = createTheme({
    palette: {
      mode: branding.mode,
      primary: {
        main: branding.primaryColor
      },
      secondary: {
        main: branding.secondaryColor
      },
      background: {
        default: branding.backgroundDefault,
        paper: branding.backgroundPaper
      },
      divider: alpha("#FFFFFF", 0.12)
    },
    shape: {
      borderRadius: 16
    },
    typography: {
      fontFamily: branding.fontFamily,
      h5: { fontWeight: 700, letterSpacing: 0.2 },
      h6: { fontWeight: 700, letterSpacing: 0.1 },
      subtitle1: { fontWeight: 600 },
      body1: { fontSize: "0.96rem", lineHeight: 1.6 },
      body2: { lineHeight: 1.5 },
      button: { fontWeight: 600, textTransform: "none" }
    },
    components: {
      MuiPaper: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            border: `1px solid ${alpha("#FFFFFF", 0.08)}`,
            boxShadow: `0 ${8}px ${24}px ${alpha("#000000", 0.25)}`
          }
        }
      },
      MuiCard: {
        styleOverrides: {
          root: {
            borderRadius: 16,
            border: `1px solid ${alpha("#FFFFFF", 0.08)}`,
            boxShadow: `0 ${8}px ${24}px ${alpha("#000000", 0.25)}`
          }
        }
      },
      MuiButton: {
        defaultProps: {
          disableElevation: true
        },
        styleOverrides: {
          root: {
            borderRadius: 12,
            fontWeight: 600
          }
        }
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 12,
            backgroundColor: alpha("#FFFFFF", 0.02)
          },
          notchedOutline: {
            borderColor: alpha("#FFFFFF", 0.14)
          }
        }
      },
      MuiChip: {
        styleOverrides: {
          root: {
            borderRadius: 999,
            fontWeight: 500
          }
        }
      },
      MuiTableCell: {
        styleOverrides: {
          head: {
            position: "sticky",
            top: 0,
            zIndex: 1,
            backgroundColor: alpha("#FFFFFF", 0.02),
            fontWeight: 600
          },
          root: {
            paddingTop: 10,
            paddingBottom: 10,
            borderBottomColor: alpha("#FFFFFF", 0.08)
          }
        }
      },
      MuiTableRow: {
        styleOverrides: {
          root: {
            "&:hover": {
              backgroundColor: alpha("#FFFFFF", 0.03)
            }
          }
        }
      },
      MuiDrawer: {
        styleOverrides: {
          paper: {
            backgroundImage: "none",
            borderLeft: `1px solid ${alpha("#FFFFFF", 0.1)}`,
            backgroundColor: branding.backgroundPaper
          }
        }
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundImage: "none"
          }
        }
      }
    }
  });

  return theme;
}
