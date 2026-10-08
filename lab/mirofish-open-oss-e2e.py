#!/usr/bin/env python3
"""Public open-source-only MiroFish end-to-end compatibility experiment.

The experiment does NOT read ALOS private source, any API keys, real customer data,
or production workloads. A genuine locally executed language model backs the
upstream graph/simulation/report stages. No mocked AI completions are accepted.
"""
import json, os, pathlib, subprocess, sys, tempfile, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PIN = "8d4eea4dfa981ecd23c3b385953b4085dfd9b6ca"
UPSTREAM = "https://github.com/shayswrld/mirofish.git"
MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
OUTPUT = pathlib.Path("mirofish-real-e2e.json").resolve()
RESULT = {"test": "MiroFish public OSS end-to-end test",
          "upstream": UPSTREAM, "upstream_sha": PIN, "model": MODEL_ID,
          "data": "synthetic", "production_secrets_used": False,
          "paid_model_api_calls": 0, "full_e2e_certified": False,
          "steps": {}, "overall": "FAIL"}
counts = {"chat_completions": 0, "model_inferences": 0, "endpoint_errors": 0}
scratch = pathlib.Path(tempfile.mkdtemp(prefix="mirofish-public-oss-"))
source = scratch / "MiroFish"
model = tokenizer = torch = server = None
lock = threading.Lock()
simulation = state = None
GRAPH_ID = "fictional_biz_agents"

def stage(name, fn):
    start = time.monotonic()
    try:
        detail = fn()
        RESULT["steps"][name] = {"status": "PASS", "seconds": round(time.monotonic() - start, 2),
                                  "details": detail}
        print("PROOF_STAGE_PASS", name, flush=True)
        return True
    except Exception as err:
        RESULT["steps"][name] = {"status": "FAIL", "seconds": round(time.monotonic() - start, 2),
                                  "error": (type(err).__name__ + ": " + str(err))[:1500],
                                  "traceback_tail": traceback.format_exc()[-1000:]}
        print("PROOF_STAGE_FAIL", name, str(err)[:750], flush=True)
        return False

def cmd(args, cwd=None, timeout=150, env=None):
    run = subprocess.run(args, cwd=cwd, env=env, timeout=timeout, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(f"command exited {run.returncode}: {run.stdout[-900:]} {run.stderr[-1200:]}")
    return run.stdout.strip()

def check_safe():
    for key in ("KAGGLE_API_TOKEN", "ALOS_GITHUB_SOURCE_TOKEN", "OPENAI_API_KEY",
                "SUPABASE_SERVICE_ROLE_KEY", "STRIPE_SECRET_KEY", "ANTHROPIC_API_KEY"):
        assert not os.environ.get(key), f"private credential unexpectedly present: {key}"
    return {"private_keys_present": False, "hosted_provider": False}

def get_upstream():
    cmd(["git", "init", "-q", str(source)])
    cmd(["git", "-C", str(source), "remote", "add", "origin", UPSTREAM])
    cmd(["git", "-C", str(source), "fetch", "--depth", "1", "origin", PIN], timeout=200)
    cmd(["git", "-C", str(source), "checkout", "-q", "FETCH_HEAD"])
    actual = cmd(["git", "-C", str(source), "rev-parse", "HEAD"])
    assert actual == PIN
    sys.path.insert(0, str(source / "backend"))
    return {"pinned_sha": actual}

def load_model():
    global model, tokenizer, torch
    import torch as t
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch = t
    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=torch.float32)
    model.eval()
    return {"parameters": sum(p.numel() for p in model.parameters()), "device": "cpu"}

def infer(messages, json_mode=False):
    messages = [m for m in messages if isinstance(m, dict)]
    conv = []
    if json_mode:
        conv.append({"role": "system", "content": "You must respond with one valid JSON object. No markdown."})
    # Preserve the report's system instructions across tool observations. The original
    # sliding window dropped them once a section needed several retrieval calls.
    recent = ([messages[0]] + messages[-8:]) if len(messages) > 9 else messages
    for m in recent:
        role = m.get("role")
        text = m.get("content", "")
        if not isinstance(text, str): text = json.dumps(text)
        conv.append({"role": role if role in ("system","user","assistant") else "user",
                     "content": text[:1800]})
    with lock:
        input_ids = tokenizer.apply_chat_template(conv, tokenize=True, add_generation_prompt=True,
                                                  return_tensors="pt")[:, -3500:]
        with torch.inference_mode():
            output = model.generate(input_ids, max_new_tokens=480, do_sample=False,
                                    pad_token_id=tokenizer.eos_token_id)
        decoded = tokenizer.decode(output[0][input_ids.shape[-1]:], skip_special_tokens=True).strip()
        counts["model_inferences"] += 1
        return decoded

