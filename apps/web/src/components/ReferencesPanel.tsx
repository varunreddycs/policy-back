import { useEffect, useState } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import { policyApi } from "../api/policyApi";
import type {
  PolicyReferenceItem,
  ReferenceType,
  SectionReferencesResponse
} from "../api/types";

interface ReferencesPanelProps {
  sectionId: string | null;
  tenantId: string;
}

const TYPE_LABELS: Record<ReferenceType, string> = {
  internal_section: "Section",
  cross_policy: "Policy",
  external_authority: "External"
};

function statusColor(status: PolicyReferenceItem["resolution_status"]) {
  switch (status) {
    case "resolved":
      return "success";
    case "external":
      return "info";
    default:
      return "warning";
  }
}

function describeTarget(ref: PolicyReferenceItem): string {
  if (ref.target_section_title || ref.target_section_path) {
    const head = ref.target_policy_name ? `${ref.target_policy_name} · ` : "";
    return `${head}${ref.target_section_title ?? ref.target_section_path ?? ""}`;
  }
  if (ref.target_policy_name) {
    return ref.target_policy_name;
  }
  if (ref.target_external_label) {
    return ref.target_external_label;
  }
  return ref.matched_text;
}

function ReferenceList({ title, items }: { title: string; items: PolicyReferenceItem[] }) {
  return (
    <Box>
      <Typography variant="overline" color="text.secondary">
        {title} ({items.length})
      </Typography>
      {items.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          None
        </Typography>
      ) : (
        <Stack spacing={0.75} sx={{ mt: 0.5 }}>
          {items.map((ref) => (
            <Box
              key={ref.id}
              sx={{
                p: 1,
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
                bgcolor: "background.paper"
              }}
            >
              <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.5 }}>
                <Chip size="small" label={TYPE_LABELS[ref.reference_type]} />
                <Chip
                  size="small"
                  label={ref.resolution_status}
                  color={statusColor(ref.resolution_status)}
                  variant="outlined"
                />
              </Stack>
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {describeTarget(ref)}
              </Typography>
              {ref.matched_text && ref.matched_text !== describeTarget(ref) ? (
                <Typography variant="caption" color="text.secondary">
                  “{ref.matched_text}”
                </Typography>
              ) : null}
              {ref.target_external_uri ? (
                <Typography variant="caption" component="div">
                  <a href={ref.target_external_uri} target="_blank" rel="noreferrer">
                    {ref.target_external_uri}
                  </a>
                </Typography>
              ) : null}
            </Box>
          ))}
        </Stack>
      )}
    </Box>
  );
}

export default function ReferencesPanel({ sectionId, tenantId }: ReferencesPanelProps) {
  const [data, setData] = useState<SectionReferencesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sectionId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    policyApi
      .getSectionReferences(sectionId, tenantId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load references");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sectionId, tenantId]);

  if (!sectionId) {
    return null;
  }

  return (
    <Box sx={{ p: 2, border: 1, borderColor: "divider", borderRadius: 2, bgcolor: "background.default" }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        References
      </Typography>
      {loading ? (
        <Typography variant="body2" color="text.secondary">
          Loading…
        </Typography>
      ) : error ? (
        <Typography variant="body2" color="error">
          {error}
        </Typography>
      ) : data && (data.outbound.length === 0 && data.inbound.length === 0) ? (
        <Typography variant="body2" color="text.secondary">
          No references detected for this section.
        </Typography>
      ) : data ? (
        <Stack spacing={1.5}>
          <ReferenceList title="Outbound" items={data.outbound} />
          <ReferenceList title="Inbound" items={data.inbound} />
        </Stack>
      ) : null}
    </Box>
  );
}
