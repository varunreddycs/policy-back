# NIST SP 800-53 — Policy Platform Demo Results

**Endpoint:** `https://policy-api-dev.purpleglacier-f66f3ddd.eastus2.azurecontainerapps.io`  
**Corpus:** NIST SP 800-53 Rev 5 — 20 control families, 1,014 controls + enhancements  
**Result:** 30/30 questions behaved as expected (in-scope questions grounded with citations; out-of-scope refused).

Every answer is generated **only** from retrieved NIST control text and returns the exact controls cited. Out-of-scope questions are refused rather than answered from general knowledge.


## Control lookup

| ✓ | Question | Result | Conf. | Controls cited |
|---|----------|--------|-------|----------------|
| ✅ | What does access control AC-2 require for account management? | ANSWERED | 0.99 | AC-2, AC-2(7), AC-2(1), AC-2(8) |
| ✅ | What are the requirements for incident response? | ANSWERED | 0.67 | IR-8, IR-4, IR-4(11), IR-2 |
| ✅ | What controls cover authenticator and password management? | ANSWERED | 0.60 | IA-5, IA-5(18), IA-5(6), IA-7 |
| ✅ | What does AU-2 require for event logging? | ANSWERED | 0.99 | AU-2, AU-3, SA-15(13), AU-12 |
| ✅ | What are the configuration management baseline requirements (CM-2)? | ANSWERED | 0.99 | CM-2, CM-2(6), CM-9, CM-2(2) |
| ✅ | What does least privilege (AC-6) require? | ANSWERED | 0.99 | AC-6, SA-8(14), SA-17(7), AC-6(10) |
| ✅ | What are the requirements for multi-factor authentication (IA-2)? | ANSWERED | 0.99 | IA-2, IA-2(1), IA-2(2), IA-2(6) |
| ✅ | What does AC-11 require for session lock? | ANSWERED | 0.99 | AC-11, AC-12, AC-10, AC-12(1) |
| ✅ | What are the contingency planning requirements (CP-2)? | ANSWERED | 0.99 | CP-2, CP-2(2), CP-2(6), CP-2(5) |
| ✅ | What does RA-5 require for vulnerability scanning? | ANSWERED | 0.99 | RA-5, RA-5(5), RA-5(2), RA-5(6) |
| ✅ | What are the media sanitization requirements (MP-6)? | ANSWERED | 0.99 | MP-6, MP-7(2), MP-6(1), MP-6(3) |
| ✅ | What controls govern remote access (AC-17)? | ANSWERED | 0.99 | AC-17, AC-17(1), AC-17(4), AC-18 |
| ✅ | What does SC-7 require for boundary protection? | ANSWERED | 0.99 | SC-7, SC-7(12), SC-7(18), SC-7(26) |
| ✅ | What are the security awareness and training requirements (AT-2)? | ANSWERED | 0.99 | AT-2, AT-3, AT-1, AT-3(2) |
| ✅ | What does SI-2 require for flaw remediation and patching? | ANSWERED | 0.99 | SI-2, SI-2(2), SI-2(3), SI-2(4) |
| ✅ | What are the audit record retention requirements (AU-11)? | ANSWERED | 0.99 | AU-11, AU-11(1), AU-4, AU-3 |
| ✅ | What does PE-3 require for physical access control? | ANSWERED | 0.99 | PE-3, PE-3(1), PE-2, PE-2(3) |
| ✅ | What does AC-5 require for separation of duties? | ANSWERED | 0.99 | AC-5, CM-5(4), AC-3(2), AU-9(5) |
| ✅ | What does SA-11 require for developer security testing? | ANSWERED | 0.99 | SA-11, SA-11(9), SA-11(5), SA-11(1) |
| ✅ | What controls address supply chain risk management? | ANSWERED | 0.58 | PM-30, SR-3, SR-5, SR-2 |

## Scenario

| ✓ | Question | Result | Conf. | Controls cited |
|---|----------|--------|-------|----------------|
| ✅ | How should we handle a vendor data breach? | ANSWERED | 0.44 | IR-8(1), IR-2(3), IR-4(10), IR-6(3) |
| ✅ | An employee was just terminated — which access-related controls apply? | ANSWERED | 0.64 | PS-4, PS-4(2), PS-4(1), PS-6(3) |
| ✅ | We're moving workloads to the cloud — which controls cover external system connections? | ANSWERED | 0.50 | SC-7, SC-7(3), AC-20, SA-9 |
| ✅ | How do we prepare for and respond to a ransomware incident? | ANSWERED | 0.48 | IR-4, IR-8, IR-2(3), IR-4(11) |
| ✅ | What controls should we implement for a remote workforce? | ANSWERED | 0.50 | AC-17(1), AC-17, PE-17, SC-15 |
| ✅ | A laptop holding sensitive data was lost — what does NIST require? | ANSWERED | 0.46 | IR-2(3), AC-7(2), MP-6, IR-8(1) |
| ✅ | How do we stand up an incident response capability from scratch? | ANSWERED | 0.59 | IR-8, IR-4(11), IR-4, IR-4(9) |
| ✅ | What does NIST require for protecting data at rest and in transit? | ANSWERED | 0.53 | SC-28, SC-28(1), SC-8(1), SC-12(2) |

