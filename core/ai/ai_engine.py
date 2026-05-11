# core/ai/ai_engine.py
"""
AI-powered features for AI tool.
All functions gracefully degrade when OpenAI key is absent.
"""

import json
import os
from typing import Dict, Any, List, Optional, Union
import pandas as pd
from openai.types.chat import ChatCompletionMessageParam
from openai import AzureOpenAI


# -------------------------------------------------
# OpenAI client (lazy, reusable)
# -------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        

        if not api_key or not endpoint:
            return None

        

        _client = AzureOpenAI(
            api_key=api_key,
            api_version="2024-02-15-preview",
            azure_endpoint=endpoint,
            
        )
    return _client


def ai_available() -> bool:
    return (
        os.environ.get("AZURE_OPENAI_API_KEY") is not None and
        os.environ.get("AZURE_OPENAI_ENDPOINT") is not None and
        os.environ.get("AZURE_CHAT_DEPLOYMENT") is not None

    )


def _chat(system: str, user: str, json_mode: bool = False, model: Optional[str] = None) -> Optional[str]:
    client = _get_client()
    if client is None:
        return None

    # ✅ Always resolve model here (single source of truth)
    model = model or os.getenv("AZURE_CHAT_DEPLOYMENT")
    print(model)

    if not model:
        return "[AI Error] Missing AZURE_CHAT_DEPLOYMENT"

    try:
        # ✅ FIX: Modify system BEFORE building messages
        if json_mode:
            system = system + "\nReturn strictly valid JSON."

        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        # ✅ JSON mode (works with Azure GPT-4 deployments)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = client.chat.completions.create(**kwargs)

        if resp and resp.choices:
            return resp.choices[0].message.content or ""

        return "[AI Error] Empty response"

    except Exception as e:
        return f"[AI Error] {e}"


def _chat_json(system: str, user: str, model=None) -> Optional[Dict]:
    """Chat call that returns parsed JSON."""

    # ✅ FIX: Resolve model at runtime (not import time)
    model = model or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

    raw = _chat(system, user, json_mode=True, model=model)

    if raw is None:
        return None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # ✅ Return structured fallback so UI can handle it
        return {"raw_response": raw}


# =================================================
# FEATURE 1: AI Mapping Validator
# =================================================
def ai_validate_mapping(mapping: Dict[str, Any]) -> Optional[Dict]:
    """
    Review extracted mapping for issues.
    Returns confidence scores and flagged problems.
    """
    system = """You are a senior data engineer reviewing SQL mapping metadata.
Analyze the mapping and return ONLY JSON with:
{
  "overall_confidence": 0-100,
  "tables_review": {
    "count": int,
    "tables": [...],
    "issues": [...]
  },
  "joins_review": {
    "count": int,
    "confidence": 0-100,
    "issues": ["potential cartesian join between X and Y", ...]
  },
  "filters_review": {
    "count": int,
    "issues": [...]
  },
  "column_mapping_review": {
    "count": int,
    "confidence": 0-100,
    "type_mismatches": ["column X looks like date but mapped as string", ...],
    "suspicious_transformations": [...]
  },
  "recommendations": ["Add filter for ...", "Consider LEFT JOIN instead of INNER for ...", ...]
}
Be specific and actionable. Flag real issues, not generic advice."""

    return _chat_json(system, json.dumps(mapping, indent=2, default=str))


# =================================================
# FEATURE 2: AI Data Quality Summary
# =================================================
def ai_dq_summary(
    table_name: str,
    dq_metrics: Dict[str, Any],
    column_health: pd.DataFrame,
    sample_rows: int = 0,
) -> Optional[str]:
    """
    Generate narrative DQ summary for a table.
    """
    system = """You are a data quality analyst. Given profiling metrics, write a concise
2-3 paragraph narrative summary. Highlight:
- Overall health assessment
- Specific columns with issues (high nulls, low cardinality, etc.)
- Actionable recommendations
Use markdown formatting with bold for column names and metrics."""

    health_data = column_health.to_dict("records") if isinstance(column_health, pd.DataFrame) else column_health

    user = json.dumps({
        "table": table_name,
        "summary": dq_metrics,
        "column_health": health_data,
        "sample_rows": sample_rows,
    }, indent=2, default=str)

    return _chat(system, user)


