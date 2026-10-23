# AI Reporting System: Project Guide

*Last updated: 23 Oct 2026*

This guide explains the whole project in simple words: what we are building, how it works, what is done, and what comes next. Every idea has an example.

---

## 1. The project in one minute

Today, when someone needs a number or a report from our database, they ask the IT/DB team, who write SQL by hand. That takes time, and only a few people know the database well enough.

We are building an **AI system that knows our database** (EPM). You can talk to it in plain English, and it:

1. **Answers questions.** *"What is the bill submission date for study ID 123?"*
2. **Makes reports on demand.** *"All checks posted for provider Y in September, as Excel."*
3. **Learns an existing report from its SOP or an old copy**, rebuilds it from the database, and proves it is right.
4. **Runs approved reports with one click**, every month, with no AI and no cost, only for people allowed to see them.

**The key promise: no real data ever goes to the AI.** The AI only sees table names, column names and descriptions. All the data stays on our machine.

---

## 2. What it will do, with examples

| # | Ability | What the user does | What they get |
|---|---|---|---|
| 1 | **Answer questions** | Types: *"How many studies does patient X have?"* | *"14 studies"*, plus the SQL used and an Excel download |
| 2 | **On-demand reports** | Types: *"Total billed, paid and outstanding per provider for Sept 2026"* | A full table, downloadable as Excel |
| 3 | **Learn a report from an SOP / old report** | Uploads the *Check Posting* SOP and last month's Check Posting report | The system builds the same report from the database and checks it matches, cell by cell |
| 4 | **One-click recurring reports** | Picks an approved report, picks the month, clicks **Run** | The fresh report from the latest data. No AI used. Only people on the report's access list can see it. |

### Why we call it "agentic"
A normal chatbot gives one answer and stops. Our system works like a careful junior analyst:

1. **Plans**: "Which tables do I need?"
2. **Acts**: writes the SQL and runs it.
3. **Checks**: compares the result with a trusted report.
4. **Fixes itself**: if it's wrong, it is told *what* is wrong and tries again.
5. **Asks a person** when something is unclear, e.g. *"There are two patients named John Smith. Which one?"*

---

## 3. The rules we never break

| Rule | What it means, simply |
|---|---|
| **No real data goes to the AI** | The AI sees: table names, column names, descriptions, the question. It never sees patient names, amounts, IDs or results. |
| **Ask before every paid AI call** | Every AI call costs money and is checked by management. We say how many calls, get a "yes", and stop at that number. Every call is logged in `ai_calls.csv`. |
| **One AI model only** | Nemotron 3 Ultra (via OpenRouter). |
| **Read-only** | We never change the database. Every query the AI writes is safety-checked, and only `SELECT` (read) is allowed. |

---

## 4. How it works, step by step

### 4.1 One question, from start to finish

**Example question:** *"What is the bill submission date for study ID 123?"*

| Step | What happens | Where | Example |
|---|---|---|---|
| **1. Hide names and IDs** | Our code spots names/IDs in the question and replaces them with placeholders. | Our machine | Sent onward as: *"What is the bill submission date for study ID {STUDY_ID_1}?"* |
| **2. Find likely tables** (Schema RAG) | Our code compares the question's *meaning* with the description of every table and column, and picks the 10 closest. | Our machine | Finds `Bot_BDRReport_StudyLevel`, because its column *"Bill Submission Date"* is described as *"Date the bill was submitted (sent) to the payer"*. |
| **3. AI picks the tables** | The AI gets the question + the 10 table descriptions and chooses what it needs. | AI (no data) | AI chooses `Bot_BDRReport_StudyLevel`, columns `STUDY_ID`, `Bill Submission Date`. |
| **4. Work out joins** (Schema graph) | If more than one table is needed, our code works out how they connect. | Our machine | e.g. `PAYMENT.BILLID = BILL.BILLID`. Warns if a join would double-count. |
| **5. AI writes the SQL** | The AI writes one `SELECT` query using the placeholder. | AI (no data) | `SELECT [Bill Submission Date] FROM Bot_BDRReport_StudyLevel WHERE STUDY_ID = {STUDY_ID_1}` |
| **6. Safety check and run** | Our code puts the real ID back, checks the query is read-only, and runs it. | Our machine | Result: *28 Aug 2023* |
| **7. Show the answer** | The web page shows the answer, the SQL, and an Excel download. | Our machine | *"Bill submitted on 28 Aug 2023."* |

