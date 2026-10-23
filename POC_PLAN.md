# POC Plan: Phase by Phase

*Started: 22 Oct 2026. This is the plan we follow. Tick each box when it is done.*
*Background, rules and file list: see [PROJECT_GUIDE.md](PROJECT_GUIDE.md).*

---

## The goal in one line
An **agentic system that knows our EPM database**, so anyone can ask it a question in plain English and get the right answer from the data, and later build and run reports.

## What the POC must show the CIO
A web page where someone types questions about the **BDR report** (`Bot_BDRReport_StudyLevel`) and gets correct answers:

| Type of question | Example |
|---|---|
| Look up a name from an ID | "In the BDR report, what is the patient name for study ID X?" |
| Count for a name | "How many study IDs does patient X have?" |
| List for a name | "Which providers has patient X been seen by?" |
| Look up a date or status | "What is the bill submission date and status for study ID X?" |
| Totals | "Total billed, paid and outstanding for provider Y in Sept 2026." |
| Counts by group | "How many studies per bill submission status last month?" |

For each answer it also shows the **SQL it used** and offers an **Excel download**. Every answer is checked against an answer key our own code computed.

---

## The rule that shapes everything
**No real data goes to the AI.** The AI only sees table names, column names, descriptions and the question. That affects two things in this plan:

1. **Names and IDs in the question are hidden from the AI.** If someone asks *"How many study IDs does John Smith have?"*, our code finds "John Smith" on this machine, swaps it for a placeholder, and sends the AI *"How many study IDs does {PATIENT_NAME_1} have?"*. The AI writes SQL with the placeholder, and our code puts the real name back before running it.
2. **"Training the AI" does not mean giving it our data.** We do not fine-tune the model on rows. We *teach* it with things that hold no data: column descriptions, the business glossary, and a bank of **checked example questions with their correct SQL**. When a new question comes in, the most similar examples are added to the prompt. Over time the bank grows and the answers get more accurate.

---

## Phase 1: The foundation, plus the BDR question POC *(we are here)*

Build every piece the agent needs to "know" the database, make the report tables print correctly, teach the AI, and then show Q&A on the BDR report.

### 1A. Schema RAG: find the right tables and columns by meaning
- [x] Descriptions for every dbo table (`EPM/dbo/descriptions.md`).
- [x] `schema.json` for EPM (258 usable tables).
- [x] Search index (embeddings of descriptions, built on this machine).
- [x] Describe every **column** of the 4 main report tables (189 columns, incl. all 82 of `Bot_BDRReport_StudyLevel`). *(23 Oct, no AI calls)*
- [ ] Rebuild the search index and check that "submission date", "patient name", "study ID" now find the BDR table first.

### 1B. Schema graph: know how tables join
- [x] 79 declared links + 325 inferred links, joins prefer core tables.
- [ ] Check the inferred links against the data with our own code (e.g. do 99% of `PAYMENT.BILLID` values exist in `BILL`?). Mark each link *confirmed* or *rejected*.
- [ ] Use the stored-procedure code in `EPM/dbo/procs/` to confirm how the report tables are built from core tables.

### 1C. Data graph: know how the records connect *(on this machine only)*
A map of the actual records: patient → cases → studies → bills → payments, and patient ↔ provider.
- [ ] Build it from the BDR table and core tables, store it locally.
- [ ] Use it to answer "how many / which" questions quickly, and to double-check the SQL answers.
- Never sent to the AI.

### 1D. Value lookup: recognise names and IDs in a question *(on this machine only)*
- [ ] Local index of searchable values (patient names, provider names, insurer names, study IDs, case IDs), with **fuzzy matching** so "Jon Smith" finds "JOHN SMITH".
- [ ] Use it to spot names and IDs in a question and swap them for placeholders (see the rule above). If a name matches several people, ask the user which one.
- [ ] The values are matched by a local model or simple text matching. **They are never sent to an AI API.**

### 1E. Print the reports: prove we can reproduce the report tables
- [ ] Pick the reports to start with: BDR, Check Posting (`AllTransactionCPtpay_Report`), AR / aging (billing dashboards).
- [ ] Our code produces each report for a month as Excel, straight from the report tables. These are the trusted "master data".
- [ ] Note which settings each report needs (month, provider, client, status).

### 1F. Teach the AI: the example bank
- [ ] Glossary of business words (BDR, SBR, DOR, OMFS, L3A/L3B, lien…) added to the prompt where relevant.
- [ ] Write ~30 example questions about the BDR report, with the correct SQL. We write and check these ourselves.
- [ ] Our code searches the bank and adds the 3 closest examples to each AI prompt.
- [ ] Each answer the CIO approves during testing is added to the bank.

### 1G. Answer key *(no AI calls)*
- [ ] ~20 test questions covering every row of the POC table above, using placeholders for names and IDs.
- [ ] Our code computes the correct answer for each from the BDR table and stores it locally.

### 1H. Test the agent *(paid AI calls: ask first)*
- [ ] Free dry run: build every prompt without calling the AI, and check that none of them holds a real value.
- [ ] Agree the number of calls, run the test questions, measure how many are right.
- [ ] Fix what fails (column descriptions, examples, glossary) and re-test. Target: **at least 18 of 20 right**.

### 1I. Demo to the CIO
- [ ] Web page: question box, answer, SQL used, Excel download.
- [ ] CIO tries his own BDR questions. Record what he corrects, and add the fixes to the example bank.

**Phase 1 is done when:** the CIO asks his own BDR questions and gets correct answers, and no real data has gone to the AI.

---

## Phase 2: On-demand reports and SOP / old-report upload *(after the POC)*
- [ ] Ask for a full report in plain English ("all checks posted for provider Y in Sept, by case") and download it as Excel.
- [ ] Upload an SOP and/or old reports. The agent builds the report, compares it cell by cell with the old report, fixes itself, and passes a second month it has never seen.
- [ ] A person reviews and approves the SQL.
- [ ] Grow beyond the report tables to core tables for questions the reports don't cover.

## Phase 3: Recurring reports with access control *(after Phase 2)*
- [ ] Save each approved report as a recurring report: fixed SQL plus its settings.
- [ ] Access list per report: who may see and run it.
- [ ] One click: pick the settings, get the report from the latest data. **No AI** in this step.

---

## Progress log
| Date | What was done |
|---|---|
| 22 Oct 2026 | POC plan written. 1A and 1B partly done in earlier work (see PROJECT_GUIDE.md, Phase 3). |
| 23 Oct 2026 | Column descriptions for the 4 main report tables; search index rebuild started. |
