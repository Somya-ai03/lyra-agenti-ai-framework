---
title: Agentic Data Testing Platform
emoji: "\U0001F9EC"
colorFrom: blue
colorTo: purple
sdk: streamlit
sdk_version: "1.41.0"
app_file: app.py
pinned: false
license: apache-2.0
short_description: AI assisted agentic testing framework
---

# Agentic Data Testing Platform

An AI-assisted automated testing framework that transforms SQL mapping documents and raw source data into executable test scenarios, then validates them against Snowflake target tables.

## Features

- **Mapping Extraction** - Parse Excel mapping documents to extract source tables, JOINs, WHERE filters, and column transformations
- **Data Quality Profiling** - Profile raw CSV data for nullness, cardinality, column health, and generate variance samples
- **Scenario Generation** - Automatically build INSERT, UPDATE, and DELETE test scenarios from joined/profiled data
- **Snowflake Validation** - Execute scenarios against live Snowflake target tables and compare expected vs actual results
- **Coverage Reporting** - Measure how much of the mapping logic (columns, joins, filters, transformations) is exercised by test scenarios
- **Failed Scenario Diagnostics** - Detailed root cause analysis for failed validations with suggested fixes

## Project Structure

```
.
├── app.py                    # Streamlit UI entry point
├── core/
│   ├── profiling/            # Data quality & coverage
│   ├── snowflake/            # Database operations
│   ├── scenarios/            # Test scenario generation
│   ├── agent.py              # OpenAI integration
│   └── audit.py              # Audit logging
├── cli/
│   └── run_agent.py          # CLI entry point
├── data/
│   ├── sample/               # Demo data
│   └── mapping_document/     # Excel mapping files
└── requirements.txt
```

## Quick Start

### Streamlit UI

```bash
pip install -r requirements.txt
streamlit run app.py
```

### CLI

```bash
python cli/run_agent.py
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `SNOWFLAKE_USER` | For validation | Snowflake username |
| `SNOWFLAKE_PASSWORD` | For validation | Snowflake password |
| `SNOWFLAKE_ACCOUNT` | For validation | Snowflake account identifier |
| `SNOWFLAKE_WAREHOUSE` | No | Defaults to `DEV_WH` |
| `SNOWFLAKE_ROLE` | No | Defaults to `ACCOUNTADMIN` |
| `OPENAI_API_KEY` | For AI review | OpenAI API key for mapping validation |

## HuggingFace Spaces Deployment

This app is configured for HuggingFace Spaces (Streamlit SDK). Configure the environment variables above as **Secrets** in the Space settings.

## Tech Stack

Python | Streamlit | Snowflake | OpenAI | pandas | openpyxl