**The AI never saw "123" or "28 Aug 2023".** It only wrote the recipe; our machine did the cooking.

### 4.2 The picture

```
  User types a question
          │
          ▼
  1. Hide names/IDs          ── our machine
          │
          ▼
  2. Schema RAG              ── our machine: finds likely tables by meaning
          │
          ▼
  3. AI picks tables         ── AI: sees descriptions only
          │
          ▼
  4. Schema graph            ── our machine: works out the joins
          │
          ▼
  5. AI writes SQL           ── AI: sees descriptions + joins only
          │
          ▼
  6. Safety check + run      ── our machine: read-only, real values put back
          │
          ▼
  7. Compare / show answer   ── our machine: web page + Excel
```

### 4.3 Learning a report from an SOP or old report

**Example:** we give it the *Check Posting* SOP plus the August and September Check Posting reports.

1. **Read the SOP.** *"Take all payments posted between the start and end date, group by provider and check number."*
2. **Find the tables** (steps 2–4 above): `PAYMENT`, `AllTransactionCPtpay_Report`, `BILL`…
3. **Write the SQL** and run it for **August**.
4. **Compare with the August report, cell by cell.** Our code does this.
5. **If different, tell the AI what is wrong, without values.** E.g. *"3 rows missing; column Total is too low in 5 rows."* The AI fixes the SQL and tries again.
6. **When August matches, test on September**, a month it has **never seen**. This proves it learned the report, not just memorised one month.
7. **A person reviews and approves** the SQL.
8. It becomes a **recurring report** (see 4.4).

### 4.4 One-click recurring reports

1. The approved SQL is saved with its **settings** (e.g. month, provider, client).
2. Each report has an **access list**: who may see and run it.
3. A user opens the web page, sees **only their allowed reports**, picks the month, clicks **Run**.
4. Our machine runs the saved SQL on the latest data and gives Excel.
5. **No AI is used here at all.** Same SQL every time, zero cost, nothing leaves the machine.

---

## 5. The building blocks, explained simply

| Building block | Simple explanation | Example |
|---|---|---|
| **Table & column descriptions** | A one-line meaning for every table and column, so the system knows what each holds. Our DB has none, so we wrote them. | `BILL` = *"One bill sent to an insurer for a study."* |
| **Schema RAG** | "Search by meaning." Finds tables even when the question uses different words. | Question says *"when was it sent"* → finds column *"Bill Submission Date"*. |
| **Schema graph** | A map: tables are dots, links are lines. Used to join tables correctly. Our DB has very few links defined, so the system **works them out** from column names. | `PAYMENT` has a `BILLID` column → it links to `BILL`. |
| **Data graph** *(planned)* | A map of actual records on our machine: patient → cases → studies → bills → payments. Fast "how many / which" answers and a double-check. Never sent to the AI. | Patient X → 3 cases → 14 studies. |
| **Value lookup** *(planned)* | Spots names and IDs in a question (even misspelled) and swaps them for placeholders before the AI sees the question. | *"Jon Smith"* → finds *JOHN SMITH* → AI sees `{PATIENT_NAME_1}`. |
| **Example bank** *(planned)* | Checked example questions with their correct SQL. The closest 3 are shown to the AI with each new question. This is how we "train" it without giving it data. | *"Total paid for provider {X} in {month}"* → its correct SQL. |
| **Answer key** *(planned)* | Test questions where our own code already knows the right answer, so we can score the AI. | 20 questions → target 18+ right. |
| **Master data** | The report tables the system already builds (BDR, Check Posting, billing dashboards). These are the trusted answers we check against. | `Bot_BDRReport_StudyLevel` |

---

## 6. What we have done so far

### Phase 0: Proved the idea on a sample database, 13–19 Oct
1. Built the whole pipeline (steps 1–7 above) on Microsoft's sample database (AdventureWorks).
2. **Result:** the AI wrote correct SQL for test reports, and they matched cell by cell, including on a month it had never seen.
3. Deleted all the sample material afterwards and kept only the reusable code.

### Phase 1 so far: Moved to our real staging database, 19–23 Oct

