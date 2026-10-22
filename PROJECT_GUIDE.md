# AI Reporting POC: Project Guide

*Last updated: 22 Oct 2026*

---

## 1. What we are building

An **intelligent, agentic system that knows our database**. It is not just a report builder. It learns what our tables and columns mean and how they connect, and then it can:

| # | What it does | Example |
|---|---|---|
| 1 | **Answer questions** in plain English | "What is the bill submission date for case X?" |
| 2 | **Make reports on demand** | "Give me all checks posted for provider Y last month, as Excel." |
| 3 | **Understand an uploaded SOP or old report** and rebuild that report from the database | We upload the Check Posting SOP and last month's report; it works out how to make it. |
| 4 | **Recurring reports: one click, access controlled** | Once a report from #3 is approved, an allowed user clicks it, picks the month or other settings, and gets a fresh report from the latest data. |

It works out for itself which tables to use, writes the SQL, tests its own work and fixes it until it is correct.

### The knowledge base: it knows our database
Everything above rests on this. The system keeps a description of every table and column, the links between tables, and the business words (see the glossary). Our software builds this by reading the database structure on this machine. The AI only ever sees names and descriptions, never data values.

### Recurring reports: how the one-click part works
1. A user uploads an **SOP** and/or **old reports** (Job 1 below).
2. The system builds the report, checks it against the old reports, and a person **approves** it.
3. The approved report is saved as a **recurring report**: fixed SQL plus its **settings** (e.g. month, provider, client).
4. **Access control (ACL):** each recurring report has a list of who may run it. A user only sees the reports they are allowed to.
5. The user clicks **Run**, changes a setting if they want, and gets the report from the **latest data**, as Excel. **No AI is used** in this step: same SQL every time, no cost, no data leaves the machine.

### Job 1: Build a report from an SOP or an old report
Give it what a person would get: the **SOP** (the written steps for making the report) and/or an **old copy of the report**. It builds a query that produces that report from the database, and **proves it is right** before anyone relies on it.

> **Example:** we hand it the *Check Posting report* SOP and last month's Check Posting report.
> 1. It reads the SOP and finds the tables it needs (payments, checks, cases, providers).
> 2. It writes the SQL and runs it for last month.
> 3. Our code compares the result with the old report, **cell by cell**.
> 4. If anything differs, it is told *what* is wrong (e.g. "3 rows missing, total too low"). It is never shown the values. It fixes the SQL and tries again.
> 5. When it matches, it is tested on a **second month it has never seen**. Only if that also matches is the report accepted.
> 6. A person reviews and approves it. It becomes a **one-click recurring report** for the users allowed to run it: same SQL, latest data, no AI, no cost.

### Job 2: Answer questions and make on-demand reports
> **Question:** someone types *"What is the bill submission date for case X?"*
> It finds the right table, writes the SQL, runs it, and shows the answer: *"*"28 Aug 2023, Original submission, Accepted by Clearinghouse."*lt;date*"28 Aug 2023, Original submission, Accepted by Clearinghouse."*gt;, Original submission, Accepted by Clearinghouse."*
>
> **On-demand report:** someone types *"All checks posted for provider Y in September, by case."*
> Same steps, but the result is a full table they can download as Excel. If they like it, it can be saved and approved as a recurring report.

### Why "agentic"
It is not one AI answer. It is a loop where the system **plans** (which tables), **acts** (writes and runs SQL), **checks** (compares with the trusted report) and **corrects itself**, and it **asks a person** when something is unclear or the SOP and the old report disagree.

This is a **proof of concept (POC)** to show the CIO and management that it works on our real data.

---

## 2. The rules we never break

| Rule | What it means in practice |
|---|---|
| **No real data goes to the AI** | The AI only sees table names, column names, descriptions and the user's question. It never sees patient names, amounts, rows or results. Our own software reads the data on this machine. |
| **Ask before every paid AI call** | The AI (Nemotron) is paid for and every call is checked by management. Before any run: say how many calls, get a "yes", stop at that number. Every call is logged in `ai_calls.csv`. |
| **Nemotron only** | Nemotron 3 Ultra through OpenRouter. No other AI model. |
| **Read-only** | We only read from the database. The connection is read-only, and any SQL the AI writes is checked and rolled back. |

