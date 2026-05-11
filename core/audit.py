import json
from datetime import datetime
from typing import Dict, Any

def make_audit(user_text: str, plan: Dict[str, Any], sampler_used: str, summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts": datetime.utcnow().isoformat() + "Z",
        "user_text": user_text,
        "plan": plan,
        "sampler_used": sampler_used,
        "dq_summary": summary,
    }

def append_audit_jsonl(audit_path: str, record: Dict[str, Any]) -> None:
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
