# Project overview: an AI assistant that knows our database

## What we are building

One **intelligent agentic system** that knows our company database (EPM_For_Automation) the way an experienced analyst does, and can:

1. **Answer questions about the data, the way Claude would.** A person types *"How much did we collect from each insurance company in March 2023?"* The system works out which tables hold that, writes the database query (SQL), runs it, checks the result, and replies in clear language with the numbers and a table, showing the steps it took. It remembers the conversation, so a follow-up like *"and in April?"* just works.
2. **Build reports from an SOP or an old report.** A person uploads a written procedure (SOP: *"every month, list the bills over 90 days unpaid, grouped by insurer…"*) or an old Excel report. The system works out how to produce that report from the database, compares its output with the old report, fixes itself until they match, and a person approves it.
3. **Re-run approved reports with one click** for a new month, provider or client, without any AI.

**"Agentic"** means it doesn't answer in one shot. Like a person, it **plans, acts, looks at the result and corrects itself**: *"I'll look in the payments table… the query returned nothing… the name was probably spelled differently, let me search more loosely… now I have it."*

## The rules that never change

| Rule | What it means in practice |
|---|---|
| **The AI never sees our data** | The AI only sees table names, column names and descriptions, plus the question with names and IDs swapped for placeholders (*"patient @patient_1"*). Queries run on our machine; the results stay here. Patient data (PHI) never leaves. |
| **Read-only** | The database login can only read. Every query is checked to be a plain `SELECT` before it runs. |
| **No paid AI call without approval** | Before any step that calls the AI, the number of calls is agreed first, and the system stops at that number. |
| **One AI model** | DeepSeek V4.1 Flash, unless management approves a change. |
| **Secrets stay out of git** | The database login and AI key live only in `.env` on this machine. |

## How we work

- **One step at a time.** We only move to the next step when you say so.
- **Two documents only.** This overview (goal, rules, plan), and [01_project_steps.md](01_project_steps.md), where every step is written up in order: its **purpose** in simple words, with an **example** and a **scenario**, then what was done, the results and the files. Plus [02_questions_for_manager.md](02_questions_for_manager.md): the open questions only a person can answer.
- Each step leaves something the next step builds on, like floors of a building.

## The plan, step by step

This is the proposed order. We can change it as we go.

| Step | Name | Purpose in one line | Uses AI? |
|---|---|---|---|
| 1 | Database inventory | Make a complete list of what the database contains: tables, columns, keys, sizes. | No |
| 2 | Data profile | Measure how full each table and column is in this copy (counts only). | No |
| 3 | Table understanding (the schema) | Sort every table into a tier (core, support, archive, answer key) and write what each table and column *means* in plain English. | Maybe, on names only |
| **4** | **Links between tables** | Work out and check how tables connect (a payment belongs to a bill, a bill to a case…). | No |
| 5 | Business vocabulary | Define terms like *billed, paid, outstanding, date of service* and exactly how each is calculated. | No |
| 6 | Schema search (RAG) | For any question, find the few tables that are relevant, so the AI gets a short, focused menu. | No (runs locally) |
| 7 | Privacy shield | Swap names and IDs in a question for placeholders before the AI sees it, and check every message for leaks. | No |
| 8 | SQL agent | The AI writes SQL, our code checks it is safe, runs it, and lets the AI fix its own errors. | Yes |
| 9 | Chat that works like Claude | Conversation memory, summarising long chats, keeping prompts small, showing its steps, suggesting follow-ups. | Yes |
| 10 | Reports from SOPs and old reports | Turn an SOP or old report into a working report, compare, self-correct, human approval. | Yes |
| 11 | Saved, one-click reports | Approved reports re-run with new parameters, per-user access, no AI. | No |
| 12 | Web app, testing and demo | One page for chat and reports, full testing, and a demo for the CIO and CTO. | Yes, for testing |

## Files

| Path | What it is |
|---|---|
| `docs/00_project_overview.md` | This overview. |
| `docs/01_project_steps.md` | Every step, written up in order. |
| `docs/02_questions_for_manager.md` | Questions for the manager (business rules, code meanings). |
| `db.py` | The database connection, used by every step. Settings come from `.env`. |
| `step01_inventory.py` | Step 1: reads the database's catalog. |
| `step02_profile.py` | Step 2: measures which tables and columns are actually used. |
| `step03_schema.py` | Step 3: builds the schema the AI will see. |
| `step04_links.py` | Step 4: finds the links between tables and tests each one against the data. |
| `knowledge/tables.yaml` | What each table and column means, written by hand. Edit it to correct a description. |
| `knowledge/links.yaml` | Link hints written by hand (odd column names, lists, two-column links). |
| `catalog/` | What the steps learn about the database. On this machine only (git-ignored), because it describes the organization's database. |
| `.env` | Database login and AI key. Never in git. |
| `requirements.txt` | The Python packages the project needs. |

## Setup

1. Python 3.14. Create the environment once: `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`.
2. A `.env` file in the project folder with `DB_SERVER`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` (and later `AI_API_KEY`). Never commit it.

## Words used in these documents

| Word | Meaning | Example |
|---|---|---|
| Database | One big store of company data. | EPM_For_Automation |
| Schema | A folder inside the database that groups tables. | `dbo` (the main one), `EAMS`, `settle` |
| Table | A grid of data about one kind of thing. | `BILL`: one row per bill |
| Column | One field in a table. | `BILL.DATEOFSERVICE` |
| Row | One record. | One bill |
| View | A saved query that looks like a table. | |
| Primary key | The column that uniquely identifies each row. | `BILLID` in `BILL` |
| Link (foreign key) | A column that points to a row in another table. | `BILL.CASEID` → `CASEINFO` |
| SQL | The language used to ask a database for data. | `SELECT COUNT(*) FROM dbo.BILL` |
| Catalog | The database's own list of its tables and columns. It holds no business data. | |
| Prompt | The text we send to the AI. | |
| RAG | *Retrieval-Augmented Generation*: find the relevant pieces first, then give only those to the AI. | |