---

## 3. How it works (architecture)

```
  User types a question
          │
          ▼
 ┌──────────────────────┐   On this machine, no AI.
 │ 1. Schema search     │   Finds the 10 most likely tables by comparing the
 │    (schema_search)   │   question with table/column DESCRIPTIONS.
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   AI call. AI sees: question + table/column
 │ 2. Pick tables       │   descriptions. AI does NOT see any data.
 │    (pick_tables)     │   It picks the tables and columns needed.
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   On this machine, no AI.
 │ 3. Schema graph      │   Works out HOW the tables join
 │    (schema_graph)    │   (e.g. PAYMENT.BILLID = BILL.BILLID) and warns
 └──────────┬───────────┘   about joins that double-count.
            ▼
 ┌──────────────────────┐   AI call. AI sees: question, tables, joins.
 │ 4. Write SQL         │   It writes ONE SELECT query.
 │    (build_report)    │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   On this machine, no AI.
 │ 5. Safety check + run│   Refuses anything that is not a single SELECT on
 │    (sql_runner)      │   allowed tables, then runs it and rolls back.
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐   On this machine, no AI.
 │ 6. Check the answer  │   Compares the result with a trusted report.
 │    (compare)         │   Differences go back to the AI WITHOUT the values
 └──────────┬───────────┘   ("2 cells too high"), so it can fix its SQL.
            ▼
 ┌──────────────────────┐
 │ 7. Web page          │   Shows the answer, the SQL, and an Excel download.
 │    (web_app)         │
 └──────────────────────┘
```

**The two jobs use the same steps:**
- **Report building (Job 1)** runs steps 1–6 in a loop. Step 6 compares with the old report, and the AI retries until it matches on two different months. Then a person approves it (`review_report.py`), and after that it runs with no AI (`run_report.py`).
- **Questions (Job 2)** run steps 1–5 once and show the answer in step 7.
- **Old reports contain real data, so they stay on this machine.** The AI is told only the report's column names and number of rows, plus the SOP text.

**Two words used throughout:**
- **Schema RAG** = step 1. Finding the right tables by *meaning*, not exact words. "Revenue" can find a table called `PAYMENT`. This needs good **table descriptions**, which is why we wrote them.
- **Schema graph** = step 3. A map of tables (dots) and their links (lines). The bot uses it to join tables correctly. Our database has almost no links defined (125 for 674 tables), so we have to **work them out** from column names like `CASEID` and `BILLID`.

---

## 4. What we have done

### Phase 1: Proved the idea on a sample database (AdventureWorks), 13–19 Oct
- Built the whole pipeline above and proved it end to end on Microsoft's sample database.
- **Result:** the bot wrote correct SQL for test reports, and the answers matched the expected numbers cell by cell, including on a held-back month it never saw.
- That sample work has now been **deleted** (reports, data, PDFs). Only the reusable code was kept.

### Phase 2: Moved to our real staging database, 19–21 Oct

| # | Step | Result |
|---|---|---|
| 1 | **Connected to staging** | Server `10.0.0.244`, database **EPM**, SQL Server 2014, SQL login (kept in `.env`). |
| 2 | **Explored it** (`explore_db.py`) | EPM is the *database*. It has **6 schemas**: `dbo` (414 tables, the main app), `EDEX` (99), `edi` (78), `EAMS` (69), `edc` (14), `DWCEAMS` (1 view). |
| 3 | **Learned what the business is** | Medical **lien and collections** for California workers' comp. Providers (mostly imaging centres) treat injured workers; the company bills insurers, chases payment, files liens/appeals/DORs. Collectors work from Karachi and Islamabad. |
| 4 | **Found where the data comes from** | Staging was **restored from a production backup** (server *MI04-Production*) on **27 Nov 2023**, and has been used and changed since (rows from 2026 exist). It does **not** link live to production. It is **real patient data**. |
| 5 | **Cleaned the project** | Removed AdventureWorks material. Removed the "data value search" because it read real values for the AI. Fixed two places where real values could reach the AI (sample rows in the prompt, and values in the "what's wrong" feedback). |
| 6 | **Read the top 10 rows of every dbo table** (`sample_tables.py`) | All 414 tables. Names, SSNs, birth dates, addresses, phones and notes were **masked** before reading. |
| 7 | **Wrote a description for every dbo table** | `EPM/dbo/descriptions.md`. Grouped into: 86 core, 15 report, 103 lookup, 19 history, 35 other-system, 55 system, 46 backup, 55 empty. |
| 8 | **Found the report tables and the code behind them** (`find_procs.py`) | The system already builds report tables (BDR report, billing dashboards, payments report, file status) using stored procedures and a bot. Saved the code of 40 procedures to `EPM/dbo/procs/`. |

