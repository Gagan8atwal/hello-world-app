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
MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
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
OASIS_ROUNDS = 3  # genuine LLM rounds; exclude round-zero setup posts

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
    n1=store.add_node("Fictional Customer", ["Person"], "Fictional customer requesting a vehicle-repair quote",
                      {"age": 35, "role": "buyer", "interested_topics":["phone","repairs"]})
    n2=store.add_node("Fictional Shopkeeper", ["Person"], "Fictional small business owner",
                      {"age": 40, "role": "operator", "interested_topics":["business","service"]})
    store.add_edge("asks", "Fictional Customer asks Fictional Shopkeeper about vehicle repairs", n1, n2)
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
            "Model two fictional people discussing a missed repair-quote call in an auto shop.",
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
                     "total_simulation_hours":OASIS_ROUNDS,"minutes_per_round":60})
    assert len(data.get("agent_configs",[]))==2
    for a in data["agent_configs"]:
        a["active_hours"]=list(range(OASIS_ROUNDS))
        a["activity_level"]=1.0
    # Upstream may mistakenly credit round-zero manual setup posts in round 1
    # because the SQLite trace scanner begins with last_rowid=0. Disable
    # setup posts: every counted action must be a genuine OASIS LLM action.
    data.setdefault("event_config", {})["initial_posts"] = []
    config.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return {"simulation_id":state.simulation_id,"profiles":state.profiles_count,
            "config_exists":True,"synthetic_lab_agent_activation": f"two agents across {OASIS_ROUNDS} genuine rounds, zero setup posts",
            "model_calls":counts["model_inferences"]}

