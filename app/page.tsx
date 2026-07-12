"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { AlertTriangle, Brain, BriefcaseBusiness, CheckCircle2, Cloud, Download, GitBranch, LayoutDashboard, Lightbulb, ListChecks, LockKeyhole, LogOut, MemoryStick, Plus, Search, Sparkles, Target } from "lucide-react";

const Graph = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Kind = "company" | "decision" | "memory" | "risk" | "task" | "pattern" | "goal";
type Node = { id: string; kind: Kind; title: string; body: string; created?: string; created_at?: string };
type Link = { source: string; target: string; type: string };
type Feedback = { id?: string; node_id?: string; useful: boolean };
type Store = { nodes: Node[]; links: Link[]; feedback: Feedback[] };
type Tab = "home" | "projects" | "decisions" | "memory" | "graph";

const emptyStore: Store = { nodes: [], links: [], feedback: [] };
const kinds: Kind[] = ["company", "decision", "memory", "risk", "task", "pattern", "goal"];

function classify(text: string, forced?: Kind): Kind {
  if (forced) return forced;
  const s = text.toLowerCase();
  if (/decid|choose|pause|stop|start/.test(s)) return "decision";
  if (/risk|danger|concern|blocked|fail/.test(s)) return "risk";
  if (/need to|must|task|next step|remind/.test(s)) return "task";
  if (/pattern|again|keeps happening|recurring/.test(s)) return "pattern";
  if (/goal|target|aim/.test(s)) return "goal";
  return "memory";
}

