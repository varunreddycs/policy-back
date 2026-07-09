# MistrV Policy Platform — Project Summary

**A compliance-grade policy intelligence engine.** Ask a plain-English question
about your security and compliance obligations and get a precise answer that is
grounded *only* in your authoritative policy text — with the exact controls cited
and a full audit trail. Built to be trustworthy enough for regulated work, not a
generic chatbot bolted onto a document store.

- **Live console:** https://platform.mistrv.com
- **Reference corpus:** NIST SP 800-53 Rev 5 — 20 control families, 1,014 controls + enhancements

---

## What makes it different

| Generic AI chatbot | MistrV Policy Platform |
|--------------------|------------------------|
| Answers from the model's general training | Answers **only** from retrieved policy text |
| "Sounds right," no provenance | Every answer returns the **exact controls cited** |
| Confidently makes things up | **Refuses** when the evidence isn't there |
| No record of what was asked/answered | Every query is **audit-logged** |
| One-size-fits-all | Department- and authority-aware ranking, version control |

The behavior that matters most to a compliance owner: **when the platform doesn't
have grounding, it says so** instead of inventing an answer. In the latest demo
run, all 28 in-scope questions were answered with citations and both out-of-scope
questions were correctly refused — **30/30**.

## How it works

```
Question ─▶ Vector retrieval (semantic + exact control-ID match)
          ─▶ Authority/recency ranking
          ─▶ Grounded LLM synthesis (cite-or-refuse)
          ─▶ Answer + citations + confidence + audit record
```

1. **Retrieve** — the question is embedded and matched against every policy
   section using vector search; questions that name a specific control (e.g.
   "AC-2") surface that control exactly.
2. **Rank** — evidence is ordered by relevance, authority level, and whether the
   policy is the current version.
3. **Answer** — an LLM synthesizes a response *constrained to the retrieved
   evidence*; if nothing relevant clears the confidence threshold, it refuses.
4. **Cite & record** — the controls used are returned as citations and the whole
   exchange is written to an immutable audit log.

## Capabilities

- **Multi-format ingestion** — PDF / DOCX / TXT, parsed into sections, versioned,
  and embedded automatically through a background worker.
- **Semantic + exact retrieval** — vector search with a control-ID boost so
  "what does AC-2 require" returns AC-2, not just topically-similar controls.
- **Grounded, cited answers** — synthesized from evidence, never from general
  knowledge, with the source controls attached.
- **Refusal on insufficient evidence** — a tunable confidence threshold keeps
  out-of-scope questions from being answered.
- **Cross-references** — the platform extracts and resolves references between
  policy sections (e.g. "see Section 3.2", "per HIPAA §164").
- **Audit & governance** — every question, answer, and citation set is logged.
- **Versioning** — policies carry version lineage; "current version only" is the default.

## Architecture

A cloud-native, fully managed stack on Microsoft Azure:

| Layer | Technology |
|-------|-----------|
| Frontend | React + MUI, Azure Static Web Apps |
| API | FastAPI on Azure Container Apps |
| Background worker | Queue-driven extraction/embedding worker (Azure Container Apps) |
| Database | Azure Cosmos DB (NoSQL) with a DiskANN cosine vector index |
| Embeddings & LLM | Azure OpenAI (`text-embedding-3-large`, GPT chat) |
| Storage / queue | Azure Blob Storage + Storage Queues |
| Secrets | Azure Key Vault via managed identity |
| Infra & CI/CD | Bicep (IaC) + GitHub Actions (OIDC, no stored cloud passwords) |

The data layer is abstracted behind a repository interface, so the same
application code runs on either Cosmos DB or PostgreSQL/pgvector — the platform is
not locked to one database.

## Engineering quality

- **Infrastructure as Code** — the entire cloud footprint is defined in Bicep and
  deployed through a one-command pipeline.
- **Passwordless CI/CD** — GitHub Actions authenticates to Azure via OIDC
  federation; no cloud credentials are stored in the repo.
- **Tested** — unit-tested retrieval, ranking, citation, and worker logic, plus an
  end-to-end demo harness that runs the full question set against the live API.
- **Reproducible corpus** — the NIST 800-53 catalog is loaded from its
  public-domain OSCAL source by a committed seed tool.

---

*MistrV — https://mistrv.com*