def oasis_one_round():
    assert state is not None
    path=pathlib.Path(simulation.SIMULATION_DATA_DIR)/state.simulation_id
    out=path/"oasis.out"
    runner = source/"backend"/"scripts"/"run_parallel_simulation.py"
    args = [sys.executable, str(runner), "--config", str(path/"simulation_config.json"),
            "--reddit-only", "--max-rounds", str(OASIS_ROUNDS), "--no-wait"]
    before_calls=counts["model_inferences"]
    p=subprocess.run(args, cwd=source/"backend", env=os.environ.copy(),
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=600)
    out.write_text(p.stdout[-20000:])
    assert p.returncode == 0, f"OASIS process exited {p.returncode}: {p.stdout[-2000:]}"
    import runpy
    qa=runpy.run_path("lab/mirofish-evidence-qa.py")
    evidence=qa["inspect_agent_actions"](path)
    print("OASIS_GENUINE_ACTION_PROOF=" + json.dumps(evidence, sort_keys=True), flush=True)
    assert evidence["distinct_agent_ids"] >= 2, "Need model-driven actions by two distinct agents"
    # Record ONLY verified round >=1 OASIS actions as graph facts so native
    # retrieval can discover them. The local store uses exact SQL LIKE terms.
    from app.services.local_graph_store import LocalGraphStore
    store = LocalGraphStore(GRAPH_ID)
    run_node = store.add_node("OASIS Verified Round", ["Run"],
                              "Genuine OASIS action-log evidence")
    actor_nodes = {}
    observed = 0
    for action_file in path.rglob("actions.jsonl"):
        for line in action_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (row.get("action_type") and int(row.get("round") or 0) >= 1
                    and isinstance(row.get("agent_id"), int) and row.get("success") is True):
                agent_id = row["agent_id"]
                if agent_id not in actor_nodes:
                    actor_nodes[agent_id] = store.add_node(
                        f"OASIS Agent {agent_id}", ["AgentEvidence"],
                        "Synthetic agent identifier from authentic OASIS action log")
                store.add_edge("observed_action",
                    f"OASIS round {row['round']}: agent {agent_id} successfully performed "
                    f"{row['action_type']}; source=actions.jsonl. "
                    "Separate source graph fact: Fictional Customer asks "
                    "Fictional Shopkeeper about vehicle repairs. "
                    "This trial did not measure actual customer phone calls or sales.",
                    actor_nodes[agent_id], run_node)
                observed += 1
    assert observed == evidence["real_agent_actions"] >= 2
    assert store.search_edges("OASIS round"), "Verified actions not graph-searchable"
    assert counts["model_inferences"] > before_calls, "OASIS did not call real local model"
    return {"rounds_requested":OASIS_ROUNDS,"action_evidence":evidence,
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

    # Normalize upstream's documented <tool> response to its actual parser tag,
    # without inventing a call or completion. Actual Qwen output is preserved.
    original_parser = report_mod.ReportAgent._parse_tool_calls
    def parse_upstream_compatible(self, response):
        parsed = original_parser(self, response)
        if parsed:
            return parsed
        if "<tool>" in response and "</tool>" in response:
            return original_parser(self, response.replace("<tool>", "<tool_call>")
                                          .replace("</tool>", "</tool_call>"))
        return []
    report_mod.ReportAgent._parse_tool_calls = parse_upstream_compatible

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
        "You are the factual report writer for an entirely FICTIONAL MiroFish/OASIS simulation.\n"
        "Scenario: {simulation_requirement}\n"
        "Report title: {report_title}. Current section: {section_title}. Summary: {report_summary}.\n"
        "Source graph names are EXACTLY: Fictional Customer; Fictional Shopkeeper.\n"
        "Use both names explicitly in your final narrative, faithfully distinguishing the hypothetical missed repair-quote phone call from what social agents actually did.\n"
        "Facts about agent actions must come ONLY from successful genuine OASIS round evidence obtained with retrieval tools. Any real action is a social action, not an actual telephone contact or sale.\n"
        "No percentages, customer-contact success rates, sales forecasts, imagined calls, invented counts, business results, or causal conclusions. Never treat counts of retrieval-tool calls as phone calls.\n"
        "First THREE responses: request exactly one real graph retrieval, with this strict syntax:\n"
        "<tool_call>{{\"name\":\"quick_search\",\"parameters\":{{\"query\":\"OASIS round\"}}}}</tool_call>\n"
        "You may use panorama_search for a different graph perspective. Do not use interview_agents: this simulation is no longer live.\n"
        "AFTER the three actual retrieval responses, reply with Final Answer: and write at least two coherent, short factual paragraphs using the two exact fictional names, the observed OASIS action types and the limitations of the simulation. No Markdown headings or apologies.\n"
        "Never quote content not actually retrieved. Never state any simulated predictions as real-world results."
    )
    report_mod.SECTION_USER_PROMPT_TEMPLATE = (
        "Draft the report section {section_title}, distinct from earlier sections: {previous_content}\n"
        "Both known fictional roles are Fictional Customer and Fictional Shopkeeper. After verifying graph events via the real tool, include their exact names in the report. Evidence only; no statistics about phone-call handling, customers or sales.\n"
        "First output ONE <tool_call> request to retrieve OASIS round facts. Do not give your final answer until THREE real retrieval tools have run."
    )
    # Qwen needs an executable example at every retry, not upstream's vague
    # natural-language hints that fail the actual <tool_call> parser.
    retry_example = ('<tool_call>{"name":"quick_search",'
                     '"parameters":{"query":"OASIS round"}}</tool_call>')
    # These strings are subsequently interpolated using str.format(). Escape
    # JSON braces while retaining the separately formatted counter fields.
    retry_example = retry_example.replace("{", "{{").replace("}", "}}")
    report_mod.REACT_INSUFFICIENT_TOOLS_MSG = (
        "More REPORT-WRITING graph retrieval operations are necessary, "
        "not customer telephone calls. Reply with ONLY " + retry_example
    )
    report_mod.REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
        "Additional GRAPH RETRIEVAL is mandatory. These are not business "
        "contact counts. Reply ONLY with " + retry_example
    )
    report_mod.REACT_UNUSED_TOOLS_HINT = ""
    report_mod.REACT_OBSERVATION_TEMPLATE = (
        "VERIFIED GRAPH EVIDENCE ({tool_name}):\\n{result}\\n"
        "This is actual simulation graph evidence. Do not infer any business "
        "contact rates, telephone call attempts or customer conversions "
        "from the software retrieval counter. For further evidence reply ONLY "
        "with " + retry_example +
        " Once the required three retrievals have executed, start Final Answer: "
        "and write two short paragraphs mentioning Fictional Customer, "
        "Fictional Shopkeeper, observed action types, and uncertainty."
    )
    # The upstream ReACT loop has only five turns for three retrieval calls
    # plus a final answer. Small CPU models often waste turns on prose.
    # Extend its iteration budget without weakening the retrieval evidence gate.
    original_section_method = report_mod.ReportAgent._generate_section_react
    import inspect
    source = inspect.getsource(original_section_method)
    assert "max_iterations = 5  # Max iterations" in source
    namespace = {}
    patched_source = source.replace("max_iterations = 5  # Max iterations",
                                    "max_iterations = 10  # Lab-only retry budget")
    patched_source = __import__("textwrap").dedent(patched_source)
    exec(compile(patched_source, "<lab-report-iteration-adapter>", "exec"),
         original_section_method.__globals__, namespace)
    report_mod.ReportAgent._generate_section_react = namespace["_generate_section_react"]

    report_mod.REACT_FORCE_FINAL_MSG = (
        "Write Final Answer: followed by a factual section. The scenario names are Fictional Customer and Fictional Shopkeeper; use them verbatim, and describe only actions actually present in the retrieved OASIS graph facts. The missed call is a FICTIONAL premise, not a recorded telephone interaction. No percentages, no 3-of-5 call counts, no business rates or unsupported forecasts. Mention the severe limits of this small simulated trial. No headings."
    )
    requirement = (
        "Verified scenario graph: Fictional Customer asks Fictional Shopkeeper "
        "about vehicle repairs. Hypothetical premise: an auto-repair shop "
        "missed a customer phone call. The telephone event is not observed. "
        f"Genuine OASIS actions recorded: {action_evidence['real_agent_actions']} "
        f"successful actions of types {', '.join(action_evidence['action_types'])} "
        f"by {action_evidence['distinct_agent_ids']} distinct agents. "
        "This tiny synthetic trial contains no sales or customer-contact measurements."
    )
    agent = report_mod.ReportAgent(
        graph_id=GRAPH_ID, simulation_id=state.simulation_id,
        simulation_requirement=requirement)
    before = counts["model_inferences"]
    report = agent.generate_report(report_id="public_oss_report")
    # Export upstream's genuine section-by-section trace, including failed QA.
    pathlib.Path("mirofish-report-agent-log.jsonl").write_text(
        pathlib.Path(agent.report_logger.log_file_path).read_text(encoding="utf-8"),
        encoding="utf-8")
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
    for sec in sections:
        idx = sec.get("section_index")
        relevant = [r for r in tool_results if r.get("section_index") == idx]
        assert len(relevant) >= 3, f"Section {idx} lacks three real tool results"
        assert any("OASIS round" in str(r.get("details", {}).get("result", ""))
                   for r in relevant), f"Section {idx} did not retrieve verified OASIS action evidence"
        assert all("Tool execution failed:" not in str(r.get("details", {}).get("result", ""))
                   for r in relevant), f"Section {idx} used failed retrieval results"
    quality = qa["inspect_report"](body)
    assert "Fictional Customer" in body and "Fictional Shopkeeper" in body, (
        "Report lacks exact names from the source graph")
    assert counts["endpoint_errors"] == 0, "Local Qwen endpoint errors occurred"
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
                        if stage("oasis_real_agents", oasis_one_round):
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