### Phase 3: Pointed the report-building pipeline at EPM, 22 Oct

| # | Step | Result |
|---|---|---|
| 9 | **Built `schema.json` for EPM** (`extract_schema.py`) | 258 usable dbo tables (85 core, 103 lookup, 15 report, 20 history, 35 other-system). Backup, empty and system tables left out. |
| 10 | **Inferred the missing table links** | The database declares only 79 links between these tables. We added **325 inferred links** by matching column names to primary keys (e.g. `PAYMENT.BILLID → BILL.BILLID`), only between columns of the same type. Each is marked *INFERRED* so the AI is warned. |
| 11 | **Taught the joins to prefer main tables** | Joins now go through core and lookup tables (PAYMENT → PATIENT → INSURANCE → insurer) instead of cutting through report or history copies. |
| 12 | **Built the search index** | 3,461 descriptions turned into numbers on this machine (takes ~17 min, and only re-runs when `schema.json` changes). |
| 13 | **Dry run, no AI call** | For *"Check posting report: total payments posted per provider and check number"*, the search shortlisted PAYMENT, AllTransactionCPtpay_Report, PREPAYMENTINFO, BILL… The prompt the AI would get is ~2,200 tokens of table/column names and descriptions only. Saved in `EPM/dryrun/`. |

**Known limits:**
- When two routes between tables are the same length, the graph can't tell which one the business means. Example: BILL → insurer via the patient's insurance (right) or via an objection (wrong). The safety nets: the AI names the tables it wants, the result must match the old report on two months, and a person approves the SQL. Confirming links against the data (step E1) and with the CIO will remove these.
- Report-table **columns** have no descriptions yet, so the search does not yet find `Bot_BDRReport_StudyLevel` for "submission date" (step A1).

### How the main tables connect (our understanding so far)
```
BUSINESSINFO (provider)
  └─ PATIENT (injured worker, PATIENTREGID)
       └─ CASEINFO (workers' comp case, CASEID, ADJ number)
            ├─ INJURY, INSURANCE, EMPLOYER, DEFENSEATTORNEY
            └─ STUDY_TO_BE_REQUESTED (one service, e.g. an MRI, STUDY_ID)
                 └─ BILL (BILLID) ─ BILLCPTCODE (bill lines) ─ PAYMENT (money received)
Work on a file:  ACTIONTAKEN, FOLLOWUP_SCHEDULES_SET, CALL_HISTORY, VERIFICATION
Paperwork:       PATIENT_DOCUMENTS ─ DOCUMENT_DETAILS
Disputes:        SBR_Information, AutoAppeal, OBJECTION, DOR_*
```

### The CIO's direction (agreed 21 Oct)
- The database team won't provide ERDs or descriptions. **The AI works out the tables and links itself**, and the CIO checks the result.
- **The system's own report tables are the "master data"**, the trusted answers. We ask the bot questions from them and check it against them.
- **"Check with me" = show the CIO a working POC.**

---

## 5. The plan from here (what's left)

> **The plan we now follow is [POC_PLAN.md](POC_PLAN.md)** (written 22 Oct). It breaks the work into Phase 1 (foundation + BDR question POC), Phase 2 (on-demand reports, SOP upload) and Phase 3 (recurring reports with access control). The steps below are the older list and are kept for reference.

### Step A: Make the report tables the bot's main source *(next)*
The report tables are wide, ready-made and use readable column names, so the AI rarely needs joins. That means **more accurate answers, and they match what the business already sees.**