export default function Home() {
  const [store, setStore] = useState<Store>(emptyStore);
  const [sha, setSha] = useState("");
  const [accessKey, setAccessKey] = useState("");
  const [unlocked, setUnlocked] = useState(false);
  const [text, setText] = useState("");
  const [captureKind, setCaptureKind] = useState<Kind | "auto">("auto");
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<Tab>("home");
  const [selected, setSelected] = useState<Node | null>(null);
  const [workspace, setWorkspace] = useState<Node | null>(null);
  const [status, setStatus] = useState("Locked");
  const [saving, setSaving] = useState(false);
  const [kindFilter, setKindFilter] = useState<Kind | "all">("all");
  const [hovered, setHovered] = useState<string | null>(null);

  async function unlock() {
    setStatus("Checking password...");
    const response = await fetch("/api/memory", { headers: { "x-alos-key": accessKey } });
    const result = await response.json();
    if (!response.ok) { setStatus(response.status === 401 ? "Wrong password" : result.error || "Unable to unlock"); return; }
    setStore(result.data); setSha(result.sha); setUnlocked(true);
    setStatus(`Private memory synced • ${result.data.nodes.length} records`);
  }

  function lock() {
    setStore(emptyStore); setSha(""); setAccessKey(""); setSelected(null); setWorkspace(null); setUnlocked(false); setStatus("Locked");
  }

  async function persist(next: Store) {
    setSaving(true);
    const response = await fetch("/api/memory", { method: "PUT", headers: { "Content-Type": "application/json", "x-alos-key": accessKey }, body: JSON.stringify({ data: next, sha }) });
    const result = await response.json();
    if (response.ok) { setSha(result.sha); setStatus("Saved to private GitHub memory"); }
    else setStatus(result.error || "Sync failed");
    setSaving(false);
  }

  async function add() {
    const body = text.trim(); if (!body) return;
    const kind = classify(body, captureKind === "auto" ? undefined : captureKind);
    const id = `${kind}-${Date.now()}`;
    const node: Node = { id, kind, title: body.length > 72 ? `${body.slice(0, 69)}...` : body, body, created: new Date().toISOString() };
    const refs = store.nodes.filter((x) => x.kind === "company" && body.toLowerCase().includes(x.title.toLowerCase().replace(" llc", "")));
    const newLinks = refs.map((r) => ({ source: id, target: r.id, type: "belongs_to" }));
    const next = { ...store, nodes: [node, ...store.nodes], links: [...newLinks, ...store.links] };
    setStore(next); setText(""); await persist(next);
  }

  async function addFeedback(nodeId: string, useful: boolean) {
    const next = { ...store, feedback: [...store.feedback.filter((f) => (f.id ?? f.node_id) !== nodeId), { id: nodeId, useful }] };
    setStore(next); await persist(next);
  }

  const byKind = (kind: Kind) => store.nodes.filter((n) => n.kind === kind);
  const projects = byKind("company");
  const decisions = byKind("decision");
  const risks = byKind("risk");
  const tasks = byKind("task");
  const patterns = byKind("pattern");
  const action = tasks[0]?.title || risks[0]?.title || "Capture the highest-value blocker affecting revenue today.";
  const executionScore = Math.max(0, Math.min(100, 70 + tasks.length * 2 - risks.length * 5 - patterns.length * 2));

  const visible = useMemo(() => store.nodes.filter((n) => {
    const matchText = `${n.title} ${n.body} ${n.kind}`.toLowerCase().includes(q.toLowerCase());
    return matchText && (kindFilter === "all" || n.kind === kindFilter);
  }), [store.nodes, q, kindFilter]);

  const graphData = useMemo(() => ({
    nodes: visible.map((n) => ({ ...n, name: n.title })),
    links: store.links.filter((l) => visible.some((n) => n.id === l.source) && visible.some((n) => n.id === l.target)),
  }), [visible, store.links]);

  function related(nodeId: string) {
    const ids = new Set(store.links.flatMap((l) => l.source === nodeId ? [l.target] : l.target === nodeId ? [l.source] : []));
    return store.nodes.filter((n) => ids.has(n.id)).slice(0, 20);
  }

  function backup() {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(store, null, 2)], { type: "application/json" }));
    a.download = "alos-backup.json"; a.click();
  }

  if (!unlocked) return <main className="lock-screen"><section className="lock-card"><div className="lock-mark"><Brain/></div><small>PRIVATE FOUNDER OPERATING SYSTEM</small><h1>ALOS Second Mind</h1><p>Your projects, decisions, risks, memories, and graph remain hidden until you enter your password.</p><input type="password" value={accessKey} onChange={(e) => setAccessKey(e.target.value)} onKeyDown={(e) => e.key === "Enter" && unlock()} placeholder="Enter private password" autoFocus/><button onClick={unlock}><LockKeyhole/>Unlock ALOS</button><span>{status}</span></section></main>;

  const titles: Record<Tab, string> = { home: "Command Center", projects: "Projects", decisions: "Decisions", memory: "Memory", graph: "Knowledge Map" };
  const projectRelated = workspace ? related(workspace.id) : [];

  return <main>
    <aside>
      <div className="brand"><Brain/><b>ALOS</b><span>Second Mind</span></div>
      <button onClick={() => { setTab("home"); setWorkspace(null); }} className={tab === "home" ? "active" : ""}><LayoutDashboard/>Home</button>
      <button onClick={() => { setTab("projects"); setWorkspace(null); }} className={tab === "projects" ? "active" : ""}><BriefcaseBusiness/>Projects</button>
      <button onClick={() => { setTab("decisions"); setWorkspace(null); }} className={tab === "decisions" ? "active" : ""}><ListChecks/>Decisions</button>
      <button onClick={() => { setTab("memory"); setWorkspace(null); }} className={tab === "memory" ? "active" : ""}><MemoryStick/>Memory</button>
      <button onClick={() => { setTab("graph"); setWorkspace(null); }} className={tab === "graph" ? "active" : ""}><GitBranch/>Map</button>
      <button onClick={backup}><Download/>Backup</button><button onClick={lock}><LogOut/>Lock</button>
    </aside>

    <section className="work">
      <header><div><small>Gagandeep&apos;s cognitive operating system</small><h1>{workspace ? workspace.title : titles[tab]}</h1></div><label><Search/><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search everything"/></label></header>

      {!workspace && <><div className="capture-mode">{(["auto","task","decision","risk","memory"] as const).map(k=><button key={k} className={captureKind===k?"active":""} onClick={()=>setCaptureKind(k)}>{k}</button>)}</div><div className="capture"><textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Write naturally. ALOS will classify and connect it..."/><button onClick={add} disabled={saving}><Plus/>{saving ? "Saving" : "Save"}</button></div><p className="sync"><Cloud size={15}/>{status}</p></>}

      {workspace ? <section className="workspace">
        <button className="back-link" onClick={()=>setWorkspace(null)}>← Back to projects</button>
        <div className="workspace-hero"><div><span className="pill">project workspace</span><h2>{workspace.title}</h2><p>{workspace.body}</p></div><div className="workspace-score"><b>{projectRelated.length}</b><span>connected records</span></div></div>
        <div className="workspace-grid">
          {(["task","risk","decision","goal","pattern","memory"] as Kind[]).map(kind=><section className="panel" key={kind}><div className="panel-title"><i className={kind}/>{kind}s</div>{projectRelated.filter(n=>n.kind===kind).length ? projectRelated.filter(n=>n.kind===kind).map(n=><button className="row" key={n.id} onClick={()=>setSelected(n)}><span>{n.title}</span><small>{kind}</small></button>) : <p className="empty">No connected {kind}s yet.</p>}</section>)}
        </div>
      </section> : <>
        {tab === "home" && <>
          <section className="brief"><div><span><Sparkles/>CEO daily brief</span><h2>{action}</h2><p>Focus on one completion before switching projects. Resolve the highest-impact risk first.</p></div><div className="score"><b>{executionScore}</b><small>execution score</small></div></section>
          <div className="metric-grid"><article><b>{projects.length}</b><span>Projects</span></article><article><b>{tasks.length}</b><span>Open tasks</span></article><article><b>{risks.length}</b><span>Risks</span></article><article><b>{decisions.length}</b><span>Decisions</span></article></div>
          <div className="dashboard-grid"><section className="panel"><div className="panel-title"><Target/>Today&apos;s focus</div>{tasks.slice(0,4).map(n=><button className="row" key={n.id} onClick={()=>setSelected(n)}><span>{n.title}</span><small>task</small></button>)}</section><section className="panel"><div className="panel-title"><AlertTriangle/>Current blockers</div>{risks.slice(0,4).map(n=><button className="row" key={n.id} onClick={()=>setSelected(n)}><span>{n.title}</span><small>risk</small></button>)}</section><section className="panel"><div className="panel-title"><Lightbulb/>Patterns noticed</div>{patterns.slice(0,4).map(n=><button className="row" key={n.id} onClick={()=>setSelected(n)}><span>{n.title}</span><small>pattern</small></button>)}</section><section className="panel"><div className="panel-title"><ListChecks/>Recent decisions</div>{decisions.slice(0,4).map(n=><button className="row" key={n.id} onClick={()=>setSelected(n)}><span>{n.title}</span><small>decision</small></button>)}</section></div>
        </>}

        {tab === "projects" && <div className="project-grid">{projects.map(project => { const connected = related(project.id); return <article className="project-card" key={project.id} onClick={()=>setWorkspace(project)}><div className="type"><i className="company"/>project</div><h2>{project.title}</h2><p>{project.body}</p><div className="project-meta"><span>{connected.filter(n=>n.kind==="task").length} tasks</span><span>{connected.filter(n=>n.kind==="risk").length} risks</span><span>{connected.length} links</span></div></article> })}</div>}
        {tab === "decisions" && <div className="timeline">{decisions.map(n=><article key={n.id} onClick={()=>setSelected(n)}><div className="type"><i className="decision"/>decision</div><h3>{n.title}</h3><p>{n.body}</p><small>{n.created || n.created_at || "Stored decision"}</small></article>)}</div>}
        {tab === "memory" && <><div className="filters"><button className={kindFilter==="all"?"active":""} onClick={()=>setKindFilter("all")}>All</button>{kinds.map(k=><button key={k} className={kindFilter===k?"active":""} onClick={()=>setKindFilter(k)}>{k}</button>)}</div><div className="grid">{visible.map(n=><article key={n.id} className="card" onClick={()=>setSelected(n)}><div className="type"><i className={n.kind}/>{n.kind}</div><h3>{n.title}</h3><p>{n.body}</p></article>)}</div></>}
        {tab === "graph" && <><div className="graph-toolbar"><div className="legend">{kinds.map(k=><button key={k} className={kindFilter===k?"selected":""} onClick={()=>setKindFilter(kindFilter===k?"all":k)}><i className={k}/>{k}</button>)}</div><p>Tap a node to open it. Labels appear only for the node you touch.</p></div><div className="graph-shell"><div className="graph"><Graph graphData={graphData} nodeAutoColorBy="kind" nodeLabel="title" linkLabel={(l:any)=>l.type} cooldownTicks={90} d3AlphaDecay={0.04} d3VelocityDecay={0.55} linkDirectionalArrowLength={2} linkWidth={0.6} nodeRelSize={6} onNodeHover={(n:any)=>setHovered(n?.id ?? null)} onNodeClick={(n:any)=>setSelected(n)} nodeCanvasObject={(node:any,ctx:any,scale:number)=>{const active=hovered===node.id||selected?.id===node.id;ctx.fillStyle=node.color;ctx.beginPath();ctx.arc(node.x,node.y,active?7:4.5,0,2*Math.PI);ctx.fill();if(active){ctx.font=`600 ${13/scale}px sans-serif`;ctx.fillStyle="#f4f6fb";ctx.fillText(node.title,node.x+10,node.y+4)}}}/></div><section className="graph-guide"><h3>What this map means</h3><p>Each dot is one decision, goal, risk, task, company, pattern, or memory.</p><p>Lines show how those items relate.</p><div className="mini-list">{visible.slice(0,8).map(n=><button key={n.id} onClick={()=>setSelected(n)}><i className={n.kind}/><span>{n.title}</span></button>)}</div></section></div></>}
      </>}
    </section>

    {selected && <div className="shade" onClick={()=>setSelected(null)}><div className="drawer" onClick={e=>e.stopPropagation()}><button className="x" onClick={()=>setSelected(null)}>×</button><span className="pill">{selected.kind}</span><h2>{selected.title}</h2><p>{selected.body}</p><hr/><h3>Connected to</h3><div className="related">{related(selected.id).map(n=><button key={n.id} onClick={()=>setSelected(n)}>{n.title}<small>{n.kind}</small></button>)}</div><hr/><h3>Was this useful?</h3><div className="feedback"><button onClick={()=>addFeedback(selected.id,true)}><CheckCircle2/>Useful</button><button onClick={()=>addFeedback(selected.id,false)}><AlertTriangle/>Not useful</button></div></div></div>}
  </main>;
}