class API(BaseHTTPRequestHandler):
    def log_message(self, *_args): pass
    def do_POST(self):
        if self.path.split("?")[0] != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            length=int(self.headers.get("Content-Length", "0"))
            if not (0 < length <= 250000): raise ValueError("unsupported request size")
            body = json.loads(self.rfile.read(length))
            text = infer(body.get("messages", []), (body.get("response_format") or {}).get("type") == "json_object")
            answer = {"id": "local-oss-chat", "object": "chat.completion", "created": int(time.time()),
                      "model": MODEL_ID, "choices": [{"index": 0, "finish_reason": "stop",
                          "message": {"role": "assistant", "content": text}}],
                      "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            counts["chat_completions"] += 1
            payload=json.dumps(answer).encode("utf-8")
            self.send_response(200)
        except Exception as exc:
            counts["endpoint_errors"] += 1
            payload=json.dumps({"error": {"message": str(exc)[:400], "type": "server_error"}}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

def launch_endpoint():
    global server
    server = ThreadingHTTPServer(("127.0.0.1", 8290), API)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ.update({"LLM_API_KEY": "local-only-not-a-real-token",
                       "LLM_BASE_URL": "http://127.0.0.1:8290/v1",
                       "LLM_MODEL_NAME": MODEL_ID,
                       "OPENAI_API_KEY": "local-only-not-a-real-token",
                       "OPENAI_API_BASE_URL": "http://127.0.0.1:8290/v1",
                       "OPENAI_BASE_URL": "http://127.0.0.1:8290/v1"})
    return {"endpoint": "loopback-only", "model": MODEL_ID}

def llm_client():
    from app.utils.llm_client import LLMClient
    response = LLMClient().chat([{"role": "user", "content":
                                  "In one short sentence, explain what happens when a fictional auto shop misses a customer call."}])
    assert len(response) >= 15
    return {"response": response[:350], "real_inferences": counts["model_inferences"]}

def graph():
    from app.services import local_graph_store as mod
    mod.GRAPH_DIR = str(scratch / "graphs")
    store = mod.LocalGraphStore(GRAPH_ID)
    store.set_meta("Sample case", "Synthetic missed call scenario",
                   {"entity_types":[{"name":"Person"}], "edge_types":[{"name":"asks"}]},
                   "2026-10-08T00:00:00Z")
    n1=store.add_node("Fictional Customer", ["Person"], "Fictional person seeking a quote",
                      {"age": 35, "role": "buyer", "interested_topics":["phone","repairs"]})
    n2=store.add_node("Fictional Shopkeeper", ["Person"], "Fictional small business owner",
                      {"age": 40, "role": "operator", "interested_topics":["business","service"]})
    store.add_edge("asks", "Fictional Customer asks Fictional Shopkeeper about repairs", n1, n2)
    store.add_episode("All business names and financial values are fictional.")
    assert store.get_statistics()["node_count"] == 2
    assert store.get_statistics()["edge_count"] == 1
    return {"synthetic_people": 2, "synthetic_relationships": 1}

def prepare():
    global simulation, state
    from app.services.simulation_manager import SimulationManager
    SimulationManager.SIMULATION_DATA_DIR = str(scratch / "simulations")
    simulation=SimulationManager()
    state=simulation.create_simulation("fictional_public_project", GRAPH_ID,
                                       enable_twitter=False, enable_reddit=True)
    state=simulation.prepare_simulation(state.simulation_id,
            "Model two fictional people discussing missed-call lead capture over one round.",
            "Synthetic data only; this is a bounded software test, not a business prediction.",
            defined_entity_types=["Person"], use_llm_for_profiles=False, parallel_profile_count=1)
    assert state.status.value == "ready", f"simulation not ready: {state.status}, {state.error}"
    assert state.profiles_count == 2
    folder=pathlib.Path(simulation.SIMULATION_DATA_DIR)/state.simulation_id
    config=folder/"simulation_config.json"
    assert config.exists()
    # One-round E2E must ACTIVATE real agents; first round is simulated 00:00.
    # Explicit synthetic QA overrides do not replace the upstream MiroFish engine.
    data=json.loads(config.read_text(encoding="utf-8"))
    time_cfg=data["time_config"]
    time_cfg.update({"agents_per_hour_min":2,"agents_per_hour_max":2,
                     "off_peak_activity_multiplier":1.0,"peak_activity_multiplier":1.0,
                     "total_simulation_hours":1,"minutes_per_round":60})
    assert len(data.get("agent_configs",[]))==2
    for a in data["agent_configs"]:
        a["active_hours"]=[0]
        a["activity_level"]=1.0
    config.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"simulation_id":state.simulation_id,"profiles":state.profiles_count,
            "config_exists":True,"synthetic_lab_agent_activation": "2 agents at round 1 (00:00)",
            "model_calls":counts["model_inferences"]}

def oasis_one_round():
    assert state is not None
    path=pathlib.Path(simulation.SIMULATION_DATA_DIR)/state.simulation_id
    out=path/"oasis.out"
    runner = source/"backend"/"scripts"/"run_parallel_simulation.py"
    args = [sys.executable, str(runner), "--config", str(path/"simulation_config.json"),
            "--reddit-only", "--max-rounds", "1", "--no-wait"]
    before_calls=counts["model_inferences"]
    p=subprocess.run(args, cwd=source/"backend", env=os.environ.copy(),
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
    out.write_text(p.stdout[-20000:])
    assert p.returncode == 0, f"OASIS process exited {p.returncode}: {p.stdout[-2000:]}"
    import runpy
    qa=runpy.run_path("lab/mirofish-evidence-qa.py")
    evidence=qa["inspect_agent_actions"](path)
    assert counts["model_inferences"] > before_calls, "OASIS did not call real local model"
    return {"one_round_requested":True,"action_evidence":evidence,
            "model_calls":counts["model_inferences"]}

def native_report():
    """Exercise the genuine pinned MiroFish ReportAgent with CPU-model prompts.

    This is a test-only prompt compatibility adapter: it does not replace the
    upstream outline planner, ReACT loop, retrieval tools, or report assembly.
    Every completion still comes from the locally loaded Qwen model.
    """
    assert state is not None
    import runpy
    qa = runpy.run_path("lab/mirofish-evidence-qa.py")
    sim_dir = pathlib.Path(simulation.SIMULATION_DATA_DIR) / state.simulation_id
    action_evidence = qa["inspect_agent_actions"](sim_dir)
    assert action_evidence["real_agent_actions"] >= 2

    from app.services import report_agent as report_mod

    # Upstream advertises <tool> blocks but only parses <tool_call>. The
    # tiny local model also receives >3k tokens of unrelated generic instructions.
    # Limit the task to two evidence-bound sections and an exact parser contract.
    report_mod.PLAN_SYSTEM_PROMPT = (
        "You write a factual report about a FICTIONAL agent simulation. "
        "Return ONLY valid JSON with keys title, summary, sections. "
        "sections must be a list of exactly two objects with title and description. "
        "Use specific titles about the missed customer call, the shop and the agent posts. "
        "Never use 'Section Title', generic headings, or claims of real-world outcomes."
    )
    report_mod.PLAN_USER_PROMPT_TEMPLATE = (
        "Simulation: {simulation_requirement}\n"
        "Entities: {total_nodes}; edges: {total_edges}; agents: {total_entities}.\n"
        "Recorded graph facts: {related_facts_json}\n"
        "Return a two-section JSON outline specific to the fictional shop case."
    )
    report_mod.SECTION_SYSTEM_PROMPT_TEMPLATE = (
        "You are MiroFish's simulation report writer, not a customer service chatbot.\n"
        "Synthetic scenario: {simulation_requirement}\n"
        "Report: {report_title}. Section: {section_title}. Summary: {report_summary}.\n"
        "Evidence must come from the retrieval tools; no fabricated quotes, "
        "no numerical business forecasts, no assertions about real customers.\n"
        "For your FIRST THREE replies, make exactly one tool call in this syntax:\n"
        "<tool_call>{{\"name\":\"quick_search\",\"parameters\":{{\"query\":\"Fictional Customer Fictional Shopkeeper phone repairs\"}}}}</tool_call>\n"
        "Other valid tool names: panorama_search, insight_forge. "
        "Do NOT call interview_agents because the simulation is no longer running.\n"
        "After three real tool observations, start your reply with 'Final Answer:' "
        "then write 2 grounded paragraphs with concrete scenario entities, observed "
        "agent action types, limits and uncertainty. No headings or apologies.\n"
        "Never say 'I can help', 'tool limit', 'more information', or request input."
    )
    report_mod.SECTION_USER_PROMPT_TEMPLATE = (
        "Write about {section_title}. Other sections: {previous_content}\n"
        "Step 1: call quick_search, panorama_search or insight_forge using "
        "the exact <tool_call> JSON block above. Do not write a final answer yet."
    )
    report_mod.REACT_OBSERVATION_TEMPLATE = (
        "ACTUAL retrieval result from {tool_name}:\n{result}\n"
        "Executed tool calls: {tool_calls_count}/{max_tool_calls}. Used: {used_tools_str}. "
        "{unused_hint}\n"
        "If fewer than 3 calls, issue ONE <tool_call> block with quick_search "
        "or panorama_search. If at least 3 calls, write 'Final Answer:' "
        "followed by substantive paragraphs grounded in the above results. "
        "Do not mention tools or apologize."
    )
    report_mod.REACT_FORCE_FINAL_MSG = (
        "Write Final Answer: followed by a factual, case-specific 120-word "
        "analysis of the fictional shop's missed call, the two agent posts, "
        "and the severe limits of this one-round synthetic simulation. "
        "Do not write headings or mention tools or request clarification."
    )
    requirement = (
        "Fictional Customer asked Fictional Shopkeeper about phone repairs. "
        "A fictional auto-repair shop missed a customer phone call. "
        f"An actual OASIS round completed with {action_evidence['real_agent_actions']} "
        f"successful agent actions of types {', '.join(action_evidence['action_types'])} "
        f"from {action_evidence['distinct_agent_ids']} agents. "
        "This bounded one-round synthetic experiment cannot predict revenues."
    )
    agent = report_mod.ReportAgent(
        graph_id=GRAPH_ID, simulation_id=state.simulation_id,
        simulation_requirement=requirement)
    before = counts["model_inferences"]
    report = agent.generate_report(report_id="public_oss_report")
    assert report.status.value == "completed", (
        f"report status={report.status}; reason={report.error}")
    assert counts["model_inferences"] > before, "Native report did not use local Qwen"
    body = report.markdown_content or ""
    pathlib.Path("mirofish-synthetic-report.md").write_text(body, encoding="utf-8")

    # Native report tool activity must also be recorded, not just generation logs.
    records = [json.loads(line) for line in
               pathlib.Path(agent.report_logger.log_file_path).read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    tool_calls = [r for r in records if r.get("action") == "tool_call"]
    tool_results = [r for r in records if r.get("action") == "tool_result"]
    sections = [r for r in records if r.get("action") == "section_complete"]
    assert len(sections) >= 2, "Native MiroFish report sections missing"
    assert len(tool_calls) >= 3 * len(sections), (
        f"Only {len(tool_calls)} real native retrieval calls for {len(sections)} sections")
    assert len(tool_results) >= len(tool_calls), "Retrieval tool results missing"
    quality = qa["inspect_report"](body)
    assert "Fictional Customer" in body or "Fictional Shopkeeper" in body, (
        "Report lacks names from the source graph")
    return {"chars": len(body), "report_quality": quality,
            "native_section_count": len(sections),
            "native_tool_calls": len(tool_calls),
            "native_tool_results": len(tool_results),
            "action_evidence": action_evidence,
            "report_model_inferences": counts["model_inferences"] - before}

try:
    if stage("security", check_safe) and stage("upstream", get_upstream):
        if stage("real_open_model", load_model) and stage("loopback_api", launch_endpoint):
            if stage("mirofish_real_llm_client", llm_client):
                if stage("graph_storage", graph):
                    if stage("simulation_preparation", prepare):
                        stage("oasis_real_agents", oasis_one_round)
                        stage("mirofish_report", native_report)
    required=["security","upstream","real_open_model","loopback_api",
              "mirofish_real_llm_client","graph_storage","simulation_preparation",
              "oasis_real_agents","mirofish_report"]
    RESULT["full_e2e_certified"] = all(RESULT["steps"].get(k,{}).get("status")=="PASS" for k in required)
    RESULT["overall"] = "PASS" if RESULT["full_e2e_certified"] else "PARTIAL_OR_FAIL"
finally:
    RESULT["observed"] = counts
    OUTPUT.write_text(json.dumps(RESULT, indent=2, sort_keys=True), encoding="utf-8")
    print("MIROFISH_E2E_PROOF="+json.dumps(RESULT, sort_keys=True), flush=True)
    if server: server.shutdown()
if not RESULT["full_e2e_certified"]: sys.exit(2)