| # | What we did | Result, simply |
|---|---|---|
| 1 | **Connected** to staging | Server 10.0.0.244, database **EPM**, read-only. |
| 2 | **Mapped the database** | 6 schemas. The main one, `dbo`, has 414 tables, 197 views, 1,312 stored procedures. |
| 3 | **Understood the business from the data** | California workers' comp medical **billing, liens and collections**. Providers treat injured workers; we bill insurers, chase payment, file liens/appeals. |
| 4 | **Checked where staging data comes from** | Restored from a production backup (27 Nov 2023) and changed since. Real patient data, so the "no data to AI" rule matters. |
| 5 | **Read the top 10 rows of every dbo table**, with personal details masked | Enough to understand what each table holds. |
| 6 | **Wrote a description for all 414 dbo tables** | Grouped into: 85 core, 103 lookup, 15 report, 20 history, 35 other-system, and 156 we leave out (backups, empty, system). |
| 7 | **Found the report tables and the code that fills them** | BDR report, check posting, billing dashboards, file status. Saved the code of 40 stored procedures. |
| 8 | **Built the knowledge file** (`schema.json`) | 258 usable tables, 3,922 columns, with descriptions. |
| 9 | **Worked out the table links ourselves** | The DB declares only 79 links. The system found **325 more** from column names (e.g. `PAYMENT.BILLID → BILL`). Each is marked "inferred" until confirmed. |
| 10 | **Taught joins to use the main tables** | Joins go through real tables (Patient → Case → Bill → Payment), not through report copies. |
| 11 | **Built the search index** (Schema RAG) | 3,461 descriptions turned into searchable numbers, on our machine. |
| 12 | **Dry run, no AI call** | For *"check posting report"* it found the right tables (PAYMENT, AllTransactionCPtpay_Report…). The prompt holds no data, only names and descriptions. |
| 13 | **Described every column of the 4 main report tables** (23 Oct) | 189 columns: BDR report (82), Check Posting (45), Aging summary (33), Billing dashboard (29). E.g. *"Soldate = statute of limitations date."* Search index being rebuilt to use them. |

### How the main tables connect (our understanding so far)
```
BUSINESSINFO (provider / client)
  └─ PATIENT (injured worker)
       └─ CASEINFO (workers' comp case, ADJ number)
            ├─ INSURANCE, EMPLOYER, attorney
            └─ STUDY_TO_BE_REQUESTED (one service, e.g. an MRI)
                 └─ BILL ─ BILLCPTCODE (bill lines) ─ PAYMENT (money received)
Work on a file:  ACTIONTAKEN, follow-ups, calls, VERIFICATION
Paperwork:       PATIENT_DOCUMENTS ─ DOCUMENT_DETAILS
Disputes:        SBR_Information, AutoAppeal, OBJECTION, DOR
```

### The CIO's direction (21 Oct)
- No ERDs from the DB team: **the AI works out the tables and links**, and the CIO checks the result.
- **The system's own report tables are the master data** (the trusted answers).
- **"Check with me" = show a working POC.**

---

## 7. The POC plan, step by step

### What the POC must show the CIO
A web page where someone asks questions about the **BDR report** (`Bot_BDRReport_StudyLevel`) and gets correct answers:

| Type of question | Example |
|---|---|
| Look up a name from an ID | "What is the patient name for study ID X?" |
| Count for a name | "How many study IDs does patient X have?" |
| List for a name | "Which providers has patient X been seen by?" |
| Look up a date or status | "What is the bill submission date and status for study ID X?" |
| Totals | "Total billed, paid and outstanding for provider Y in Sept 2026." |
| Counts by group | "How many studies per bill submission status last month?" |

Each answer shows the **SQL used** and offers an **Excel download**, and is checked against our answer key.

### Phase 1: Foundation + BDR question POC *(we are here)*

**1A. Schema RAG: find the right tables and columns**
- [x] Descriptions for every dbo table.
- [x] `schema.json` for EPM (258 usable tables).
- [x] Search index, built on our machine.
- [x] Describe every column of the 4 main report tables (189 columns). *(23 Oct)*
- [ ] Rebuild the search index and check that "submission date", "patient name", "study ID" find the BDR table first. *(running)*

**1B. Schema graph: know how tables join**
- [x] 79 declared + 325 inferred links; joins prefer main tables.
- [ ] Check each inferred link against the data with our own code (e.g. do 99% of `PAYMENT.BILLID` values exist in `BILL`?). Mark it *confirmed* or *rejected*.
- [ ] Use the stored-procedure code to confirm how report tables are built from main tables.

