"""Independent MiroFish proof validation: do not count setup events as agent actions."""
import json
import re
from pathlib import Path

def inspect_agent_actions(sim_dir):
    folder = Path(sim_dir)
    logs = list(folder.rglob("actions.jsonl"))
    assert logs, "No OASIS action logs exist"
    entries = []
    for f in logs:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                assert isinstance(row, dict), "Malformed action log row"
                entries.append(row)
    round_starts = [r for r in entries if r.get("event_type") == "round_start" and int(r.get("round") or 0) >= 1]
    round_ends = [r for r in entries if r.get("event_type") == "round_end" and int(r.get("round") or 0) >= 1]
    real_actions = [
        r for r in entries
        if r.get("action_type") and int(r.get("round") or 0) >= 1
        and isinstance(r.get("agent_id"), int) and r.get("success") is True
    ]
    assert round_starts, "No real simulation round started"
    assert round_ends, "No real simulation round completed"
    # Upstream may replay round-zero setup posts from the SQLite trace during
    # the first LLM round. This lab disables initial_posts; fail closed if
    # any setup action exists instead of miscrediting it as model-driven work.
    round_zero_actions = [r for r in entries if r.get("action_type")
                          and int(r.get("round") or 0) == 0]
    assert not round_zero_actions, "Round-zero setup posts could be counted as LLM actions"
    assert real_actions, "No genuine agent action after round 0 (only setup events)"
    assert len({r["agent_id"] for r in real_actions}) >= 2, (
        "Fewer than two distinct OASIS agents produced genuine actions")
    return {"round_starts": len(round_starts), "round_ends": len(round_ends),
            "real_agent_actions": len(real_actions),
            "action_types": sorted(set(str(x["action_type"]) for x in real_actions)),
            "distinct_agent_ids": len({x["agent_id"] for x in real_actions})}

def inspect_report(markdown):
    assert isinstance(markdown, str), "Report must be text"
    assert len(markdown.strip()) >= 300, "Generated report too short"
    heads = re.findall(r"(?m)^#{1,3}\s+(.+?)\s*$", markdown)
    normalized = [h.strip().lower() for h in heads]
    assert len(normalized) >= 2, "Too few report headings"
    assert len(set(normalized)) >= 2, "All report headings are duplicated"
    placeholders = {"section title", "untitled", "section", "placeholder", "chapter title", "your title here"}
    assert not placeholders.intersection(normalized), "Report has generated placeholder headings"
    assert re.search(r"\b(missed|call|phone|shop|lead|customer)\b", markdown, re.I), \
        "Generated report lacks any case-specific language"
    assert "Fictional Customer" in markdown and "Fictional Shopkeeper" in markdown, (
        "Native report did not ground its content in both source-graph entities")
    # Retrieval progress previously appeared as 3/5 and the small model
    # invented 60% customer contact conversion from that diagnostic counter.
    # No business measurements exist in this synthetic trial.
    assert not re.search(r"\\b(?:success|conversion|contact)\\s+rate\\b|"
                         r"\\b(?:three|3)\\s+(?:out of|of)\\s+(?:five|5)\\b|"
                         r"\\b(?:attempted contacts|five callers)\\b|"
                         r"\\b\\d+(?:\\.\\d+)?\\s*%|\\b\\d+(?:\\.\\d+)?\\s+percent\\b",
                         markdown, re.I), "Unsupported business conversion metrics in report"
    return {"characters": len(markdown), "headings": len(heads),
            "distinct_headings": len(set(normalized)), "case_specific_terms": True}
