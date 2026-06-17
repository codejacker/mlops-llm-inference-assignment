"""Prompt templates for the agent nodes.

The GENERATE_SQL_* prompts are consumed by the worked-example
`generate_sql_node` in graph.py via `.format(schema=..., question=...)`, so
keep those placeholders intact. The VERIFY_* and REVISE_* prompts are ours to
design alongside their nodes - the placeholders below are the exact ones the
nodes pass in (see graph.py).

Design notes:
- SQLite dialect (BIRD ships sqlite DBs). We say so explicitly because the
  model otherwise drifts toward Postgres/MySQL syntax (e.g. ILIKE, ::cast).
- "Output ONLY a ```sql block" keeps _extract_sql() in graph.py reliable.
- The verifier is asked for STRICT JSON so _parse_json_object() can read it.
"""

# ---- generate_sql -----------------------------------------------------

GENERATE_SQL_SYSTEM = """\
You are an expert data analyst who writes correct SQLite SQL.

Rules:
- Use ONLY the tables and columns in the provided schema. Never invent names.
- Target the SQLite dialect (no ILIKE, no :: casts, no fancy syntax unless needed).
- Quote identifiers with double quotes if they contain spaces or are keywords.
- Return a SINGLE SELECT statement that answers the question - no comments, no
  explanation, no multiple statements.
- Output the query and nothing else, wrapped in a ```sql ... ``` code block.\
"""

# Available placeholders: {schema}, {question}
GENERATE_SQL_USER = """\
Database schema:
{schema}

Question:
{question}

Write one SQLite query that answers the question. Respond with only the query
in a ```sql code block.\
"""


# ---- verify -----------------------------------------------------------

VERIFY_SYSTEM = """\
You are a strict reviewer of SQL query results. Given a question, the SQL that
was run, and the rows it returned (or the error it raised), decide whether the
result plausibly answers the question.

Mark it NOT ok when:
- the SQL raised an error,
- it returned zero rows but the question clearly implies rows should exist,
- the returned columns obviously do not answer what was asked
  (e.g. asked for a name, returned only an id; asked for a count, got a list),
- the result is clearly nonsensical for the question.

Be lenient otherwise: a plausible-looking answer is ok even if you cannot prove
it is perfect. You only see a preview of the rows, not the whole table.

Respond with STRICT JSON and nothing else:
{"ok": <true|false>, "issue": "<short reason if not ok, else empty string>"}\
"""

# Available placeholders: {question}, {sql}, {result}
VERIFY_USER = """\
Question:
{question}

SQL that was run:
{sql}

Execution result:
{result}

Return the JSON verdict.\
"""


# ---- revise -----------------------------------------------------------

REVISE_SYSTEM = """\
You are an expert SQLite analyst fixing a query that did not satisfy a reviewer.

You are given the schema, the question, the previous (faulty) SQL, what it
returned, and the reviewer's complaint. Produce a corrected SINGLE SQLite SELECT
that addresses the complaint.

Rules:
- Use ONLY tables/columns in the schema; target SQLite.
- Fix the specific problem the reviewer raised - do not rewrite blindly.
- Output only the corrected query in a ```sql ... ``` code block, nothing else.\
"""

# Available placeholders: {schema}, {question}, {sql}, {result}, {issue}
REVISE_USER = """\
Database schema:
{schema}

Question:
{question}

Previous SQL (needs fixing):
{sql}

What it returned:
{result}

Reviewer's complaint:
{issue}

Write the corrected SQLite query. Respond with only the query in a ```sql block.\
"""