**1C. Data graph: how the records connect** *(our machine only)*
- [ ] Build the patient → case → study → bill → payment map.
- [ ] Use it for quick "how many / which" answers and to double-check SQL answers.

**1D. Value lookup: recognise names and IDs** *(our machine only)*
- [ ] Local searchable list of patient, provider, insurer names and IDs, with fuzzy matching ("Jon Smith" → "JOHN SMITH").
- [ ] Swap them for placeholders before the AI sees the question. If a name matches several people, ask the user.

**1E. Print the reports: reproduce the master data**
- [ ] Start with BDR, Check Posting, AR/aging.
- [ ] Our code produces each for a month as Excel, straight from the report tables.
- [ ] Note the settings each report needs (month, provider, client, status).

**1F. Teach the AI: the example bank**
- [ ] Glossary of business words added to the prompt where relevant.
- [ ] ~30 example BDR questions with correct SQL, written and checked by us.
- [ ] Add the 3 closest examples to each AI prompt.
- [ ] Add every answer the CIO approves to the bank.

**1G. Answer key** *(no AI calls)*
- [ ] ~20 test questions covering every row of the POC table above.
- [ ] Our code computes the correct answer for each.

**1H. Test the agent** *(paid AI calls: ask first)*
- [ ] Free dry run: build every prompt and check none holds a real value.
- [ ] Agree the number of calls, run the test, measure how many are right.
- [ ] Fix what fails and re-test. Target: **at least 18 of 20 right**.

**1I. Demo to the CIO**
- [ ] Web page: question box, answer, SQL, Excel download.
- [ ] The CIO tries their own BDR questions; corrections go into the example bank.

**Phase 1 is done when:** the CIO asks their own BDR questions and gets correct answers, and no real data has gone to the AI.

### Phase 2: On-demand reports + SOP / old-report upload
- [ ] Ask for a full report in plain English and download it as Excel.
- [ ] Upload an SOP and/or old reports; the agent builds the report, compares cell by cell, fixes itself, passes a second unseen month.
- [ ] A person reviews and approves the SQL.
- [ ] Grow beyond the report tables to main tables for questions the reports don't cover.

### Phase 3: Recurring reports with access control
- [ ] Save each approved report: fixed SQL + its settings.
- [ ] Access list per report: who may see and run it.
- [ ] One click: pick settings, get the report from the latest data. **No AI** in this step.

---

## 8. What's next (in order)

1. **Finish 1A:** confirm the search now finds the BDR table for "submission date", "patient name", "study ID".
2. **1B:** check the 325 inferred links against the data, so we know which are real.
3. **1E:** produce the BDR, Check Posting and AR reports as Excel from the report tables.
4. **1G + 1F:** write the 20 test questions with answers, and 30 example questions with SQL.
5. **1D:** value lookup, so names and IDs never reach the AI.
6. **1H:** first paid test run (after agreeing the number of calls).
7. **1I:** demo to the CIO.

**Decision needed from the CIO/manager:** some table descriptions contain status words taken from the data (e.g. *"Accepted, Closed, Denied"*). They are not patient data, and they help the AI pick the right column. May they be sent to the AI, or should we strip them?

---

## 9. Talking points for the CIO meeting

- **What it is:** an AI that knows our database and turns plain-English questions into correct SQL, then reports.
- **Safety:** the AI never sees data, only table/column names and descriptions. Read-only. Every call logged and capped.
- **Following your direction:** no ERDs needed. The system mapped the database itself: 414 tables described, 325 links found automatically. Your review confirms them.
- **Trust:** every answer is checked against the system's own report tables (BDR, Check Posting, billing dashboards). A report is only accepted after it matches on a month it has never seen.
- **Done:** connected, database mapped and described, search and join engine built on EPM, report tables understood.
- **Next:** BDR question POC with a 20-question test (target 18+ right), then a web demo for you to try.
- **Ask:** confirm the descriptions/links where possible, and the status-words decision above.

**Likely questions:**
- *"Is our data safe?"* Yes. The AI gets descriptions only; names and IDs in a question are replaced with placeholders; all data stays on our machine.
- *"How do we know it's right?"* It is scored against answers our own code computes from the trusted report tables, and reports must match two different months.
- *"What does it cost?"* Only the AI calls while building/answering; each is a few thousand words of descriptions. Approved recurring reports cost nothing to run.
- *"Why not just give the AI the data?"* Patient data (PHI). We teach it with descriptions and checked examples instead.

