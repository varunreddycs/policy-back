# Policy Platform — NIST SP 800-53 Demo Questions

A curated set for live demos. The corpus is the **public-domain NIST SP 800-53
Rev 5** catalog — 20 control families, 1,014 controls and enhancements — so every
answer is grounded in a recognizable, authoritative standard.

What to highlight while demoing:
- **Grounded answers, every time** — responses are synthesized *only* from
  retrieved control text, and the exact controls used are returned as citations.
- **It reaches across controls** — broad/scenario questions pull together
  several related controls (e.g. incident response + supply chain for a vendor breach).
- **It says "I don't know"** — out-of-scope questions are refused instead of
  being answered from the model's general knowledge. This is the compliance-grade
  behavior that separates this from a generic chatbot.

---

## 1. Direct control lookups (precise grounding)

1. What does access control AC-2 require for account management?
2. What are the requirements for incident response?
3. What controls cover authenticator and password management?
4. What does AU-2 require for event logging?
5. What are the configuration management baseline requirements (CM-2)?
6. What does least privilege (AC-6) require?
7. What are the requirements for multi-factor authentication (IA-2)?
8. What does AC-11 require for session lock?
9. What are the contingency planning requirements (CP-2)?
10. What does RA-5 require for vulnerability scanning?
11. What are the media sanitization requirements (MP-6)?
12. What controls govern remote access (AC-17)?
13. What does SC-7 require for boundary protection?
14. What are the security awareness and training requirements (AT-2)?
15. What does SI-2 require for flaw remediation and patching?
16. What are the audit record retention requirements (AU-11)?
17. What does PE-3 require for physical access control?
18. What does AC-5 require for separation of duties?
19. What does SA-11 require for developer security testing?
20. What controls address supply chain risk management?

## 2. Real-world scenarios (synthesis across controls)

21. How should we handle a vendor data breach?
22. An employee was just terminated — which access-related controls apply?
23. We're moving workloads to the cloud — which controls cover external system connections?
24. How do we prepare for and respond to a ransomware incident?
25. What controls should we implement for a remote workforce?
26. A laptop holding sensitive data was lost — what does NIST require?
27. How do we stand up an incident response capability from scratch?
28. What does NIST require for protecting data at rest and in transit?

## 3. Out of scope (the system refuses)

29. What's your refund policy?
30. What's the weather today and should I bring an umbrella?

---

**Latest run:** 30/30 behaved as expected (28 grounded with citations, 2 refused).
See [DEMO_RESULTS.md](DEMO_RESULTS.md) for the full results table and sample answers.

The first eight questions are also one-click chips on the live console, so a
viewer can drive the demo themselves.
