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
    return (
        "You are choosing one real action for a simulated social-media agent. "
        "Use the provided function schema to choose a real action, not a description. "
        "Your entire reply MUST be the following XML element with actual valid JSON. "
        "The function name must match a supplied function name and arguments must satisfy its parameters. "
        "Do not make up function names, don't add explanations, and don't output markdown.\n"
        '<tool_call>{"name":"NAME_FROM_LIST","arguments":{"parameter":"value"}}</tool_call>\n'
        "Available tools:\n" + json.dumps(functions,ensure_ascii=False)[:13000]
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
