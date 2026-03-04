import { Chip, Stack, Typography } from "@mui/material";

interface QuickReplyChipsProps {
  options: string[];
  onSelect: (value: string) => void;
}

export default function QuickReplyChips({ options, onSelect }: QuickReplyChipsProps) {
  return (
    <Stack spacing={1}>
      <Typography variant="caption" color="text.secondary">
        Quick replies
      </Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {options.map((option) => (
          <Chip key={option} label={option} onClick={() => onSelect(option)} variant="outlined" />
        ))}
      </Stack>
    </Stack>
  );
}
