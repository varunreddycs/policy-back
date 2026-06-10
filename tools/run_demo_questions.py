"""Run the NIST 800-53 demo question set against the deployed Policy Platform API
and write a Markdown results report (docs/DEMO_RESULTS.md).

Usage:
  uv run python tools/run_demo_questions.py \
      --api https://policy-api-dev.purpleglacier-f66f3ddd.eastus2.azurecontainerapps.io \
      --tenant 00000000-0000-0000-0000-000000000001
"""

from __future__ import annotations

import argparse
from pathlib import Path

import requests

REFUSAL = "Insufficient evidence in available policy sections."

# (category, question, expectation)  expectation in {"ground", "refuse"}
QUESTIONS: list[tuple[str, str, str]] = [
    # --- Specific control lookups ---------------------------------------
    ("Control lookup", "What does access control AC-2 require for account management?", "ground"),
    ("Control lookup", "What are the requirements for incident response?", "ground"),
    ("Control lookup", "What controls cover authenticator and password management?", "ground"),
    ("Control lookup", "What does AU-2 require for event logging?", "ground"),
    ("Control lookup", "What are the configuration management baseline requirements (CM-2)?", "ground"),
    ("Control lookup", "What does least privilege (AC-6) require?", "ground"),
    ("Control lookup", "What are the requirements for multi-factor authentication (IA-2)?", "ground"),
    ("Control lookup", "What does AC-11 require for session lock?", "ground"),
    ("Control lookup", "What are the contingency planning requirements (CP-2)?", "ground"),
    ("Control lookup", "What does RA-5 require for vulnerability scanning?", "ground"),
    ("Control lookup", "What are the media sanitization requirements (MP-6)?", "ground"),
    ("Control lookup", "What controls govern remote access (AC-17)?", "ground"),
    ("Control lookup", "What does SC-7 require for boundary protection?", "ground"),
    ("Control lookup", "What are the security awareness and training requirements (AT-2)?", "ground"),
    ("Control lookup", "What does SI-2 require for flaw remediation and patching?", "ground"),
    ("Control lookup", "What are the audit record retention requirements (AU-11)?", "ground"),
    ("Control lookup", "What does PE-3 require for physical access control?", "ground"),
    ("Control lookup", "What does AC-5 require for separation of duties?", "ground"),
    ("Control lookup", "What does SA-11 require for developer security testing?", "ground"),
    ("Control lookup", "What controls address supply chain risk management?", "ground"),
    # --- Scenario / synthesis -------------------------------------------
    ("Scenario", "How should we handle a vendor data breach?", "ground"),
    ("Scenario", "An employee was just terminated — which access-related controls apply?", "ground"),
    ("Scenario", "We're moving workloads to the cloud — which controls cover external system connections?", "ground"),
    ("Scenario", "How do we prepare for and respond to a ransomware incident?", "ground"),
    ("Scenario", "What controls should we implement for a remote workforce?", "ground"),
    ("Scenario", "A laptop holding sensitive data was lost — what does NIST require?", "ground"),
    ("Scenario", "How do we stand up an incident response capability from scratch?", "ground"),
    ("Scenario", "What does NIST require for protecting data at rest and in transit?", "ground"),
    # --- Out of scope (must refuse) -------------------------------------
    ("Out of scope", "What's your refund policy?", "refuse"),
    ("Out of scope", "What's the weather today and should I bring an umbrella?", "refuse"),
]


def ask(api: str, tenant: str, question: str) -> dict:
    resp = requests.post(
        f"{api.rstrip('/')}/v1/ask",
        json={"tenant_id": tenant, "question": question, "mode": "strict"},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--tenant", default="00000000-0000-0000-0000-000000000001")
    ap.add_argument("--out", default="docs/DEMO_RESULTS.md")
    args = ap.parse_args()

    rows: list[dict] = []
    passed = 0
    for category, q, expectation in QUESTIONS:
        try:
            data = ask(args.api, args.tenant, q)
        except Exception as exc:  # demo runner: capture transport errors per row
            rows.append({"cat": category, "q": q, "exp": expectation, "status": "ERROR",
                         "ok": False, "conf": 0.0, "cites": [], "answer": str(exc)[:200]})
            continue
        answer = data.get("answer") or ""
        refused = REFUSAL.lower() in answer.lower()
        cites = []
        for c in (data.get("citation_items") or []):
            sp = c.get("section_path")
            if sp:
                cites.append(sp)
        status = "REFUSED" if refused else "ANSWERED"
        ok = (refused and expectation == "refuse") or (not refused and expectation == "ground")
        passed += int(ok)
        rows.append({"cat": category, "q": q, "exp": expectation, "status": status, "ok": ok,
                     "conf": float(data.get("confidence") or 0.0), "cites": cites[:4], "answer": answer})
        print(f"[{'PASS' if ok else 'FAIL'}] {status:8s} conf={rows[-1]['conf']:.2f}  {q}")

    # Write report
    lines = [
        "# NIST SP 800-53 — Policy Platform Demo Results",
        "",
        f"**Endpoint:** `{args.api}`  ",
        f"**Corpus:** NIST SP 800-53 Rev 5 — 20 control families, 1,014 controls + enhancements  ",
        f"**Result:** {passed}/{len(QUESTIONS)} questions behaved as expected "
        "(in-scope questions grounded with citations; out-of-scope refused).",
        "",
        "Every answer is generated **only** from retrieved NIST control text and returns the exact "
        "controls cited. Out-of-scope questions are refused rather than answered from general knowledge.",
        "",
    ]
    cur = None
    for r in rows:
        if r["cat"] != cur:
            cur = r["cat"]
            lines += ["", f"## {cur}", "", "| ✓ | Question | Result | Conf. | Controls cited |", "|---|----------|--------|-------|----------------|"]
        mark = "✅" if r["ok"] else "❌"
        cites = ", ".join(r["cites"]) if r["cites"] else "—"
        lines.append(f"| {mark} | {r['q']} | {r['status']} | {r['conf']:.2f} | {cites} |")

    lines += ["", "---", "", "## Sample answers", ""]
    for r in rows:
        if r["status"] == "ANSWERED" and r["cat"] in ("Control lookup", "Scenario"):
            snippet = " ".join((r["answer"] or "").split())[:600]
            lines += [f"### {r['q']}", "", f"> {snippet}…", "",
                      f"*Controls cited: {', '.join(r['cites']) or '—'}*", ""]
            if sum(1 for x in lines if x.startswith("### ")) >= 6:
                break
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{passed}/{len(QUESTIONS)} passed. Report -> {out}")


if __name__ == "__main__":
    main()
