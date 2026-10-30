# Questions for the manager

We are building an AI assistant that answers questions about our billing and collections data and writes reports. To do that, it needs to know what each table and column means. We worked most of this out from the names of the tables and columns. The questions below are the ones that names can't answer, and where a wrong guess would give **wrong numbers**.

- **Part 1** matters most: business rules that decide totals such as "paid" and "outstanding".
- **Part 2** is about status and type codes, and there is a shortcut.
- **Part 3** is quickest for a developer who knows the database.
- **Part 4** asks for one permission that would answer many questions at once.

Short answers are fine. "I don't know, ask X" also helps.

---

## Part 1: Business rules

**1. What counts as "paid"?**
A payment can carry a **PPO reduction** or **another reduction** (`PAYMENT.PPOReduction`, `PAYMENT.OtherReduction`). Should "paid" mean only money received, or money received **plus** reductions?
*Why it matters:* it changes every paid and outstanding total.

**2. How is "outstanding" calculated?**
Is it *billed minus paid*? Are reductions or write-offs taken off as well? Is it measured against the billed amount or the OMFS (fee schedule) allowed amount? If the BDR uses a formula, which one?

**3. What is an "advance" payment?**
`PAYMENT.For_Advance` marks some payments as advances. What is an advance, and does it count as paid?

**4. Where is a settlement officially recorded?**
Four places look like settlements:
- the settlement offers table (`settle.SettlementOffer`);
- the amount settled on a collector's action (`ACTIONTAKEN.SETTLEDAMOUNT`);
- a settlement amount on the case (`CASEINFO.SETTLEMENT`);
- a "for settlement" mark on payments (`PAYMENT.FOR_SETTLEMENT`).

When someone asks "how much did we settle for?", which one is right? Is the case's settlement amount the amount **agreed** or **offered**?

**5. What do the case's lien and collection amounts mean?**
Each case has a **lien amount** (`CASEINFO.LIEN`) and a **collection amount** (`CASEINFO.COLLECTION`). Is the lien amount the amount filed on the lien? Is the collection amount the total collected so far, or a target?

**6. Which insurer does a case belong to?**
Insurance is recorded **per patient**, not per case. When a patient has several cases or several insurers, how do you tell which insurer belongs to which case?

**7. Which date is the "date of service"?**
A study has a study date (`STUDY_TO_BE_REQUESTED.STUDY_DATE`), and its bill has a date of service. When someone asks about "DOS", which should we use?

**8. What do these terms mean?**
- **NSP**: there is a separate NSP follow-up workflow with its own statuses and activities.
- **BDE level**: it looks like a collector's level or grade.
- **Customer firm**: the "customer firm" linked to a case (`CUSTOMER_Firm_Information`). Is it the applicant's attorney, a lien buyer, or something else?

---

## Part 2: What the codes mean

These columns store numbers or short codes. For example, a case status of 3 means something, but the database alone doesn't tell us what.

| # | Column | What it is |
|---:|---|---|
| 9 | `CASEINFO.CaseStatus` | Status of a case |
| 10 | `CASEINFO.CollectionsStatus` | Collection status of a case |
| 11 | `CASEINFO.GradeID` | Grade of a case |
| 12 | `STUDY_TO_BE_REQUESTED.STATUS` and `HISTORY_STUDY_STATUS` | Status of a study, and its history |
| 13 | `BILL.Submission_Type` | How a bill was submitted |
| 14 | `PAYMENT.PAYMENTTYPEID` | Type of payment. **There is no code list for this in the database.** |
| 15 | `ACTIONTAKEN.STATUS` | File status after a collector's action |
| 16 | `FOLLOWUP_SCHEDULES_SET.STATUS` | Follow-up open, done, etc. |
| 17 | `AutoAppeal.Status` | Status of an appeal |
| 18 | `DOR_Case_Information.Request_type` | Type of DOR request |
| 19 | `SB1160_INFO_MASTER.SB1160_REVIEW_STATUS_ID` | SB1160 review status |

**The shortcut.** Most of these codes probably have a small **code list** in the database: a table that only pairs numbers with labels such as "Billed" or "Denied", with no patient data. Our rule is that no database values are read into the project without approval, so we need your approval to read them.

> **Question 20:** May we read the small code-list tables (labels only, no patient data)? If yes, you only need to explain `PAYMENTTYPEID` (number 14) and any codes we still can't match.

---

## Part 3: For a developer

These are quick for someone who knows the database. Where nobody knows, we will try to work them out ourselves by matching counts.

| # | Question |
|---:|---|
| 21 | `CASEINFO.ATTORNEY` (the applicant's attorney): the IDs fit both the attorney list (`ATTORNEYINFORMATIONLOOKUP`) and the defense attorneys (`DEFENSEATTORNEY`). Which one is right? |
| 22 | `BILL.PHYSICIANID`: it is **not** an ID in `PHYSICIAN` (only a third match). Which table does it point to? |
| 23 | `FOLLOWUP_SCHEDULES_SET.ACTIONTAKENID` (and the NSP follow-ups): only 12% match a collector action in `ACTIONTAKEN`. What does it point to? |
| 24 | `FILEID` in `PAYMENT`, `PATIENT_DOCUMENTS` and `ACTIONTAKEN`: what "file" is this, and in which table? |
| 25 | `APPOINTMENTTYPE` (types of study) has about 961,000 rows. Is each type repeated per provider or per case? Which column is the shared type? |

*Already answered by the data, so no need to ask:* the case's primary treating physician (`CASEINFO.PTP`) is in `PHYSICIAN`; a study's invoice (`INVOICE_ID`) is in `INVOICE`; the collector on a patient or case is a user in `BUSINESSUSER`.

---

## Part 4: One permission that would help a lot

**26. May our read-only login get the `VIEW DEFINITION` permission on `EPM_For_Automation`?**

The database has 76 views, 7 procedures and 12 functions, including the ones that build the bot reports such as the BDR. Our login can see that they exist, but **can't read their code**.

With this permission we could read *how* the existing reports calculate paid, outstanding and status. That would answer many of the questions above directly. The permission lets us read code only: no data, and no changes.

---

*Not on this list, because we check them ourselves with counts and no data is shown:*
- whether a bill's amount equals the sum of its lines;
- whether pre-entered payments end up in the payments table;
- whether our numbers match the dashboard tables;
- which table each ID column points to (Step 4 confirmed about 560 links this way).