# =================================================
# FEATURE 3: AI Scenario Enrichment (Edge Cases)
# =================================================
def ai_suggest_edge_cases(
    mapping: Dict[str, Any],
    existing_scenarios: List[Dict],
    target_table: str,
) -> Optional[Dict]:
    """
    Suggest additional edge case scenarios.
    """
    system = """You are a QA engineer specializing in data testing.
Given the mapping logic and existing test scenarios, suggest edge cases that are NOT covered.
Return ONLY JSON:
{
  "edge_cases": [
    {
      "name": "Boundary: max quantity",
      "operation": "INSERT",
      "description": "Test with maximum integer quantity to check overflow",
      "column": "Quantity",
      "test_value": 2147483647,
      "priority": "HIGH"
    },
    ...
  ],
  "coverage_gaps": ["NULL handling for CurrencyCode", "Negative prices", ...],
  "total_suggested": int
}
Suggest 5-10 specific, actionable edge cases."""

    # Summarize existing scenarios (don't send all data)
    scenario_summary = {
        "total": len(existing_scenarios),
        "operations": {},
    }
    for s in existing_scenarios[:20]:
        op = s.get("operation", "UNKNOWN")
        scenario_summary["operations"][op] = scenario_summary["operations"].get(op, 0) + 1

    user = json.dumps({
        "target_table": target_table,
        "mapping": mapping,
        "existing_scenarios_summary": scenario_summary,
    }, indent=2, default=str)

    return _chat_json(system, user)


# =================================================
# FEATURE 4: AI Root Cause Analysis
# =================================================
def ai_root_cause_analysis(
    scenario: Dict,
    validation_result: Dict,
    mapping: Optional[Dict] = None,
) -> Optional[str]:
    """
    Explain why a scenario failed in natural language.
    """
    system = """You are a data validation expert. A test scenario failed during Snowflake validation.
Analyze the scenario, expected values, actual values, and mismatches.
Provide:
1. **Root Cause**: What specifically went wrong
2. **Likely Source**: Where in the data pipeline the issue originated
3. **Fix Suggestion**: How to resolve it
Be concise and specific. Use markdown."""

    user = json.dumps({
        "scenario": scenario,
        "validation_result": validation_result,
        "mapping_context": mapping,
    }, indent=2, default=str)

    return _chat(system, user)