| Business report | Table | Example question |
|---|---|---|
| BDR / bill submission | `Bot_BDRReport_StudyLevel` (493k rows) | "Submission date of case X?" |
| Check posting / payments | `AllTransactionCPtpay_Report` (459k) | "Checks posted for case X last month?" |
| AR / aging | `BillingDashboard_AgingSummaryOfflineData`, `billingdashboard_offlinedata` | "Outstanding for provider Y over 90 days?" |

- [ ] A1. Describe every **column** of these report tables. *(no AI calls)*
- [x] A2. Build `schema.json` + search index for EPM, with inferred links. *(done 22 Oct)*

### Step B: Build a test set *(no AI calls)*
- [ ] B1. Write ~15 realistic questions (lookups like "submission date of case X", totals, counts by status).
- [ ] B2. Our own code computes the correct answer for each straight from the report tables. This is the answer key.

### Step C: Test the bot *(paid AI calls: ask first)*
- [ ] C1. Free dry run: build every prompt without calling the AI, and check that no data is in them.
- [ ] C2. Agree the number of calls, run the bot on the test set, and measure how many it gets right.
- [ ] C3. Fix what fails (usually better column descriptions) and re-test.

### Step C+: Build a report from an SOP *(Job 1, paid AI calls: ask first)*
- [ ] C4. Pick one real report the business makes (e.g. Check Posting or AR) and get its SOP plus two months of the old report.
- [ ] C5. Let the system build it: write SQL, compare with month 1, fix, then pass month 2.
- [ ] C6. Review and approve it, then run it with no AI for a new month.

### Step C++: Recurring reports with access control *(no AI calls)*
- [ ] C7. Save an approved report as a recurring report: its SQL plus its settings (month, provider, client).
- [ ] C8. Add an access list per report: who may see and run it.
- [ ] C9. One-click run on the web page: pick the settings, get Excel from the latest data.

### Step D: Demo to the CIO
- [ ] D1. Web page: type a question or ask for a report, see the answer, the SQL used, and download Excel. Upload an SOP / old report. Pick an approved recurring report (only the ones you are allowed), set the month, click Run.
- [ ] D2. Show the CIO and let him try his own questions. Note his corrections.

### Step E: Grow beyond the report tables *(after the POC)*
- [ ] E1. Work out the links between the core tables (the schema graph), checked against the data by our software.
- [ ] E2. Let the bot use core tables for questions the reports don't cover.
- [ ] E3. Get the descriptions confirmed by a senior / the CIO.

---

## 6. Files in this project

### Code (kept in git)
| File | What it does |
|---|---|
| `db.py` | The one database connection. Details come from `.env`. |
| `explore_db.py` | Lists schemas, tables, columns, keys and row counts. Reads only the catalog, no data. |
| `sample_tables.py` | Reads the top 10 rows per table, **masking personal details**. `--only "pattern"` for some tables. |
| `find_procs.py` | Finds which stored procedures fill a set of tables and saves their code. |
| `extract_schema.py` | Builds `schema.json` from the catalog + descriptions: 258 usable tables, leaving out backup/empty/system, with declared and **inferred** links. |
| `schema_search.py` | Schema RAG: finds tables by meaning. Runs on this machine. |
| `schema_graph.py` | Schema graph: works out joins and warns about double-counting. |
| `pick_tables.py` | AI picks the tables a question needs. |
| `build_report.py` | AI writes the SQL, we test it, and it retries until correct. |
| `sql_runner.py` / `sql_checks.py` | Safety check, then run (always rolled back). |
| `compare.py` | Compares a result with the expected answer, without showing values to the AI. |
| `review_report.py` / `run_report.py` | A person approves the SQL; the approved SQL then runs with no AI. |
| `web_app.py` | The demo web page. |
| `llm.py` | The one AI connection (Nemotron), with every call logged. |

