import json
import os
from typing import Dict, Any
from openai import AzureOpenAI


def get_openai_client():
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")

    if not api_key or not endpoint:
        raise ValueError("Azure OpenAI config missing")

    return AzureOpenAI(
        api_key=api_key,
        api_version="2024-02-15-preview",
        azure_endpoint=endpoint
    )


def agent_review_mapping(mapping: Dict[str, Any]) -> Dict[str, Any]:
    client = get_openai_client()

    deployment = os.getenv("AZURE_CHAT_DEPLOYMENT")
    if not deployment:
        return {"error": "Missing deployment name"}

    system = """
Return ONLY JSON.
You are a data engineering assistant.

Given extracted SQL mapping metadata:
- Validate tables
- Validate joins
- Validate target lineage

Respond with:
{
  "tables_detected": [...],
  "join_count": int,
  "target_column_count": int,
  "issues": []
}
"""

    resp = client.chat.completions.create(
        model=deployment,  # ✅ IMPORTANT (Azure uses deployment)
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(mapping, indent=2)},
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(resp.choices[0].message.content)