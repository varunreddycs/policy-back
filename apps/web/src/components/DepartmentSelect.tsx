import { FormControl, InputLabel, MenuItem, Select, Stack, TextField } from "@mui/material";

const DEPARTMENTS: string[] = ((import.meta.env.VITE_DEPARTMENT_OPTIONS as string | undefined) || "operations,compliance,finance,hr,it")
  .split(",")
  .map((item: string) => item.trim())
  .filter(Boolean);

interface DepartmentSelectProps {
  department: string;
  onChange: (value: string) => void;
}

export default function DepartmentSelect({ department, onChange }: DepartmentSelectProps) {
  const isKnownDepartment = DEPARTMENTS.includes(department);
  const selectedValue = isKnownDepartment ? department : "other";

  return (
    <Stack spacing={1.5}>
      <FormControl fullWidth>
        <InputLabel id="department-label">Department</InputLabel>
        <Select
          labelId="department-label"
          label="Department"
          value={selectedValue}
          onChange={(event) => {
            const nextValue = event.target.value;
            if (nextValue === "other") {
              if (isKnownDepartment) {
                onChange("");
              }
              return;
            }
            onChange(nextValue);
          }}
        >
          {DEPARTMENTS.map((item) => (
            <MenuItem key={item} value={item}>
              {item}
            </MenuItem>
          ))}
          <MenuItem value="other">Other</MenuItem>
        </Select>
      </FormControl>
      {selectedValue === "other" && (
        <TextField
          fullWidth
          label="Other department"
          value={department}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Enter department"
        />
      )}
    </Stack>
  );
}
