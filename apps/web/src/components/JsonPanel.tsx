import { Card, CardContent, Typography } from "@mui/material";

interface JsonPanelProps {
  title: string;
  value: unknown;
}

export default function JsonPanel({ title, value }: JsonPanelProps) {
  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          {title}
        </Typography>
        <Typography
          component="pre"
          sx={{
            m: 0,
            p: 2,
            borderRadius: 2,
            bgcolor: "background.default",
            border: 1,
            borderColor: "divider",
            overflow: "auto",
            fontFamily: "monospace",
            fontSize: "0.82rem",
            lineHeight: 1.6
          }}
        >
          {JSON.stringify(value, null, 2)}
        </Typography>
      </CardContent>
    </Card>
  );
}