### Outputs (on this machine only, never in git)
| File | What it holds |
|---|---|
| `.env` | Database login and AI key. **Secret.** |
| `EPM/<schema>/overview.md`, `catalog.json` | Every table and column in each schema. |
| `EPM/dbo/descriptions.md` / `.json` | **Rough description of all 414 dbo tables**, for the senior to check. |
| `EPM/dbo/tables.md` | dbo tables grouped by business area. |
| `EPM/dbo/samples.md`, `samples_only.md` | Masked sample rows. |
| `EPM/dbo/procs/` | Code of the stored procedures that build the report tables. |
| `ai_calls.csv` | Log of every paid AI call. |

### How to add a report for the system to build (Job 1)
Make a folder `reports/<report_name>/` (kept out of git, because the old reports hold real data) with 4 files:

| File | What goes in it | Example |
|---|---|---|
| `sop.txt` | The written steps for making the report, numbered | `1. Take all payments posted between the start and end date.`<br>`2. Group by provider and check number. ...` |
| `case.json` | Report name, the two periods and the column(s) that identify a row | `{"question": "Check posting report", "params": {"start_date": "2026-08-01", "end_date": "2026-08-31"}, "holdout_params": {"start_date": "2026-09-01", "end_date": "2026-09-30"}, "key": ["Check Number"]}` |
| `expected.csv` | The old report for the first period (August) | exported from the system |
| `expected_holdout.csv` | The old report for the second period (September). **The AI never sees this one.** | exported from the system |

Then run `python build_report.py <report_name>` (paid AI calls, so ask first), review with `python review_report.py <report_name>`, and after approval run any month with `python run_report.py <report_name> 2026-10-01 2026-10-31`.

### Common commands
```
python explore_db.py all                              # refresh the catalog of all schemas
python sample_tables.py dbo                           # masked top-10 rows of dbo tables
python sample_tables.py dbo --only "offline|report"   # only matching tables
python find_procs.py dbo "offline|report"             # procedures that fill those tables
python web_app.py                                     # demo page at http://localhost:5000
```

---

## 7. Glossary (business words you will see in the tables)

| Term | Meaning |
|---|---|
| **Workers' comp (WC)** | Insurance that pays medical bills for people injured at work. Case type 11 in our data. |
| **Provider** | The clinic or imaging centre that treated the patient. Our client. `BUSINESSREGID`. |
| **Study** | One service performed, e.g. one MRI. `STUDY_ID`. |
| **CPT code** | Code for a medical procedure, e.g. 72148 = MRI lower spine. |
| **ICD code** | Code for a diagnosis. |
| **HCFA 1500** | The standard paper claim form for a medical bill. |
| **EDI** | Sending bills electronically instead of on paper. |
| **Clearinghouse** | Middleman that passes electronic bills to insurers (WCEDI, Jopari, IHCFA). |
| **Bill submission** | Sending the bill. **Original** = first time, **ReBill** = sent again. |
| **EOR / EOB** | Explanation of Review/Benefits: the insurer's reply saying what it paid and why. |
| **OMFS** | Official Medical Fee Schedule: the state's price list for what should be paid. |
| **SBR** | Second Bill Review: disputing an insurer's payment decision. |
| **Appeal** | Asking the insurer to reconsider a denied or underpaid bill. |
| **Lien** | Legal claim filed to get paid from the injured worker's case. |
| **EAMS / ADJ number** | California's case system for workers' comp / the case number in it (e.g. ADJ10089763). |
| **EDEX** | The state's data feed of EAMS case events, hearings and parties. |
| **WCAB** | Workers' Compensation Appeals Board: the court for these cases. |
| **DOR** | Declaration of Readiness: request for a hearing at the WCAB. |
| **C&R** | Compromise & Release: a settlement of the case. |
| **AR** | Accounts Receivable: money billed but not yet collected (outstanding). |
| **BDR report** | The billing detail report built per study (`Bot_BDRReport_StudyLevel`). |

---

## 8. Things to be aware of

- **Descriptions are first guesses.** They were written from names and samples, and need confirming by a senior or the CIO.
- **Report tables are snapshots.** They are rebuilt by jobs or a bot, so answers from them are "as of the last refresh".
- **Passwords sit in plain tables** (`SERVER_INSTANCES`, `RC_Accounts`, `BUSINESSUSER`). Worth telling IT/security.
- **The project cleanup is not committed to git yet.**
