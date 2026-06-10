import { useMemo } from "react";
import defaultBranding from "./defaultBranding";

export function useBranding() {
  return useMemo(() => defaultBranding, []);
}
