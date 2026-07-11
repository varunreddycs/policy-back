import { Chip, Stack, Typography } from "@mui/material";

interface CitationsChipsProps {
  citations: string[];
  onCopy: (value: string) => void;
}

export default function CitationsChips({ citations, onCopy }: CitationsChipsProps) {
  if (!citations.length) {
    return (
      <Typography variant="body2" sx={{
        color: "text.secondary"
      }}>No citations returned.
              </Typography>
    );
  }

  return (
    <Stack spacing={1}>
      <Typography variant="subtitle2">Citations</Typography>
      <Stack direction="row" spacing={1} useFlexGap sx={{
        flexWrap: "wrap"
      }}>
        {citations.map((citation, index) => (
          <Chip key={`${citation}-${index}`} label={citation} clickable onClick={() => onCopy(citation)} />
        ))}
      </Stack>
    </Stack>
  );
}
