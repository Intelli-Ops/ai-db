# The project, step by step

Everything we build is recorded here, one section per step, in the order we did it. The goal, the rules and the full plan are in [00_project_overview.md](00_project_overview.md).

Each step explains its **purpose** in simple words, with an **example** and a **scenario**, then what was done, the results, what we learned, the files and a checklist.

| Step | Name | Status |
|---|---|---|
| 1 | [Database inventory](#step-1-database-inventory) | Done, 30 Oct 2026 |
| 2 | [Data profile](#step-2-data-profile) | Done, 30 Oct 2026 |
| 3 | [Table understanding (the schema)](#step-3-table-understanding-the-schema) | Done, 30 Oct 2026; manager's answers pending |
| 4 | [Links between tables](#step-4-links-between-tables) | Done, 30 Oct 2026; a few links need a developer |

---

## Step 1: Database inventory

**Status:** done (30 Oct 2026). No AI used. No business data read.

### Purpose: why this step comes first

Before the system can answer a single question, it has to know **what exists** in the database. This step makes a complete, exact list: every schema, table, view and column, with its type, how many rows each table has, which column identifies a row (primary key), and which links between tables the database declares.

**Think of a new employee's first day.** Before doing any work, they walk through the archive room and write down every cabinet: its label, how many folders it holds, and which drawers are labelled. They **don't open a single file**. At the end of the day they know where everything is, which cabinets are empty, and which ones are huge.

That's this step. We read only the database's **catalog**, its own list of what it contains, and never the data inside the tables.

#### Why it matters for the rest of the project

Every later step reads this list instead of asking the database again:

- **Step 2** uses it to decide which tables to measure.
- **Step 3** uses it to know which columns to describe.
- **Step 4** uses the primary keys and declared links to work out how tables connect.
- **The AI**, much later, must never invent a table or column. Our code can check every query it writes against this list.

#### Example

The inventory tells us this about the `BILL` table, without reading any bill:

| What | Value |
|---|---|
| Rows | 5,712,790 |
| Columns | 33, e.g. `BILLID` (bigint), `PATIENTREGID` (bigint), `DATEOFSERVICE` (datetime), `BILLDATE` (datetime), `AMOUNTBILLED` (float), `BUSINESSREGID` (bigint) |
| Primary key | `BILLID`: every bill has its own number |
| Declared links | `CASEID` → `CASEINFO`, `PATIENTREGID` → `PATIENT`, `BUSINESSREGID` → `BUSINESSINFO` (the provider), `APPOINTMENTTYPE` → `APPOINTMENTTYPE`, `CREATEDBY` → `BUSINESSUSER` |

#### Scenario: how this helps later

A manager will ask: *"How much was billed for dates of service in March 2023?"*

- Without the inventory, the AI would have to guess, and might write `SELECT SUM(BILL_AMOUNT) …`, a column that doesn't exist. The query fails, or worse, it picks a wrong column that does exist.
- With the inventory, the system knows the amount is `BILL.AMOUNTBILLED` and the date is `BILL.DATEOFSERVICE`. If the AI writes a column that isn't in the list, our code catches it **before** the query runs.

### What it reads, and what it doesn't

| Reads (catalog only) | Never reads |
|---|---|
| Schema, table, view and column names | Any row of any table |
| Column types (text, number, date…) | Names, amounts, dates or IDs stored in tables |
| Row counts (the catalog keeps them; nothing is counted) | |
| Primary keys and declared links | |
| Names of stored procedures and functions | |

Nothing is sent to any AI. The results stay on this machine.

### How it works

1. `db.py` connects with the login in `.env`. The login can only read.
2. `step01_inventory.py` runs six catalog queries, all against SQL Server's built-in `sys` views:
   - who and where we are connected;
   - every table and view, with its row count;
   - every column, with its type;
   - the primary keys;
   - the declared links (foreign keys);
   - the stored procedures and functions.
3. It joins these into one entry per table and saves two files.

**Run it:** `python step01_inventory.py`. It takes a few seconds, and is safe to repeat at any time.

### Results

Connected to **EPM_For_Automation** on SQL Server 2014 (version 12.0), read-only.

| | Count |
|---|---:|
| Tables | **655**, holding 354 million rows in all |
| Views | 76 |
| Columns | 12,463 |
| Tables with a primary key | 503 of 655 |
| Declared links (foreign keys) | 124 |
| Stored procedures / functions | 7 / 12 |

**Per schema:**

| Schema | Tables | Views | Rows | Empty tables | What it seems to be about (from names; checked in Step 3) |
|---|---:|---:|---:|---:|---|
| `dbo` | 357 | 59 | 351.9 million | 43 | The main application: patients, cases, bills, payments, documents |
| `settle` | 38 | 0 | 1.0 million | 7 | Settlements: offers, hearings, rejection notes |
| `edi` | 78 | 7 | 1.0 million | 29 | Electronic claims sent to and received from insurers |
| `edc` | 14 | 5 | 78 thousand | 10 | Not clear from the names yet |
| `EAMS` | 69 | 1 | 26 thousand | 58 | California's workers' comp court system filings |
| `EDEX` | 99 | 3 | 18 thousand | 72 | Workers' comp case data lookups |
| `DWCEAMS` | 0 | 1 | 0 | 0 | One view |

**By size:**

| Rows | Tables |
|---|---:|
| Empty (0 rows) | 219 |
| 1 – 1,000 | 258 |
| 1,001 – 100,000 | 86 |
| 100,001 – 1 million | 58 |
| Over 1 million | 34 |

**The biggest tables** are mostly documents (`PATIENT_DOCUMENTS` 40.3 million rows, `DOCUMENT_DETAILS` 33.3 million), then billing: `BILLCPTCODE` 10.6 million (bill lines), `PAYMENT` 8.9 million, `BILL` 5.7 million, `STUDY_TO_BE_REQUESTED` 5.7 million. The full top 30 is in `catalog/inventory.md`.

### What we learned

1. **A third of the tables are empty** (219 of 655). They can be left out of everything the AI sees, which keeps its menu short and clear.
2. **About 70 tables look like backups, copies or temporary tables**, judging by names such as `…_bkp20250818`, `…_COPY`, `…_OLD`, `Temp…`. Step 2 will confirm which ones to leave out.
3. **The database declares very few links.** 557 of the 655 tables have no declared link at all. For example, `PAYMENT` has a `BILLID` column, but the database never says it points to `BILL`. **Step 4 has to work these links out** from column names and then check them against the data.
4. **Nothing has a description.** The database has no built-in explanations of tables or columns, so **Step 3 has to write them**.
5. **138 "views" were left out on purpose.** They are named `syncobj_0x…` and are created automatically by SQL Server's replication feature, which flags them as system objects. They hold no business meaning.

### Files

| File | What it is |
|---|---|
| `db.py` | The database connection, shared by every step. |
| `step01_inventory.py` | This step's tool. |
| `catalog/catalog.json` | The full inventory, for the next steps. On this machine only. |
| `catalog/inventory.md` | The same, readable: totals, per schema, biggest tables, then every table and view with its rows, columns, primary key and link counts. On this machine only. |

### Checklist

- [x] Connection in one place (`db.py`), settings only in `.env`
- [x] Inventory tool written and run
- [x] Every schema, table, view, column, primary key, declared link and procedure listed
- [x] System-made replication objects left out
- [x] Findings written down
---

## Step 2: Data profile

**Status:** done (30 Oct 2026). No AI used. Only counts and dates were kept; no row was copied out.

> **Important: this is a staging copy.** Its tables and columns are the same as production, but its data is older and thinner. So the dates and fill levels below describe **this copy only**. They are useful for testing, but they are **not** used to decide what the AI sees: a table that looks old or empty here may be busy in production. Step 3 follows this rule.

### Purpose: what is actually used?

Step 1 told us what **exists**. Step 2 finds out what is **used**. A table can exist and still be useless to us: empty, abandoned years ago, or a backup someone made once. A column can exist and never be filled in.

**Back to the new employee.** On day one they listed every cabinet in the archive room. On day two they pull each drawer open just far enough to see **how full it is** and **the date on the newest folder**, without reading any folder. Now they know which cabinets the company works from every day, which were closed in 2015, and which are just photocopies of other cabinets.

For every non-empty table, the tool measures three things:

1. **How full each column is.** For example, 100% of bills have an amount, but no bill has a `CPTCODE` (that lives in the bill-lines table instead).
2. **The first and last date** in every date column.
3. **Rows added per month**, on the table's "when added" column (usually `CREATEDON`). From this we get the **last month of normal use**.

#### Why it matters for the rest of the project

- **Step 3** knows which tables hold the most data here, which are clearly copies, and which columns are empty in this copy (so they can be labelled, not trusted blindly).
- **The "when added" column** of each table is what a question like "bills added last month" needs.
- **Testing** knows which date ranges have data in this copy, so test questions return real numbers.

#### Example

What Step 2 learned about `BILL`, without reading a single bill:

| What | Value |
|---|---|
| "When added" column | `CREATEDON` |
| Bills added per year | 2020: 851,617 · 2021: 1,127,396 · 2022: 1,158,137 · 2023: 193,448 · 2024: 359 · 2025: 29 |
| Last month of normal use | **November 2023** |
| Always filled | `AMOUNTBILLED`, `DATEOFSERVICE`, `CASEID`, `PATIENTREGID` (100%); `BILLDATE` 99.9% |
| Always empty | `CPTCODE`, `MODIFIER`, `MODIFIERDESCRIPTION`, `PhysicianNPI` |

#### Scenario: how this helps later

Someone asks: *"Show me bills by CPT code for 2022."*

- **Without Step 2,** the AI sees `BILL.CPTCODE`, uses it, and the answer is one big row of "blank", because that column is always empty.
- **With Step 2,** we know `BILL.CPTCODE` is always empty, so Step 3 labels it and points the AI to the bill-lines table (`BILLCPTCODE`), where CPT codes really are.

### How "last month of normal use" is worked out

Simple rule: find the table's **typical month** (the median of its monthly row counts). A month counts as **normal** if it has at least 10% of that. The last month of normal use is the end of the **latest run of 3 normal months in a row**.

The "3 in a row" matters. `PAYMENT` had 13,586 rows in April 2025 and 3,581 in June 2025, with almost nothing around them. These are one-off batches, most likely tests, not real use. With the 3-in-a-row rule, `PAYMENT` correctly shows **November 2023**.

### What it reads, and what it doesn't

| Keeps | Never keeps |
|---|---|
| Row counts, and how many rows each column is filled in | Any name, amount, ID or text from a row |
| First and last date of each date column | Any whole row |
| Rows per month on one date column | |

The tool reads the tables in the database (that is the only way to count), but only totals come out. Reading uses `NOLOCK` so it never blocks other users of the server. Nothing is sent to any AI.

### How it works

1. `step02_profile.py` reads the Step 1 inventory and takes the 436 non-empty tables, smallest first.
2. **Pass 1**, one query per table: the count of filled rows for every column (blank text counts as empty), and the first and last date of every date column.
3. It picks the **"when added" column**: a date column filled in at least half the rows, preferring names like `CREATEDON`, `ENTRYDATE` or `INSERTED`.
4. **Pass 2**: rows per month on that column.
5. Each table's result is saved as soon as it's done, so if the run stops, the next run continues where it stopped.
6. It adds two labels: **last-use period**, and **looks like a copy** (from the name, plus whether it has exactly the same columns as another table).

**Run it:** `python step02_profile.py` takes about 45 minutes (most of it is the two 40-million-row document tables). `python step02_profile.py --report` rebuilds the summary in seconds without touching the database.

### Results

**Tables by last month of normal use** (436 non-empty tables):

| Last normal use | Tables | Rows | What it means |
|---|---:|---:|---|
| 2023 or later | 154 | 317.5 million | The live core. Almost all business tables end in **Nov 2023** (62 tables end exactly then). |
| 2020 – 2022 | 36 | 11.8 million | Stopped recently. Probably replaced by newer tables. |
| 2015 – 2019 | 38 | 11.6 million | Old features. |
| Before 2015 | 42 | 1.8 million | Very old. |
| No date column | 138 | 6.0 million | Mostly lists and settings (codes, statuses, types). Often needed for lookups. |
| No usable dates | 28 | 5.4 million | Has date columns, but they are mostly empty, so no "when added". |
| Empty | 219 | 0 | Known from Step 1. |

**The core:** 61 tables are in use up to 2023 or later, have over 100,000 rows, and aren't copies. These include `BILL`, `BILLCPTCODE`, `PAYMENT`, `CASEINFO`, `PATIENT`, `PATIENT_DOCUMENTS` and `billingdashboard_offlinedata`.

**Activity in 2024–2025** shows up in 79 tables, but it is mostly **small settings tables** (report layouts, user access, jobs) and **dashboard snapshot tables** such as `BillingDashboardSummary_PatientLevel`, whose "added" date is the date the dashboard was rebuilt, not a business date. Real business volume stops in Nov 2023.

**Columns** (5,309 columns in the 436 non-empty tables):

| How full | Columns |
|---|---:|
| Always empty | 766 |
| Almost empty (under 1%) | 236 |
| Partly filled | 1,474 |
| Always filled | 2,833 |

**Copies:** 66 tables look like backups, copies, temporary or test tables. 30 of them are empty; the other 36 hold 20.9 million rows. 24 have exactly the same columns as a main table, so they are clear copies (for example `dbo.BillingDashboardSummary_PatientLevel_bkp20250818`).

### What we learned

1. **In this copy, most business tables have normal activity up to November 2023.** That only tells us which dates to use for tests; production is up to date.
2. **About 60 tables hold most of the data.** That's a good starting point for the core in Step 3.
3. **About 1 in 5 columns in non-empty tables is always or almost empty here** (1,002 of 5,309). They stay visible to the AI, labelled "empty in this database", because they may be filled in production.
4. **Some columns sit in the "wrong" table.** `BILL.CPTCODE` is always empty because CPT codes live in `BILLCPTCODE`. Step 3 has to describe where each fact really lives.
5. **Dashboard tables are bot-built reports.** `billingdashboard_offlinedata` and similar tables are pre-calculated from the original tables. Step 3 decides: the agent answers from the original tables, and these are used only to check our answers.
6. **Some dates are junk.** 89 date columns have dates before 1990 (for example `1900-01-01`, a common "no date" placeholder), and 21 have dates in the future. Queries will need to ignore these.

### Files

| File | What it is |
|---|---|
| `step02_profile.py` | This step's tool. |
| `catalog/profile.json` | Every table's measurements, for the next steps. On this machine only. |
| `catalog/profile.md` | The same, readable: summaries, the copy list, then every table's "when added" column, first month, last normal month and empty-column count. On this machine only. |
| `catalog/profile_parts.jsonl` | Raw results, one line per table, used to resume a stopped run. On this machine only. |

### Checklist

- [x] Fill count for every column of every non-empty table (436 tables, 5,309 columns)
- [x] First and last date for every date column
- [x] Rows per month and last month of normal use for every table with a "when added" column
- [x] One-off batches (like the 2025 test runs) not counted as use
- [x] Backups and copies flagged, by name and by identical columns
- [x] Findings written down

---

## Step 3: Table understanding (the schema)

**Status:** done (30 Oct 2026; revised the same day after review). No AI API used, no data read. The descriptions were written from table and column **names** only, so some are guesses. The guesses that could change numbers are listed in [02_questions_for_manager.md](02_questions_for_manager.md).

### Purpose: what does each table mean?

Steps 1 and 2 told us what exists and how full it is. They still don't tell anyone what `STUDY_TO_BE_REQUESTED` *means*, or that `BILL.AMOUNTBILLED` is in dollars while `PAYMENT.PPOReduction` is not money received. This step writes that meaning down in plain English, and sorts every table into a **tier** that says how the AI should use it.

**Back to the new employee.** By now they know every cabinet and how full each one is. On day three they make **a guide for the archive room**: "Cabinet B holds bills, one folder per bill; the amount is on the first page; the CPT codes are in cabinet C, not here. Cabinet X is a photocopy of B, never count from it. The back room holds older or rarely used cabinets: look there only if the front rooms don't have it." Anyone new can now find things without asking.

The result is **the schema**: the menu the AI reads before it writes any query. For each table it says:

- **Tier:**
  - *core*: the main business tables. The AI looks here first.
  - *support*: code lists, names and details the core tables point to.
  - *archive*: everything else that may hold business data. The AI sees it but uses it only when core and support don't fit.
  - *answer key*: the bot-built report tables (the BDR-style billing dashboard). **Not shown to the AI.** We use them only to check our answers.
  - *left out*: with the reason (copies, passwords, app settings, logs).
- **What it is** and **what one row is** ("one payment on one bill line").
- **For each column:** its **role** (date, amount, link, flag, code, text…), its **meaning**, how full it is in this database, and a **sensitivity** label (personal, identifier, free text, secret) for the privacy step.

#### Two rules from the review

1. **Nothing is judged by dates or by how empty something is.** This database is a staging copy: the same tables and columns as production, with older and thinner data. A table that looks unused here may be busy in production. So old and empty tables go to the *archive* tier instead of being left out, and empty columns stay visible with the label **"empty in this database"**. Only password columns are hidden.
2. **The agent answers from the original tables, not from the bot reports.** The BDR-style dashboard tables already join everything correctly, so they make a perfect **answer key**. In the POC we compare our answers with them (counts only). In the real system the agent works out the answer itself, the way a person would.

#### Why it matters for the rest of the project

- **Step 4 (links)** uses the "link" columns and their meanings, for example `PAYMENT.BILLID` → `BILL`.
- **Step 5 (vocabulary)** builds on the column meanings. "Paid" must use `PAYMENT.PAYMENT`, and the manager still has to decide whether reductions count.
- **Step 6 (schema search)** searches these descriptions to find the right tables for a question, core first, archive last.
- **Step 7 (privacy)** uses the sensitivity labels to know which values must never leave.

#### Example

Part of what the schema says about `PAYMENT`:

| Column | Role | Meaning | Filled here |
|---|---|---|---:|
| `PAYMENTID` | key | The ID of this row (one payment on one bill line). | 100% |
| `BILLCPTCODEID` | link | The bill line (BILLCPTCODE). | 100% |
| `PAYMENT` | amount | The amount paid, in dollars. | 100% |
| `PAYMENTDATE` | date | The date of the payment. | 100% |
| `CHECKNUMBER` | text, *identifier* | The number of the check that paid it. | |
| `PPOReduction` | amount | A PPO-contract reduction rather than money received (*check*). | |
| `FOR_SETTLEMENT` | flag | Whether the payment came from a settlement. | |

A column with no values in this copy is still listed, with the note *"empty in this database"*.

#### Scenario: a BDR question

A user asks: *"How many studies does patient X have, and what are their submission details?"*

- **The agent** finds `STUDY_TO_BE_REQUESTED` (core, *studies*) for the patient's studies and `BILL` (core, *billing*) for each study's `Submission_Type`, `BillByEDI`, `BillByEDIDate`, `BillByEDIStatus` and `EDI_status`. It joins them on `STUDY_ID` and answers from the original data, so the answer is never older than the last report run.
- **The answer key** `BillingDashboardSummary_PatientLevel` holds the same facts per study. During the POC we run the same question both ways over all patients and compare the counts. If they match, the joins are proven. If not, the difference shows the business rule we are missing.
- **Backups** such as `BillingDashboardSummary_PatientLevel_bkp20250818` are left out, so the agent can't count from a copy by mistake.

### How it works

Two parts: **knowledge written by hand**, and **a script that combines it with Steps 1–2**.

1. **`knowledge/tables.yaml`** (written by hand, easy to edit):
   - `business`: what the company does, in one paragraph.
   - `abbreviations`: ADJ, DOR, EOR, OMFS, SB1160, C&R, DOS…
   - `common_columns`: columns that mean the same everywhere. For example, `PATIENTREGID` always means *the patient*, and `BUSINESSREGID` always means *the provider (our client)*. They are written once instead of in every table.
   - `tables`: every core, support and answer-key table with its tier, topic, description, "one row is…", notes on important columns, and a `check:` question where unsure.
   - `archive`: tables moved to the archive by hand.
   - `leave_out`: tables kept away from the AI, grouped by reason.
2. **`step03_schema.py`** combines this with the Step 1 inventory and the Step 2 profile:
   - A table described by hand gets its tier. A table on the leave-out list is left out. Backups and copies (by name, from Step 2) and log or scratch tables (by name, such as `DDLEvents` or `Sheet1$`) are left out automatically.
   - **Everything else goes to the archive automatically**, including all views. It is described from its name ("the name suggests: bill by EDI") until someone writes a better description.
   - **Column role** comes from the type and name. A `datetime` is a date; a decimal named `…AMOUNT…` is an amount; a name ending in `ID` is a link.
   - **Column meaning** comes, in this order, from a hand note for that table, then the shared meaning, then words made from the column name (`DATE_OF_INJURY_START` → "Date: date of injury start").
   - **Sensitivity** comes from the name (`FIRSTNAME`, `SSN`, `PHONE` are *personal*; `MRN`, `CLAIM_NUMBER` are *identifiers*; `NOTES` is *free text*; `PASSWORD` is a *secret* and is always hidden).
   - Anything listed twice, or a note for a column that doesn't exist, is reported as a problem.

**Run it:** `python step03_schema.py`. It takes about a second and doesn't touch the database. Change `knowledge/tables.yaml` and run it again whenever someone answers a question. When it runs against production, the "empty in this database" labels update by themselves.

### Results

All 731 objects (655 tables and 76 views) are sorted:

| Tier | Tables | Rows in this copy | Shown to the AI |
|---|---:|---:|---|
| **Core** | 27 | 181 million | Yes, first |
| **Support** | 150 | 44 million | Yes |
| **Archive** | 328 (76 views, 141 empty here, 111 with data) | 14 million | Yes, last |
| **Answer key** | 4 | 15 million | No: only to check answers |
| **Left out** | 222 | | No |

**The 27 core tables, by topic:**

| Topic | Core tables |
|---|---|
| Patients and cases | `PATIENT`, `CASEINFO`, `INJURY`, `INSURANCE` |
| Studies | `STUDY_TO_BE_REQUESTED`, `HISTORY_STUDY_STATUS` |
| Billing | `BILL`, `BILLCPTCODE`, `BILLICDCODES`, `BILLCPTCODE_OMFS` |
| Payments | `PAYMENT`, `COLLECTION` |
| Collections work | `ACTIONTAKEN`, `FOLLOWUP_SCHEDULES_SET`, `COLLECTORCASE`, `VERIFICATION` |
| Appeals | `AutoAppeal`, `AutoAppealAdj` |
| Liens and court | `DOR_Case_Information`, `DOR_case_lien_additional_information`, `DOR_Review_Information`, `SB1160_INFO_MASTER`, `EDEX_CASE_SIGNIFICANT_EVENTS`, `EDEX_HEARING_NOTIFICATIONS` |
| Settlements | `settle.SettlementOffer` |
| Documents | `PATIENT_DOCUMENTS`, `DOCUMENT_DETAILS` |

**Support** includes providers (`BUSINESSINFO`), insurers (`INSURANCE_COMPANY`), the price list with CPT codes (`BUSINESSSERVICE`), employers, attorneys, electronic claims and 75 code lists (statuses, types, reasons).

**Archive** includes, among others, the document history (`PATIENT_DOCUMENTS_LOG`, 9.9M rows here), call logs (`GoogleVoiceCallLogs`, `CALL_HISTORY`), `EDI_Appeal`, `BILL_BY_EDI`, `PROOF_OF_SERVICE`, `MESSAGES`, the court-system tables in the `EAMS` and `EDEX` schemas, code lists such as body parts and WCAB venues, and all 76 views.

**Answer key:** `BillingDashboardSummary_PatientLevel` (one row per study: status, bill, EDI and submission details, insurance, paid, outstanding), `billingdashboard_offlinedata` (one row per bill line), `BillingDashboard_AgingSummary` and `FileStatusOfflineData`.

**Why tables were left out:**

| Reason | Tables |
|---|---:|
| Backup, copy, temporary or test table (by name, Step 2) | 66 |
| Log, system or scratch table (by name) | 50 |
| Application settings, menus, permissions | 39 |
| System logs, sessions, jobs | 25 |
| Screen caches | 12 |
| Document storage and AI-matching work tables | 9 |
| Spreadsheets imported once | 6 |
| Copies of data kept elsewhere | 6 |
| Report-builder settings (kept in mind for Step 10) | 4 |
| Hold passwords or server logins | 4 |
| Who may see which provider (`PROVIDER_ACL`; kept in mind for Step 11's per-user access) | 1 |

None of these was left out for being old or empty.

**Columns:**
- **9,297 columns are shown to the AI.** 744 of them carry the label "empty in this database" or "almost empty". In core and support it is 456 of 2,203.
- **8 are hidden**, all of them passwords or login details.
- **Where the meanings come from:** 162 written by hand, 1,468 from shared meanings and 7,667 made from the column name. Most name-made ones are in the archive; in the core tables, most important columns are written by hand.
- **Sensitive columns:** 1,863 personal, 351 identifiers, 82 free text.

### Open questions

Some descriptions are guesses that, if wrong, give wrong numbers. They fall into three kinds:

| Kind | Example | Who answers |
|---|---|---|
| **A. We check ourselves with counts** | Is a bill's amount the sum of its lines? Do pre-entered payments end up in `PAYMENT`? Do our totals match the answer key? | We do, in Steps 4–5, with no data shown |
| **B. What a code means** | Case status 3 = ?; payment type 2 = ? | The manager, or read the small code-list tables if approved |
| **C. Business rules** | Do PPO reductions count as paid? Which insurer belongs to a case? Where is a settlement officially recorded? | The manager |

Kinds B and C are written up, numbered and in plain language, in **[02_questions_for_manager.md](02_questions_for_manager.md)** (26 questions). It also asks for one permission, `VIEW DEFINITION`, which would let us read how the existing views and report procedures calculate things. Until a question is answered, the system states its assumption in the answer.

### What we learned

1. **The business is clear from the names.** Providers order studies for injured workers. Studies are billed line by line. Payments come back. Collectors chase the rest through follow-ups, appeals, settlements, liens and court.
2. **27 tables answer most questions.** The 150 support tables give names to codes and add details. The archive is a safety net.
3. **Some meanings can't come from names.** Column types sometimes contradict a name. `CASEINFO.SETTLEMENT` is a decimal (an amount), not a yes/no, so the draft was corrected and marked *check*.
4. **The database holds secrets in plain tables** (user passwords, fax-account and server logins). These tables and columns are never shown to the AI.
5. **There are parallel versions of some things,** such as two hearing feeds (`EDEX_HEARING_NOTIFICATIONS` and `Edex_Hearing`) and two provider lists (`BUSINESSINFO` and `settle.Providers`). The schema says which one to use first.
6. **The bot reports are worth more as a test than as a source.** Answering from the original tables keeps answers current and teaches the agent the real joins. The reports then prove those joins are right.

### Files

| File | What it is |
|---|---|
| `knowledge/tables.yaml` | The hand-written knowledge: business, abbreviations, shared column meanings, every described table, the archive list and the reasons for leaving tables out. **Edit this to correct a description.** |
| `step03_schema.py` | This step's tool. |
| `catalog/schema.json` | The schema, for the next steps. On this machine only. |
| `catalog/schema.md` | The same, readable: totals, open questions, then every table by tier with its columns. On this machine only. |
| `docs/02_questions_for_manager.md` | The open questions for the manager. |

### Checklist

- [x] All 731 tables and views in a tier or left out with a reason; nothing unsorted
- [x] Nothing left out for being old or empty (staging copy rule)
- [x] Description and "one row is…" for all 181 core, support and answer-key tables; archive described from names
- [x] Role, meaning, fill and sensitivity for every column; empty columns labelled, only secrets hidden
- [x] Bot report tables set aside as an answer key, not as a source
- [x] Business summary, abbreviations and shared column meanings written
- [x] Open questions sorted, and the manager's questions written up
- [ ] Manager's answers added to `knowledge/tables.yaml`

---

## Step 4: Links between tables

**Status:** done (30 Oct 2026). No AI used. Every link was tested against the data, and only counts came back; no row was copied out.

### Purpose: how do the tables connect?

Step 3 says what each table means. But almost no question is answered from one table. "Payments for patient X" needs the payments table, the patient table, and the road between them. This step finds those roads (**links**, or **joins**) and **tests every one against the data**, so the AI never joins two tables on a guess.

**Back to the new employee.** They know what every cabinet holds. Now they learn how to go from a folder in one cabinet to the matching folder in another: "a payment slip carries the bill-line number; look that number up in cabinet C". Then they **try it on a few hundred folders** to make sure it works, before telling anyone.

The database itself declares only 124 links, and most real links are missing from that list. So the tool finds links in four ways:

1. **Declared** in the database (112 used).
2. **By name:** a column named like another table's key. `PAYMENT.BILLCPTCODEID` → `BILLCPTCODE.BILLCPTCODEID`; `BILL.FACILITYID` → `BUSINESSFACILITY.FACILITYID` (667).
3. **By hand**, in `knowledge/links.yaml`, for names that give no hint. For example, `CREATEDBY` → a user, or `CASEINFO.PTP` → maybe a physician? Several possible targets can be listed, and the data picks the right one (428).
4. **Special links:**
   - **List link:** a column holding a *list* of keys. `COLLECTION.PaymentID` lists the payments a collector is credited for.
   - **Two-column link:** a link that needs two columns together (below).

**How a link is tested.** Of the rows that have a value in the column, how many find their row in the other table?
- **Confirmed:** 99% or more.
- **Mostly:** 90–99% (a few rows point to deleted records).
- **Weak:** 50–90%.
- **Rejected:** under 50%, so the guess was wrong.

Big tables are tested on an even spread of about 200,000 rows.

#### Why it matters for the rest of the project

- **Step 5 (vocabulary)** defines "paid", "outstanding" and the rest as calculations across tables, using these roads.
- **Step 6 (schema search)** brings along the tables needed to connect the ones a question mentions.
- **Step 8 (SQL agent)** gets the exact join for each pair of tables instead of guessing it. A wrong join is the most common way an AI gives a confident but wrong number.

#### Example: the tool rejects a wrong guess

`BILL.PHYSICIANID` looks like it points to `PHYSICIAN.PHYSICIAN_ID`, and the names match perfectly. The data says no: only **34%** of the IDs exist there. Four other tables were tried, and none fit. So the link is **rejected**, the AI won't use it, and it became a question for a developer. Without this check, "bills per physician" would have been confidently wrong.

#### Scenario: the BDR question, and a hidden trap

A user asks: *"How many studies does patient X have, and what are their submission details?"*

- The submission details live on the **bill**, and a bill has a `STUDY_ID` column. The obvious join is `BILL.STUDY_ID = STUDY.STUDY_ID`, and the test **confirms** it (99.9% match).
- **The trap:** `STUDY_ID` is filled on only **36%** of bills (2.0 of 5.7 million). Joining on it alone would silently lose about two thirds of the bills, and the answer would look fine but be wrong.
- **How we found it:** the BDR answer key links 99.7% of bills to a study, so the bot uses another rule. Counting showed the rule: **a bill belongs to the study of the same case and the same appointment type**. Tested:

| Test | Result |
|---|---|
| Bills that find exactly one study this way | **99.93%** (none find several) |
| Where `BILL.STUDY_ID` is filled, does the rule give the same study? | **99.91%** |
| Does it give the same study as the BDR answer key? | **100%** |

So the agent will join bill to study on **case + appointment type**, and every bill is covered. This is the answer key doing its job: it showed us a business rule that no name or column could have told us.

### How it works

`step04_links.py` reads the inventory (Step 1), the schema (Step 3) and `knowledge/links.yaml`:

1. **Lists possible links** for every column of every kept table and view, in the four ways above.
2. **Tests each one** against the data with one count query, using `NOLOCK` so it never blocks other users. Views and tables that are empty here can't be tested, so they keep their name-based link, labelled "not checked".
3. **Picks the best target** when a column has several possible ones: the best match wins. If two targets match equally well, both are recorded ("also matches") so a person can decide.
4. **"Two roads agree" checks.** Some tables store a fact directly *and* can reach it through a link. Example: a payment stores its bill, and its bill line also knows the bill. If both roads give the same answer, the links are right.
5. **Shape** of each core link: how many rows on one side per row on the other (a case has on average 6.8 bills), and how many target rows are used at all.
6. **Join paths:** the shortest road between every pair of the 27 core tables, through core tables first, then support tables.

Every result is saved as soon as it is done, so a stopped run continues where it stopped. To add a hint, edit `knowledge/links.yaml` and run again: only the new checks run.

**Run it:** `python step04_links.py`. The first full run took about 85 minutes; later runs only check what is new. `python step04_links.py --report` rebuilds the summary without touching the database.

### Results

**1,166 tests, of 1,208 columns with a possible link:**

| Status | Core | Support | Archive | Answer key |
|---|---:|---:|---:|---:|
| Confirmed (99%+) | 140 | 214 | 157 | 23 |
| Mostly (90–99%) | 12 | 7 | 9 | 0 |
| Weak (50–90%) | 6 | 5 | 5 | 0 |
| Rejected (under 50%) | 8 | 9 | 18 | 0 |
| Not checked: column empty here | 13 | 62 | 32 | 1 |
| Not checked: view, or table empty here | 0 | 0 | 522 | 0 |

**Two roads agree** (15 checks): every one that could be tested agreed at **99.9% or better**. For example:
- a payment's bill = its bill line's bill (100%);
- a bill's patient = its case's patient (100%);
- the BDR's study = the bill's study (99.94%).

One check couldn't be tested: the BDR's bill-line column is empty.

**What the shapes tell us** (things the AI must know to avoid double counting):

| Link | Shape |
|---|---|
| Case → patient | A patient has on average 1.4 cases |
| Bill → case | A case has on average 6.8 bills |
| Bill line → bill | A bill has on average 1.9 lines |
| Payment → bill line | A bill line has on average 1.6 payments |
| Injury → case | One-to-one |
| BDR answer key → study, and → bill | One row per study and per bill. In this copy it covers about a quarter of the studies. |
| Bill-line answer key → bill line | Covers every bill line |

**Join paths:** all 351 pairs of core tables can be connected. Examples:
- **Payment to patient:** `PAYMENT.PATIENTREGID = PATIENT.PATIENTREGID`.
- **Bill to study:** `BILL.CASEID = STUDY.CASEID AND BILL.APPOINTMENTTYPE = STUDY.APPOINTMENTTYPEID`.
- **Bill to insurance:** through the patient (`BILL` → `PATIENT` → `INSURANCE`). This is why the manager is asked how to pick a case's insurer.

**Answered by the data** (removed from the manager's list):
- the case's primary treating physician is in `PHYSICIAN` (97.8%);
- a study's invoice is in `INVOICE` (100%);
- the collector on a patient or case is a user in `BUSINESSUSER` (100%);
- a case's grade, validity and invalid-reason codes are in small dropdown tables (100%);
- a settlement offer's provider is our provider ID (`BUSINESSINFO`, 99.99%).

**Still open** (now in the manager's list, Part 3):
- `CASEINFO.ATTORNEY`: fits two attorney tables.
- `BILL.PHYSICIANID`: no table fits.
- `FOLLOWUP_SCHEDULES_SET.ACTIONTAKENID`: 12% match.
- The `FILEID` columns.

81 columns in core and support tables that look like links point to no table we could find. Most are outside IDs (`External_Study_ID`, `ClientCaseID`), payer IDs used in electronic claims, or codes without a list (`PAYMENTTYPEID`).

### What we learned

1. **The database declares only a small part of its links.** Names found most of the rest, but **a name is not proof**. Eight core-table guesses were wrong, including some with perfect name matches.
2. **The main chain is solid.** Patient → case → bill → bill line → payment agrees with itself 99.9–100% in every direction.
3. **One important link needs two columns.** Bill → study is "same case + same appointment type", not just `STUDY_ID`. A naive join would lose two thirds of the bills.
4. **The answer key proved its worth.** The BDR matches our joins 100%, and it revealed the bill → study rule.
5. **Some columns hold lists.** `COLLECTION.PaymentID` holds several payment IDs in one value. The AI must treat it as a list, not join on it directly.
6. **Some links are fuzzy by nature.** About 2 in 3 study-history rows and 4 in 5 collector actions point to a study that exists in this copy. Answers built on those links say so.

### Files

| File | What it is |
|---|---|
| `knowledge/links.yaml` | Hand-written link hints, list links, two-column links and the "two roads" checks. **Edit this to add or correct a link.** |
| `step04_links.py` | This step's tool. |
| `catalog/links.json` | Every link with its test result, the two-road checks, two-column links and join paths, for the next steps. On this machine only. |
| `catalog/links.md` | The same, readable. On this machine only. |
| `catalog/links_parts.jsonl` | Raw test results, one per line, so a run can continue. On this machine only. |

### Checklist

- [x] Possible links found for every kept table and view (declared, by name, by hand, lists, two-column)
- [x] Every testable link tested against the data, counts only
- [x] Wrong guesses rejected; ties recorded for a person to decide
- [x] Main chain checked both ways ("two roads agree")
- [x] Bill → study rule found, and proven against the BDR answer key
- [x] Shape of every core link (rows per target, coverage)
- [x] Join paths between all core tables
- [ ] Open link questions answered by a developer (manager's list, Part 3)
