"""Protocol adapter: transform real locally generated Qwen tool choices into OpenAI tool_calls.

No fabricated actions, model text, tool arguments, or external API requests.
Reject malformed/unknown requests; only the model's own valid decisions execute.
"""
import json
import re
import uuid

def compact_functions(tools):
    result=[]
    for t in tools or []:
        if t.get("type") != "function":
            continue
        fn=t.get("function") or {}
        if not isinstance(fn.get("name"),str) or not fn.get("name"):
            continue
        result.append({"name":fn["name"],
                       "description":str(fn.get("description",""))[:200],
                       "parameters":fn.get("parameters",{"type":"object","properties":{}})})
    return result

def tool_instruction(tools):
    functions=compact_functions(tools)
    names={f["name"] for f in functions}
    # The CPU lab measures agent-generated content actions. The real OASIS
    # tool set remains authoritative. Prompt only a supported subset:
    # displaying 13 verbose tool definitions made 1.5B Qwen hallucinate
    # unsupported "join_group" even when the allowed list excluded it.
    targeted=[f for f in functions if f["name"] == "create_post"]
    if not targeted:
        targeted=[f for f in functions if f["name"] in {"create_comment","like_post"}]
    if not targeted:
        targeted=functions[:2]
    assert targeted, "No legal tools provided by upstream OASIS"
    allowed=", ".join(f["name"] for f in targeted)
    return (
        "This is an entirely fictional Reddit-style simulation. "
        "You MUST select exactly ONE FUNCTION whose name is in this allowed list: "
        + allowed + ". "
        "You are a fictional customer or shopkeeper discussing a missed repair quote. "
        "If create_post is available, write a natural original post about the fictional missed "
        "repair quote, with at least twenty words. Do not use a canned example. "
        "Never choose join_group, create_group, or any unlisted name. "
        "Return ONLY ONE JSON object with keys name and arguments. "
        "arguments must be an object of exactly the required parameters, "
        "using your own generated text. No markdown, no reasoning, no extra text.\n"
        "EXACT VALID TOOL SCHEMA:\n" + json.dumps(targeted,ensure_ascii=False,separators=(",",":"))[:1900]
    )

def parse_actual_model_choice(raw, tools):
    """Parse model-generated text only; malformed generations remain failures."""
    functions={f["name"]:f for f in compact_functions(tools)}
    if not functions:
        return None
    attempts=[]
    tags=re.findall(r"<tool_call>\s*(\{[\s\S]*?\})\s*</tool_call>",raw,re.I)
    attempts.extend(tags)
    raw_stripped=raw.strip()
    if raw_stripped.startswith("{"):
        attempts.append(raw_stripped)
    for candidate in attempts:
        try:
            item=json.loads(candidate)
            if isinstance(item,list):
                item=item[0] if len(item)==1 else {}
            name=item.get("name") or (item.get("function") or {}).get("name")
            args=item.get("arguments",item.get("args",{}))
            if isinstance(args,str):
                args=json.loads(args)
            if name not in functions or not isinstance(args,dict):
                continue
            schema=functions[name]["parameters"]
            required=schema.get("required") or []
            props=schema.get("properties") or {}
            if not all(k in args for k in required):
                continue
            if props:
                if not all(k in props for k in args):
                    continue
                if not all(
                    (not isinstance(props[k],dict))
                    or ("type" not in props[k])
                    or (props[k]["type"]!="string")
                    or isinstance(value,str)
                    for k,value in args.items()
                ):
                    continue
            return {"id":"call_"+uuid.uuid4().hex[:16], "type":"function",
                    "function":{"name":name,"arguments":json.dumps(args,ensure_ascii=False)}}
        except (ValueError,AttributeError,TypeError,KeyError):
            continue
    return None

def make_model_driven_tool_response(raw, body):
    selected=parse_actual_model_choice(raw,body.get("tools",[]))
    if not selected:
        return {"role":"assistant","content":raw}, "stop", False
    return {"role":"assistant","content":None,"tool_calls":[selected]}, "tool_calls", True
