"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Brain, CheckCircle2, Cloud, Download, GitBranch, LockKeyhole, Plus, Search, Target } from "lucide-react";

const Graph = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type Kind = "company" | "decision" | "memory" | "risk" | "task" | "pattern" | "goal";
type Node = { id: string; kind: Kind; title: string; body: string; created?: string; created_at?: string };
type Link = { source: string; target: string; type: string };
type Feedback = { id?: string; node_id?: string; useful: boolean };
type Store = { nodes: Node[]; links: Link[]; feedback: Feedback[] };

const emptyStore: Store = { nodes: [], links: [], feedback: [] };

function classify(text: string): Kind {
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
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"home" | "graph">("home");
  const [selected, setSelected] = useState<Node | null>(null);
  const [status, setStatus] = useState("Locked");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const cached = localStorage.getItem("alos-cache");
    if (cached) try { setStore(JSON.parse(cached)); } catch {}
  }, []);

  useEffect(() => {
    localStorage.setItem("alos-cache", JSON.stringify(store));
  }, [store]);

  async function unlock() {
    setStatus("Loading private memory...");
    const response = await fetch("/api/memory", { headers: { "x-alos-key": accessKey } });
    const result = await response.json();
    if (!response.ok) {
      setStatus(response.status === 401 ? "Wrong access key" : result.error || "Unable to load memory");
      return;
    }
    setStore(result.data);
    setSha(result.sha);
    sessionStorage.setItem("alos-access-key", accessKey);
    setUnlocked(true);
    setStatus(`GitHub synced • ${result.data.nodes.length} records`);
  }

  useEffect(() => {
    const saved = sessionStorage.getItem("alos-access-key");
    if (saved) { setAccessKey(saved); }
  }, []);

  async function persist(next: Store) {
    if (!unlocked) {
      setStatus("Saved offline. Unlock to sync.");
      return;
    }
    setSaving(true);
    const response = await fetch("/api/memory", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "x-alos-key": accessKey },
      body: JSON.stringify({ data: next, sha }),
    });
    const result = await response.json();
    if (response.ok) {
      setSha(result.sha);
      setStatus("Saved to private GitHub memory");
    } else {
      setStatus(result.error || "Sync failed; local copy preserved");
    }
    setSaving(false);
  }

  async function add() {
    const body = text.trim();
    if (!body) return;
    const kind = classify(body);
    const id = `${kind}-${Date.now()}`;
    const node: Node = { id, kind, title: body.length > 72 ? `${body.slice(0, 69)}...` : body, body, created: new Date().toISOString() };
    const refs = store.nodes.filter((x) => x.kind === "company" && body.toLowerCase().includes(x.title.toLowerCase().replace(" llc", "")));
    const newLinks = refs.map((r) => ({ source: id, target: r.id, type: "belongs_to" }));
    const next = { ...store, nodes: [node, ...store.nodes], links: [...newLinks, ...store.links] };
    setStore(next);
    setText("");
    await persist(next);
  }

  async function addFeedback(nodeId: string, useful: boolean) {
    const next = { ...store, feedback: [...store.feedback.filter((f) => (f.id ?? f.node_id) !== nodeId), { id: nodeId, useful }] };
    setStore(next);
    await persist(next);
  }

  const visible = useMemo(() => store.nodes.filter((n) => `${n.title} ${n.body} ${n.kind}`.toLowerCase().includes(q.toLowerCase())), [store.nodes, q]);
  const data = useMemo(() => ({
    nodes: visible.map((n) => ({ ...n, name: n.title })),
    links: store.links.filter((l) => visible.some((n) => n.id === l.source) && visible.some((n) => n.id === l.target)),
  }), [visible, store.links]);

  const action = store.nodes.find((n) => n.kind === "task")?.title || store.nodes.find((n) => n.kind === "risk")?.title || "Capture the highest-value blocker affecting revenue today.";

  function backup() {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(store, null, 2)], { type: "application/json" }));
    a.download = "alos-backup.json";
    a.click();
  }

  return <main>
    <aside>
      <div className="brand"><Brain/><b>ALOS</b><span>Second Mind</span></div>
      <button onClick={() => setTab("home")} className={tab === "home" ? "active" : ""}><Target/>Command</button>
      <button onClick={() => setTab("graph")} className={tab === "graph" ? "active" : ""}><GitBranch/>Graph</button>
      <button onClick={backup}><Download/>Backup</button>
    </aside>

    <section className="work">
      <header>
        <div><small>Gagandeep&apos;s cognitive operating system</small><h1>{tab === "home" ? "Command Center" : "Knowledge Graph"}</h1></div>
        <label><Search/><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your second mind"/></label>
      </header>

      {!unlocked && <section className="capture" style={{ gridTemplateColumns: "1fr auto" }}>
        <div>
          <strong>Unlock private memory</strong>
          <p style={{ color: "var(--muted)", margin: "6px 0 10px" }}>No Supabase login. Enter your private ALOS access key.</p>
          <input type="password" value={accessKey} onChange={(e) => setAccessKey(e.target.value)} onKeyDown={(e) => e.key === "Enter" && unlock()} style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid var(--line)", background: "var(--panel)", color: "var(--text)" }}/>
        </div>
        <button onClick={unlock}><LockKeyhole/>Unlock</button>
      </section>}

      <div className="capture">
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Write naturally: decision, blocker, task, lesson, pattern, risk, idea..."/>
        <button onClick={add} disabled={saving}><Plus/>{saving ? "Saving" : "Save"}</button>
      </div>

      <p style={{ display: "flex", alignItems: "center", gap: 7, color: "var(--muted)", fontSize: 12 }}><Cloud size={15}/>{status}</p>

      {tab === "home" ? <>
        <div className="roi"><span>Highest-ROI next action</span><h2>{action}</h2><p>Derived from your open tasks and risks.</p></div>
        <div className="stats"><article><b>{store.nodes.length}</b><span>Knowledge nodes</span></article><article><b>{store.links.length}</b><span>Connections</span></article><article><b>{store.feedback.length}</b><span>Feedback signals</span></article></div>
        <div className="grid">{visible.map((n) => <article key={n.id} className="card" onClick={() => setSelected(n)}><div className="type"><i className={n.kind}/>{n.kind}</div><h3>{n.title}</h3><p>{n.body}</p></article>)}</div>
      </> : <div className="graph"><Graph graphData={data} nodeAutoColorBy="kind" nodeLabel="title" linkLabel={(l: any) => l.type} linkDirectionalArrowLength={3} onNodeClick={(n: any) => setSelected(n)}/></div>}
    </section>

    {selected && <div className="shade" onClick={() => setSelected(null)}><div className="drawer" onClick={(e) => e.stopPropagation()}><button className="x" onClick={() => setSelected(null)}>×</button><span className="pill">{selected.kind}</span><h2>{selected.title}</h2><p>{selected.body}</p><hr/><h3>Was this useful?</h3><div className="feedback"><button onClick={() => addFeedback(selected.id, true)}><CheckCircle2/>Useful</button><button onClick={() => addFeedback(selected.id, false)}><AlertTriangle/>Not useful</button></div></div></div>}
  </main>;
}