## Out of scope

| ✓ | Question | Result | Conf. | Controls cited |
|---|----------|--------|-------|----------------|
| ✅ | What's your refund policy? | REFUSED | 0.00 | — |
| ✅ | What's the weather today and should I bring an umbrella? | REFUSED | 0.00 | — |

---

## Sample answers

### What does access control AC-2 require for account management?

> Access control **AC-2 Account Management** requires the organization to: - **Define and document** the types of system accounts that are allowed and prohibited. - **Assign account managers** responsible for account oversight. - **Establish prerequisites and criteria** for group and role membership. - **Specify for each account**: - Authorized users, - Group and role memberships, - Access authorizations (privileges) and required attributes. - **Require approvals** by designated personnel or roles for account creation (and related account actions). In addition, related enhancements to AC-2 requi…

*Controls cited: AC-2, AC-2(7), AC-2(1), AC-2(8)*

### What are the requirements for incident response?

> The requirements for incident response include the following components: **1. Incident Response Plan (IR-8)** The organization must develop and maintain an incident response plan that: - Provides a roadmap for implementing the incident response capability. - Describes the structure and organization of the capability. - Explains how the capability fits within the overall organization. - Meets the organization’s mission, size, structure, and functional requirements. - Defines reportable incidents. - Establishes metrics for measuring the effectiveness of the incident response capability. [policy_…

*Controls cited: IR-8, IR-4, IR-4(11), IR-2*

### What controls cover authenticator and password management?

> Authenticator and password management are primarily covered by the **IA-5 control family and its enhancements**, which address the lifecycle, protection, and secure handling of authenticators (including passwords): - **IA-5 Authenticator Management** requires identity verification during issuance, establishing initial authenticator content, ensuring sufficient strength, and implementing procedures for distribution, replacement, revocation, and handling of compromised authenticators. → [policy_version_id=c96ebc80-377a-5bb8-a0b4-17e328c37249 section_id=d3fee2b0-16c6-56f1-bfa3-57185e685047] - **I…

*Controls cited: IA-5, IA-5(18), IA-5(6), IA-7*

### What does AU-2 require for event logging?

> AU-2 (Event Logging) requires the organization to: - **Identify the types of events** the system is capable of logging in support of the audit function (organization-defined event types). - **Coordinate with other organizational entities** that require audit-related information to help guide and inform the selection of events to be logged. - **Specify which event types will be logged**, selecting a defined subset of the identified event types, along with the frequency or situations in which those events are to be logged. **Cited Sections:** - [policy_version_id=253f933e-ab1a-5df7-ae8b-26355d7f…

*Controls cited: AU-2, AU-3, SA-15(13), AU-12*

### What are the configuration management baseline requirements (CM-2)?

> The configuration management baseline requirements (CM-2) are: - **Develop, document, and maintain** a current baseline configuration of the system under configuration control. - **Review and update** the baseline configuration: - At an organization-defined frequency; - When required due to organization-defined circumstances; and - When system components are installed or upgraded. Enhancements to CM-2 further require: - **Maintain separate baseline configurations** for development and test environments, managed separately from the operational baseline. - **Use automated mechanisms** (organizat…

*Controls cited: CM-2, CM-2(6), CM-9, CM-2(2)*

### What does least privilege (AC-6) require?

> Least privilege (AC-6) requires the organization to employ the principle of least privilege by allowing only those authorized accesses for users (or processes acting on behalf of users) that are necessary to accomplish assigned organizational tasks. It also requires applying least privilege to system processes, ensuring they operate at privilege levels no higher than necessary to perform organizational missions or business functions. **Cited Sections:** - [policy_version_id=8d6e7d09-5737-5637-bf20-08c0e163eaa6 section_id=5b25284b-d31b-5bcc-b4a9-405607365dc5] (AC-6)…

*Controls cited: AC-6, SA-8(14), SA-17(7), AC-6(10)*