---

## 10. Glossary (business words)

| Term | Meaning |
|---|---|
| **Workers' comp (WC)** | Insurance that pays medical bills for people injured at work. |
| **Provider** | The clinic or imaging centre that treated the patient. Our client. `BUSINESSREGID`. |
| **Study** | One service performed, e.g. one MRI. `STUDY_ID`. |
| **CPT code** | Code for a medical procedure, e.g. 72148 = MRI lower spine. |
| **ICD code** | Code for a diagnosis. |
| **HCFA 1500** | The standard claim form for a medical bill. |
| **EDI** | Sending bills electronically instead of on paper. |
| **Clearinghouse** | Middleman that passes electronic bills to insurers. |
| **Bill submission** | Sending the bill. Original = first time, ReBill = sent again. |
| **EOR / EOB** | The insurer's reply saying what it paid and why. |
| **OMFS** | Official Medical Fee Schedule: the state's price list. |
| **SBR** | Second Bill Review: disputing an insurer's payment decision. |
| **Lien** | Legal claim filed to get paid from the injured worker's case. |
| **EAMS / ADJ number** | California's workers' comp case system / the case number in it. |
| **WCAB** | Workers' Compensation Appeals Board: the court for these cases. |
| **DOR** | Declaration of Readiness: request for a hearing. |
| **C&R** | Compromise & Release: a settlement of the case. |
| **SOL date** | Statute of limitations: the last date to act on a bill. |
| **AR** | Accounts Receivable: money billed but not yet collected. |
| **BDR report** | Billing detail report, one row per study (`Bot_BDRReport_StudyLevel`). |
| **SQL** | The language used to ask a database for data. |
| **Schema** | The structure of a database: its tables, columns and links. |

---

## 11. Files and commands (for the technical side)

### Code (in git)
| File | What it does |
|---|---|
| `db.py` | The one database connection (details in `.env`). |
| `explore_db.py` | Lists schemas, tables, columns, keys and row counts. No data. |
| `sample_tables.py` | Reads top 10 rows per table with personal details masked. |
| `find_procs.py` | Finds the stored procedures that fill given tables and saves their code. |
| `extract_schema.py` | Builds `schema.json`: tables, descriptions, column descriptions, declared + inferred links. |
| `schema_search.py` | Schema RAG: finds tables by meaning. |
| `schema_graph.py` | Schema graph: works out joins and warns about double-counting. |
| `pick_tables.py` | AI picks the tables a question needs. |
| `build_report.py` | AI writes the SQL, we test it, it retries until correct. |
| `sql_runner.py` / `sql_checks.py` | Safety check, then run (read-only). |
| `compare.py` | Compares a result with the expected report, without showing values to the AI. |
| `review_report.py` / `run_report.py` | A person approves the SQL; it then runs with no AI. |
| `web_app.py` | The demo web page. |
| `llm.py` | The one AI connection, every call logged. |

### Outputs (our machine only, never in git)
| File | What it holds |
|---|---|
| `.env` | Database login and AI key. **Secret.** |
| `EPM/dbo/descriptions.md` / `.json` | Description of all 414 dbo tables. |
| `EPM/dbo/column_descriptions.json` | Column descriptions for the report tables. |
| `EPM/dbo/procs/` | Code of the procedures that build the report tables. |
| `EPM/dryrun/` | Dry-run prompts and search tests. |
| `ai_calls.csv` | Log of every paid AI call. |

### Common commands
```
python explore_db.py all        # refresh the catalog of all schemas
python extract_schema.py        # rebuild schema.json after editing descriptions
python web_app.py               # demo page at http://localhost:5000
```

---

## 12. Things to be aware of

- **Descriptions are first guesses**, written from names, masked samples and procedure code. They need confirming by a senior or the CIO.
- **Report tables are snapshots** rebuilt by jobs or a bot, so answers are "as of the last refresh".
- **Passwords are stored in plain text in some tables** (`SERVER_INSTANCES`, `RC_Accounts`, `BUSINESSUSER`). Worth telling IT/security.
- **Known limit of the join map:** when two routes between tables are equally short, it can't tell which one the business means (e.g. bill → insurer via the patient's insurance vs. via an objection). Checking links against the data (1B), the two-month test and human approval catch this.