# =================================================
# FEATURE 5: AI Chat Assistant
# =================================================
def ai_chat(
    user_message: str,
    session_context: Dict,
    chat_history: List[Dict],
) -> Optional[str]:
    """
    Context-aware chat assistant.
    """
    system = f"""You are AI assistant, an assistant for the Agentic Data Testing Platform.
You help users understand their data quality results, mapping coverage, and test scenarios.

Current session context:
{json.dumps(session_context, indent=2, default=str)}

Answer questions concisely using the context above. If data isn't available yet,
tell the user which tab/step to complete first. Use markdown formatting."""

    client = _get_client()
    if client is None:
        return None
    try:
        messages: List[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
        # Add recent chat history (last 10 messages)
        for msg in chat_history[-10:]:
            messages.append(msg)  # type: ignore
        messages.append({"role": "user", "content": user_message})

        model = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        if not model:
            return "[AI Error] Missing AZURE_OPENAI_DEPLOYMENT_NAME"

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        
        return resp.choices[0].message.content
    except Exception as e:
        return f"[AI Error] {e}"


# =================================================
# FEATURE 6: Natural Language to SQL
# =================================================
def ai_nl_to_sql(
    question: str,
    database: str,
    schema: str,
    table: str,
    column_info: Optional[List[str]] = None,
) -> Optional[Dict]:
    """
    Convert natural language question to Snowflake SQL.
    """
    system = """You are a Snowflake SQL expert. Convert the user's natural language question
into a valid Snowflake SQL query. Return ONLY JSON:
{
  "sql": "SELECT ...",
  "explanation": "This query ...",
  "confidence": 0-100
}
Rules:
- Always use fully qualified table names: DATABASE.SCHEMA.TABLE
- Add LIMIT 100 for safety unless the user asks for aggregation
- Use standard Snowflake SQL syntax"""

    col_info = f"\nAvailable columns: {column_info}" if column_info else ""

    user = f"""Database: {database}
Schema: {schema}
Table: {table}{col_info}

Question: {question}"""

    return _chat_json(system, user)


# =================================================
# FEATURE 7: AI Data Quality Insights (Anomalies)
# =================================================
def ai_dq_anomalies(
    table_name: str,
    column_health: pd.DataFrame,
    df_sample: pd.DataFrame,
) -> Optional[Dict]:
    """
    Detect anomalies and suggest investigations.
    """
    system = """You are a data quality detective. Analyze column health and sample data
to find anomalies. Return ONLY JSON:
{
  "anomalies": [
    {
      "column": "column_name",
      "type": "outlier|missing_pattern|format_inconsistency|suspicious_distribution",
      "description": "...",
      "severity": "HIGH|MEDIUM|LOW",
      "investigation": "Suggested next step..."
    }
  ],
  "overall_risk": "HIGH|MEDIUM|LOW",
  "summary": "One line summary"
}"""

    health_data = column_health.to_dict("records") if isinstance(column_health, pd.DataFrame) else column_health

    # Send a small sample of actual data for pattern detection
    sample_data = df_sample.head(5).to_dict("records") if isinstance(df_sample, pd.DataFrame) else []

    user = json.dumps({
        "table": table_name,
        "column_health": health_data,
        "sample_data": sample_data,
    }, indent=2, default=str)

    return _chat_json(system, user)


# =================================================
# FEATURE 8: Smart Mapping Suggestions
# =================================================
def ai_mapping_suggestions(
    mapping: Dict[str, Any],
    available_tables: List[str],
) -> Optional[Dict]:
    """
    Suggest which source tables are needed and detect column mismatches.
    """
    system = """You are a data mapping expert. Given extracted mapping metadata and
a list of available source tables in the data directory, identify:
1. Which available tables likely correspond to tables referenced in the mapping
2. Column name mismatches (e.g., 'cpty_id' in data vs 'CounterpartyId' in mapping)
3. Missing tables that need to be provided

Return ONLY JSON:
{
  "table_matches": [
    {
      "mapping_table": "SRC_TRADES",
      "best_match": "SRC_TRADES",
      "confidence": 100,
      "alt_matches": []
    }
  ],
  "column_mismatches": [
    {
      "mapping_column": "CounterpartyId",
      "likely_data_column": "cpty_id",
      "table": "SRC_COUNTERPARTY"
    }
  ],
  "missing_tables": ["TABLE_X"],
  "suggestions": ["Consider adding REF_CURRENCY for currency conversion logic"]
}"""

    user = json.dumps({
        "mapping": mapping,
        "available_tables": available_tables,
    }, indent=2, default=str)

    return _chat_json(system, user)


# =================================================
# FEATURE 9: AI Test Report
# =================================================
def ai_generate_report(
    session_data: Dict,
) -> Optional[str]:
    """
    Generate a comprehensive markdown test report.
    """
    system = """You are a test report generator. Create a professional markdown test report
covering all available data. Include:

# AI tool Test Report

## Executive Summary
(1-2 sentences overview)

## Mapping Analysis
(Source tables, joins, filters, coverage)

## Data Quality
(Per-table health, failed columns, recommendations)

## Test Scenarios
(Counts by operation, coverage metrics)

## Validation Results
(Pass/fail rates, failure patterns)

## Recommendations
(Priority-ordered action items)

Use tables, bullet points, and emojis for readability.
Only include sections for which data is available."""

    user = json.dumps(session_data, indent=2, default=str)
    return _chat(system, user)


# =================================================
# FEATURE 10: AI Status Messages
# =================================================
AI_STATUS_MESSAGES = {
    "mapping_extract": [
        "🔍 Parsing mapping document...",
        "🧬 Extracting source tables and joins...",
        "🔗 Resolving column transformations...",
        "✅ Mapping extraction complete!",
    ],
    "profiling": [
        "📊 Analyzing column distributions...",
        "🔬 Computing null percentages and cardinality...",
        "🧪 Evaluating column health thresholds...",
        "🎯 Generating variance samples...",
        "✅ Profiling complete!",
    ],
    "scenarios": [
        "🧩 Reading profiled data...",
        "🔗 Joining source tables...",
        "📝 Generating INSERT scenarios...",
        "✏️ Building UPDATE scenarios...",
        "🗑️ Creating DELETE scenarios...",
        "✅ Scenarios ready!",
    ],
    "validation": [
        "❄️ Connecting to Snowflake...",
        "🔍 Executing scenario validations...",
        "📊 Comparing expected vs actual...",
        "✅ Validation complete!",
    ],
    "ai_review": [
        "🤖 AI is reviewing your data...",
        "🧠 Analyzing patterns and anomalies...",
        "💡 Generating insights...",
        "✅ AI analysis complete!",
    ],
}
