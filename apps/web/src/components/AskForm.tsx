import SendRoundedIcon from "@mui/icons-material/SendRounded";
import { Button, Stack, TextField } from "@mui/material";

interface AskFormProps {
  question: string;
  loading: boolean;
  onChangeQuestion: (value: string) => void;
  onSubmit: () => void;
}

export default function AskForm({ question, loading, onChangeQuestion, onSubmit }: AskFormProps) {
  return (
    <Stack spacing={1.5}>
      <TextField
        label="Question"
        multiline
        minRows={3}
        fullWidth
        value={question}
        onChange={(event) => onChangeQuestion(event.target.value)}
        placeholder="Ask a policy question..."
      />
      <Stack direction="row" sx={{
        justifyContent: "flex-end"
      }}>
        <Button
          variant="contained"
          endIcon={<SendRoundedIcon />}
          onClick={onSubmit}
          disabled={loading || !question.trim()}
        >
          {loading ? "Asking..." : "Ask"}
        </Button>
      </Stack>
    </Stack>
  );
}
