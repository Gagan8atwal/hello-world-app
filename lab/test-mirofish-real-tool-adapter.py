"""Pure contract tests. Does not mock or certify actual OASIS execution."""
from pathlib import Path
import runpy
p=Path(__file__).parent / "mirofish-real-tool-adapter.py"
module=runpy.run_path(str(p))
parse=module["parse_actual_model_choice"]
format_msg=module["make_model_driven_tool_response"]
tools=[{"type":"function","function":{"name":"create_post",
            "description":"Create a social media post",
            "parameters":{"type":"object",
                          "properties":{"content":{"type":"string"}},
                          "required":["content"]}}}]
valid='<tool_call>{"name":"create_post","arguments":{"content":"A real test post"}} </tool_call>'
assert parse(valid,tools)["function"]["name"] == "create_post"
assert parse(valid,tools)["function"]["arguments"] == '{"content": "A real test post"}'
assert parse('<tool_call>{"name":"create_post","arguments":{}}</tool_call>', tools) is None
assert parse('<tool_call>{"name":"secret_tool","arguments":{"content":"xx"}}</tool_call>',tools) is None
assert parse('I recommend posting a message',tools) is None
msg,finish,is_call=format_msg(valid,{"tools":tools})
assert is_call is True and finish=="tool_calls" and msg["content"] is None
msg,finish,is_call=format_msg("plain reply",{"tools":tools})
assert is_call is False and msg["content"]=="plain reply"
print("TOOL_PROTOCOL_VALIDATION=PASS")
