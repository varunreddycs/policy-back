import ContentCopyRoundedIcon from "@mui/icons-material/ContentCopyRounded";
import { IconButton, Tooltip } from "@mui/material";

interface CopyButtonProps {
  value: string;
  label: string;
  onCopied?: (label: string) => void;
}

export default function CopyButton({ value, label, onCopied }: CopyButtonProps) {
  const handleCopy = async () => {
    await navigator.clipboard.writeText(value);
    onCopied?.(label);
  };

  return (
    <Tooltip title={`Copy ${label}`}>
      <IconButton size="small" onClick={handleCopy}>
        <ContentCopyRoundedIcon fontSize="small" />
      </IconButton>
    </Tooltip>
  );
}
