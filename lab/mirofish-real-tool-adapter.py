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
    targeted=[f for f in functions if f["name"] == "create_post"]
    if not targeted:
        targeted=[f for f in functions if f["name"] in {"create_comment","search_posts","refresh"}]
    if not targeted:
        targeted=functions[:3]
    if not targeted:
        raise ValueError("OASIS did not provide standard callable function tools")
    names=", ".join(f["name"] for f in targeted)
    return (
        "YOU ARE IN A SYNTHETIC TEST OF AN OASIS REDDIT-LIKE SOCIAL AGENT. "
        "Only functions listed below exist. Choose ONE of these actions in JSON "
        "using your own ORIGINAL writing. Your answer must be a SINGLE JSON object "
        "with exactly two keys: name and arguments. "
        "name MUST be one of: " + names + ". "
        "Never use join_group or other functions that are not on the list. "
        "If create_post is permitted, write a thoughtful original social media "
        "post (30 to 55 words) about how a fictional auto repair shop could reply "
        "to a fictional customer's missed quote request. "
        "Use the parameter names and required types exactly. "
        "Return JSON ONLY, no code fence or commentary. "
        "AVAILABLE FUNCTION SCHEMA: "
        + json.dumps(targeted, ensure_ascii=False, separators=(",",":"))[:3500]
    )

def isolated_agent_messages(tools, original_messages):
    # Keep factual profile context, but strip old multi-tool system directives.
    # Strong system-level format instruction prevents a small LLM hallucinating
    # functions that the OASIS agent did not actually expose.
    directive=tool_instruction(tools)
    profile=""
    for m in original_messages[-4:]:
        txt=m.get("content","")
        if isinstance(txt,str) and any(w in txt.lower() for w in ("fictional", "shopkeeper", "customer")):
            profile=txt[-400:]
            break
    return [
        {"role":"system","content":directive},
        {"role":"user","content":(
            "As a synthetic social agent, select ONE permitted function and "
            "generate ORIGINAL arguments. Scenario: fictional shopkeeper and "
            "fictional customer discussing a missed repair quote. "
            + ("Profile context: "+profile if profile else "") +
            " Reply with exactly one JSON object."
        )}
    ]

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
