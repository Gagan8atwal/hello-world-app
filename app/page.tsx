"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { createClient, type User } from "@supabase/supabase-js";
import { AlertTriangle, Brain, CheckCircle2, Cloud, Download, GitBranch, LogIn, LogOut, Plus, Search, Target } from "lucide-react";

const Graph = dynamic(() => import("react-force-graph-2d"), { ssr: false });
const supabase = createClient(
  "https://jlueirhoepdcujzauoqy.supabase.co",
  "sb_publishable_p93W1IK6g8npq87XzUmVKA_5VyHLje-"
);

type Kind = "company" | "decision" | "memory" | "risk" | "task" | "pattern" | "goal";
type Node = { id: string; kind: Kind; title: string; body: string; created: string };
type Link = { source: string; target: string; type: string };
type Store = { nodes: Node[]; links: Link[]; feedback: { id: string; useful: boolean }[] };

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
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"home" | "graph">("home");
  const [selected, setSelected] = useState<Node | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [email, setEmail] = useState("gagan.s.atwal@gmail.com");
  const [status, setStatus] = useState("Checking secure sync...");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let channel: ReturnType<typeof supabase.channel> | null = null;

    async function boot() {
      const { data } = await supabase.auth.getSession();
      const current = data.session?.user ?? null;
      setUser(current);
      if (current) {
        await loadCloud(current.id);
        channel = supabase
          .channel("alos-live-sync")
          .on("postgres_changes", { event: "*", schema: "public", table: "alos_nodes", filter: `user_id=eq.${current.id}` }, () => loadCloud(current.id))
          .on("postgres_changes", { event: "*", schema: "public", table: "alos_links", filter: `user_id=eq.${current.id}` }, () => loadCloud(current.id))
          .on("postgres_changes", { event: "*", schema: "public", table: "alos_feedback", filter: `user_id=eq.${current.id}` }, () => loadCloud(current.id))
          .subscribe();
      } else {
        const local = localStorage.getItem("alos-v1");
        if (local) {
          try { setStore(JSON.parse(local)); } catch { setStore(emptyStore); }
        }
        setStatus("Sign in once to sync every device");
        setLoading(false);
      }
    }

    boot();
    const { data: listener } = supabase.auth.onAuthStateChange(async (_event, session) => {
      const current = session?.user ?? null;
      setUser(current);
      if (current) await loadCloud(current.id);
    });

    return () => {
      listener.subscription.unsubscribe();
      if (channel) supabase.removeChannel(channel);
    };
  }, []);

  useEffect(() => {
    if (!user && !loading) localStorage.setItem("alos-v1", JSON.stringify(store));
  }, [store, user, loading]);

  async function loadCloud(userId: string) {
    setLoading(true);
    const [{ data: nodes, error: nodeError }, { data: links, error: linkError }, { data: feedback, error: feedbackError }] = await Promise.all([
      supabase.from("alos_nodes").select("id,kind,title,body,created_at").eq("user_id", userId).order("created_at", { ascending: false }),
      supabase.from("alos_links").select("source,target,type").eq("user_id", userId),
      supabase.from("alos_feedback").select("node_id,useful").eq("user_id", userId)
    ]);

    if (nodeError || linkError || feedbackError) {
      setStatus("Sync error. Local capture remains available.");
      setLoading(false);
      return;
    }

    setStore({
      nodes: (nodes ?? []).map((n) => ({ id: n.id, kind: n.kind as Kind, title: n.title, body: n.body, created: n.created_at })),
      links: (links ?? []).map((l) => ({ source: l.source, target: l.target, type: l.type })),
      feedback: (feedback ?? []).filter((f) => typeof f.useful === "boolean").map((f) => ({ id: f.node_id, useful: f.useful as boolean }))
    });
    setStatus(`Cloud synced • ${(nodes ?? []).length} records`);
    setLoading(false);
    await migrateLocal(userId);
  }

  async function migrateLocal(userId: string) {
    const raw = localStorage.getItem("alos-v1");
    if (!raw || localStorage.getItem("alos-cloud-migrated") === "yes") return;
    try {
      const local: Store = JSON.parse(raw);
      if (local.nodes.length) {
        await supabase.from("alos_nodes").upsert(local.nodes.map((n) => ({
          id: n.id, user_id: userId, kind: n.kind, title: n.title, body: n.body, created_at: n.created, updated_at: new Date().toISOString()
        })), { onConflict: "id" });
      }
      if (local.links.length) {
        await supabase.from("alos_links").upsert(local.links.map((l) => ({ user_id: userId, source: l.source, target: l.target, type: l.type })), { onConflict: "user_id,source,target,type" });
      }
      localStorage.setItem("alos-cloud-migrated", "yes");
      localStorage.removeItem("alos-v1");
      await loadCloud(userId);
    } catch {
      setStatus("Cloud active; old local data migration needs review");
    }
  }

  async function sendMagicLink() {
    setStatus("Sending secure sign-in link...");
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: window.location.origin }
    });
    setStatus(error ? error.message : "Check your email and open the sign-in link");
  }

  async function signOut() {
    await supabase.auth.signOut();
    setUser(null);
    setStore(emptyStore);
    setStatus("Signed out");
  }

  const visible = useMemo(() => store.nodes.filter((n) => `${n.title} ${n.body} ${n.kind}`.toLowerCase().includes(q.toLowerCase())), [store.nodes, q]);
  const data = useMemo(() => ({
    nodes: visible.map((n) => ({ ...n, name: n.title })),
    links: store.links.filter((l) => visible.some((n) => n.id === l.source) && visible.some((n) => n.id === l.target))
  }), [visible, store.links]);

  async function add() {
    const body = text.trim();
    if (!body) return;
    const kind = classify(body);
    const id = `${kind}-${Date.now()}`;
    const node: Node = { id, kind, title: body.length > 72 ? `${body.slice(0, 69)}...` : body, body, created: new Date().toISOString() };
    const companyRefs = store.nodes.filter((x) => x.kind === "company" && body.toLowerCase().includes(x.title.toLowerCase().replace(" llc", "")));
    const newLinks = companyRefs.map((r) => ({ source: id, target: r.id, type: "belongs_to" }));

    setStore((s) => ({ ...s, nodes: [node, ...s.nodes], links: [...newLinks, ...s.links] }));
    setText("");

    if (user) {
      const { error } = await supabase.from("alos_nodes").insert({ id, user_id: user.id, kind, title: node.title, body, created_at: node.created, updated_at: node.created });
      if (!error && newLinks.length) await supabase.from("alos_links").insert(newLinks.map((l) => ({ ...l, user_id: user.id })));
      setStatus(error ? `Save failed: ${error.message}` : "Saved and synced");
    } else {
      setStatus("Saved on this device only — sign in to sync");
    }
  }

  async function addFeedback(nodeId: string, useful: boolean) {
    setStore((s) => ({ ...s, feedback: [...s.feedback.filter((f) => f.id !== nodeId), { id: nodeId, useful }] }));
    if (user) {
      await supabase.from("alos_feedback").upsert({ user_id: user.id, node_id: nodeId, useful, updated_at: new Date().toISOString() }, { onConflict: "user_id,node_id" });
      setStatus("Feedback synced");
    }
  }

  const action = store.nodes.find((n) => n.kind === "task")?.title || store.nodes.find((n) => n.kind === "risk")?.title || "Capture the single highest-value blocker affecting revenue today.";

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
      <a href="/today" className="navlink">Today</a>
      <button onClick={backup}><Download/>Backup</button>
      {user ? <button onClick={signOut}><LogOut/>Sign out</button> : null}
    </aside>

    <section className="work">
      <header>
        <div><small>Gagandeep&apos;s cognitive operating system</small><h1>{tab === "home" ? "Command Center" : "Knowledge Graph"}</h1></div>
        <label><Search/><input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your second mind"/></label>
      </header>

      {!user && <section className="capture" style={{gridTemplateColumns:"1fr auto"}}>
        <div>
          <strong>Secure cloud sync</strong>
          <p style={{color:"var(--muted)",margin:"6px 0 10px"}}>Sign in once by email. Your existing 29 records will appear automatically.</p>
          <input value={email} onChange={(e) => setEmail(e.target.value)} style={{width:"100%",padding:10,borderRadius:8,border:"1px solid var(--line)",background:"var(--panel)",color:"var(--text)"}} />
        </div>
        <button onClick={sendMagicLink}><LogIn/>Send link</button>
      </section>}

      <div className="capture">
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Write naturally: decision, blocker, task, lesson, pattern, risk, idea..."/>
        <button onClick={add}><Plus/>Save</button>
      </div>

      <p style={{display:"flex",alignItems:"center",gap:7,color:"var(--muted)",fontSize:12}}><Cloud size={15}/>{loading ? "Loading..." : status}</p>

      {tab === "home" ? <>
        <div className="roi"><span>Highest-ROI next action</span><h2>{action}</h2><p>Derived from your open tasks and risks.</p></div>
        <div className="stats"><article><b>{store.nodes.length}</b><span>Knowledge nodes</span></article><article><b>{store.links.length}</b><span>Connections</span></article><article><b>{store.feedback.length}</b><span>Feedback signals</span></article></div>
        <div className="grid">{visible.map((n) => <article key={n.id} className="card" onClick={() => setSelected(n)}><div className="type"><i className={n.kind}/>{n.kind}</div><h3>{n.title}</h3><p>{n.body}</p></article>)}</div>
      </> : <div className="graph"><Graph graphData={data} nodeAutoColorBy="kind" nodeLabel="title" linkLabel={(l: any) => l.type} linkDirectionalArrowLength={3} onNodeClick={(n: any) => setSelected(n)}/></div>}
    </section>

    {selected && <div className="shade" onClick={() => setSelected(null)}><div className="drawer" onClick={(e) => e.stopPropagation()}><button className="x" onClick={() => setSelected(null)}>×</button><span className="pill">{selected.kind}</span><h2>{selected.title}</h2><p>{selected.body}</p><hr/><h3>Was this useful?</h3><div className="feedback"><button onClick={() => addFeedback(selected.id, true)}><CheckCircle2/>Useful</button><button onClick={() => addFeedback(selected.id, false)}><AlertTriangle/>Not useful</button></div></div></div>}
  </main>;
}
