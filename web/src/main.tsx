// SPDX-License-Identifier: MIT
// Copyright (c) 2026 John-IDK

import React, { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, type Branch, type Concept, type EntityHub, type Job, type Publication, type Role, type Source, type User } from "./api";
import "./styles.css";

type View = "dashboard" | "sources" | "search" | "review" | "publications" | "entities" | "branches" | "git" | "settings" | "users";

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.login(username, password);
      onLogin(result.user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }
  return <main className="login-shell">
    <section className="login-card">
      <p className="eyebrow">Local intelligence, accountable sources</p>
      <h1>Company Knowledge Base</h1>
      <p className="lede">Search company knowledge with a source trail. Review what the model extracts. Keep the durable record in Git.</p>
      <form onSubmit={submit}>
        <label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </section>
  </main>;
}

function Metric({ label, value, tone = "default" }: { label: string; value: string | number; tone?: string }) {
  return <article className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong></article>;
}

function Dashboard({ sources, jobs, concepts }: { sources: Source[]; jobs: Job[]; concepts: Concept[] }) {
  const reviews = concepts.filter((item) => item.status === "review").length;
  const failures = jobs.filter((item) => item.status === "failed").length;
  return <section>
    <div className="section-heading"><div><p className="eyebrow">Knowledge operations</p><h2>Overview</h2></div><p>Current state of ingestion, publication, and review.</p></div>
    <div className="metrics">
      <Metric label="Registered sources" value={sources.length} />
      <Metric label="Published concepts" value={concepts.filter((item) => item.status === "published").length} tone="green" />
      <Metric label="Waiting for review" value={reviews} tone={reviews ? "amber" : "default"} />
      <Metric label="Failed jobs" value={failures} tone={failures ? "red" : "default"} />
    </div>
    <div className="panel"><h3>Recent jobs</h3><JobTable jobs={jobs.slice(0, 8)} /></div>
  </section>;
}

function JobTable({ jobs, onAction }: { jobs: Job[]; onAction?: (id: number, action: "run" | "cancel" | "retry") => void }) {
  if (!jobs.length) return <p className="empty">No ingestion jobs yet.</p>;
  return <div className="table-wrap"><table><thead><tr><th>ID</th><th>Source</th><th>Status</th><th>Attempts</th><th>Created</th>{onAction && <th />}</tr></thead>
    <tbody>{jobs.map((job) => <tr key={job.id}><td>#{job.id}</td><td>#{job.source_id}</td><td><span className={`badge ${job.status}`}>{job.status}</span></td><td>{job.attempts}</td><td>{new Date(job.created_at).toLocaleString()}</td>{onAction && <td className="button-row">{job.status === "queued" && <><button type="button" className="ghost" onClick={() => onAction(job.id, "run")}>Run</button><button type="button" className="ghost" onClick={() => onAction(job.id, "cancel")}>Cancel</button></>}{job.status === "running" && <button type="button" className="ghost" onClick={() => onAction(job.id, "cancel")}>Cancel</button>}{["failed", "cancelled"].includes(job.status) && <button type="button" className="ghost" onClick={() => onAction(job.id, "retry")}>Retry</button>}</td>}</tr>)}</tbody></table></div>;
}

function Sources({ sources, jobs, reload, branches, branch }: { sources: Source[]; jobs: Job[]; reload: () => Promise<void>; branches: Branch[]; branch: string }) {
  const [kind, setKind] = useState<Source["kind"]>("folder");
  const [uri, setUri] = useState("");
  const [title, setTitle] = useState("");
  const [domains, setDomains] = useState("");
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setMessage("");
    try {
      await api.addSource({ kind, uri, title: title || undefined, allowed_domains: domains.split(",").map((item) => item.trim()).filter(Boolean), branch });
      setUri(""); setTitle(""); setDomains(""); await reload(); setMessage("Source registered.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not register source"); }
  }
  async function ingest(id: number) { await api.ingest(id); await reload(); }
  async function jobAction(id: number, action: "run" | "cancel" | "retry") { if (action === "run") await api.runJob(id); else if (action === "cancel") await api.cancelJob(id); else await api.retryJob(id); await reload(); }
  return <section><div className="section-heading"><div><p className="eyebrow">Source registry</p><h2>Ingest knowledge</h2></div><p>Files stay local. Websites are restricted to explicit domains.</p></div>
    <div className="two-column"><form className="panel" onSubmit={submit}><h3>Add source</h3>
      <label>Knowledge branch<select value={branch} disabled>{branches.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label>
      <label>Source type<select value={kind} onChange={(event) => setKind(event.target.value as Source["kind"])}><option value="file">File</option><option value="folder">Folder</option><option value="website">Website</option></select></label>
      <label>Path or URL<input value={uri} onChange={(event) => setUri(event.target.value)} required placeholder={kind === "website" ? "https://docs.example.com" : "C:\\Company\\Docs"} /></label>
      <label>Display title<input value={title} onChange={(event) => setTitle(event.target.value)} /></label>
      {kind === "website" && <label>Allowed domains<input value={domains} onChange={(event) => setDomains(event.target.value)} placeholder="docs.example.com" /></label>}
      <button type="submit">Register source</button>{message && <p className="notice">{message}</p>}
    </form><div className="panel"><h3>Sources</h3>{sources.filter((source) => (source.branch || "main") === branch).length ? <div className="source-list">{sources.filter((source) => (source.branch || "main") === branch).map((source) => <article key={source.id}><div><strong>{source.title || source.uri}</strong><span>{source.kind} · {source.uri}</span></div><button type="button" className="ghost" onClick={() => ingest(source.id)}>Queue ingest</button></article>)}</div> : <p className="empty">No sources registered.</p>}</div></div>
    <div className="panel"><h3>Jobs</h3><JobTable jobs={jobs} onAction={jobAction} /></div>
  </section>;
}

function SearchView({ branch }: { branch: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Concept[]>([]);
  const [semantic, setSemantic] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setMessage("Searching…");
    try { const response = await api.search(query, branch); setResults(response.results); setSemantic(response.semantic_available); setMessage(response.results.length ? "" : "No cited concepts matched."); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "Search failed"); }
  }
  async function gap() { await api.feedback(query, "Search did not answer my question."); setMessage("Added to the knowledge-gap backlog."); }
  return <section><div className="section-heading"><div><p className="eyebrow">Hybrid retrieval</p><h2>Search with evidence</h2></div><p>Vietnamese accent folding, phrase matching, BM25, and local embeddings.</p></div>
    <form className="search-box" onSubmit={submit}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder='Try "weekly revenue" or doanh thu' required /><button type="submit">Search</button></form>
    <div className="search-meta"><span>{semantic ? "Semantic + lexical ranking" : "Lexical ranking"}</span>{query && <button type="button" className="link-button" onClick={gap}>Report a knowledge gap</button>}</div>{message && <p className="notice">{message}</p>}
    <div className="result-list">{results.map((concept) => <article key={concept.id} className="result-card"><div className="result-top"><span className="badge published">{concept.type}</span><span>{concept.channels?.join(" + ")}</span></div><h3>{concept.title}</h3><p>{concept.description}</p><div className="tag-row">{concept.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div><div className="button-row"><button type="button" className="ghost" onClick={async () => { const value = await api.endorse(concept.id); setResults((items) => items.map((item) => item.id === concept.id ? { ...item, endorsements: value.endorsements } : item)); }}>Endorse ({concept.endorsements})</button><button type="button" className="link-button" onClick={async () => { const value = await api.removeEndorsement(concept.id); setResults((items) => items.map((item) => item.id === concept.id ? { ...item, endorsements: value.endorsements } : item)); }}>Remove</button></div><details onToggle={(event) => { if (event.currentTarget.open) void api.usage(concept.id); }}><summary>Open cited OKF concept</summary><pre>{concept.body}</pre></details></article>)}</div>
  </section>;
}

type ReviewClaim = { id: number; text: string; citations: Array<{ locator: string; excerpt: string; source_uri: string }> };

function ClaimEditor({ conceptId, claim, onSaved }: { conceptId: string; claim: ReviewClaim; onSaved: () => Promise<void> }) {
  const citation = claim.citations[0];
  const [text, setText] = useState(claim.text); const [locator, setLocator] = useState(citation?.locator || ""); const [excerpt, setExcerpt] = useState(citation?.excerpt || ""); const [message, setMessage] = useState("");
  async function save() { try { await api.reviseClaim(conceptId, claim.id, text, locator, excerpt); setMessage("Verified revision saved."); await onSaved(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Revision failed"); } }
  return <article className="claim-editor"><label>Claim<input value={text} onChange={(event) => setText(event.target.value)} /></label><label>Source locator<input value={locator} onChange={(event) => setLocator(event.target.value)} /></label><label>Exact source excerpt<textarea value={excerpt} onChange={(event) => setExcerpt(event.target.value)} /></label><button type="button" className="ghost" onClick={save}>Verify & save claim</button>{message && <p className="notice">{message}</p>}</article>;
}

function Review({ concepts, reload }: { concepts: Concept[]; reload: () => Promise<void> }) {
  const queue = concepts.filter((item) => item.status === "review");
  const [selected, setSelected] = useState<(Concept & { claims: ReviewClaim[] }) | null>(null);
  const [body, setBody] = useState("");
  const [message, setMessage] = useState("");
  const [gaps, setGaps] = useState<Array<{ id: number; query: string; details: string; status: string; created_at: string }>>([]);
  useEffect(() => { api.feedbackList().then(setGaps).catch(() => setGaps([])); }, []);
  async function open(id: string) { const item = await api.concept(id) as Concept & { claims: ReviewClaim[] }; setSelected(item); setBody(item.body || ""); }
  async function decide(decision: "approve" | "reject") { if (!selected) return; setMessage(""); try { await api.review(selected.id, decision, decision === "approve" ? body : undefined); setSelected(null); await reload(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Review action failed"); } }
  return <section><div className="section-heading"><div><p className="eyebrow">Human oversight</p><h2>Review queue</h2></div><p>Resolve low confidence, citation gaps, and publication conflicts.</p></div>
    {!queue.length ? <div className="panel empty">Nothing is waiting for review.</div> : <div className="review-grid"><div className="panel source-list">{queue.map((item) => <button type="button" className={`list-action ${selected?.id === item.id ? "selected" : ""}`} aria-pressed={selected?.id === item.id} key={item.id} onClick={() => open(item.id)}><div><strong>{item.title}</strong><span>{item.quality.reasons.join(" · ")}</span></div><span>{Math.round(item.quality.coverage * 100)}%</span></button>)}</div>
      <div className="panel editor">{selected ? <><h3>{selected.title}</h3><p className="notice">Coverage {Math.round(selected.quality.coverage * 100)}% · minimum confidence {selected.quality.minimum_confidence.toFixed(2)}. Citations are server-rendered and cannot be edited in Markdown.</p>{selected.claims.map((claim) => <ClaimEditor key={claim.id} conceptId={selected.id} claim={claim} onSaved={() => open(selected.id)} />)}<textarea value={body} readOnly />{message && <p className="error">{message}</p>}<div className="button-row"><button type="button" onClick={() => decide("approve")}>Approve publication</button><button type="button" className="danger" onClick={() => decide("reject")}>Reject</button></div></> : <p className="empty">Select a concept to inspect its evidence.</p>}</div></div>}
    <div className="panel"><h3>Knowledge-gap backlog</h3>{gaps.length ? <div className="source-list">{gaps.map((gap) => <article key={gap.id}><div><strong>{gap.query}</strong><span>{gap.details || "No details"}</span></div><button type="button" className="ghost" disabled={gap.status === "resolved"} onClick={async () => { await api.resolveFeedback(gap.id, "resolved"); setGaps((items) => items.map((item) => item.id === gap.id ? { ...item, status: "resolved" } : item)); }}>{gap.status}</button></article>)}</div> : <p className="empty">No unanswered questions have been reported.</p>}</div>
  </section>;
}

function PublicationsView() {
  const [items, setItems] = useState<Publication[]>([]); const [message, setMessage] = useState("");
  const reload = useCallback(() => api.publications().then(setItems), []);
  useEffect(() => { void reload(); }, [reload]);
  async function merge(id: string) { try { await api.mergePublication(id); setMessage("Publication merged into the protected canonical branch."); await reload(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Merge failed"); } }
  return <section><div className="section-heading"><div><p className="eyebrow">Protected publishing</p><h2>Publication candidates</h2></div><p>Candidate commits remain isolated until a branch administrator merges them.</p></div><div className="panel source-list">{items.length ? items.map((item) => <article key={item.id}><div><strong>{item.title}</strong><span>{item.candidate_branch} · {item.state}</span></div>{["committed", "pushed"].includes(item.state) && <button type="button" onClick={() => merge(item.id)}>Merge</button>}</article>) : <p className="empty">No publication candidates.</p>}</div>{message && <p className="notice">{message}</p>}</section>;
}

function EntitiesView({ branch }: { branch: string }) {
  const [items, setItems] = useState<EntityHub[]>([]); const [selected, setSelected] = useState<EntityHub | null>(null);
  useEffect(() => { api.entities(branch).then(setItems); setSelected(null); }, [branch]);
  async function open(id: number) { setSelected(await api.entity(id, branch)); }
  return <section><div className="section-heading"><div><p className="eyebrow">Knowledge graph</p><h2>Entity hubs</h2></div><p>Source-derived entities connect related canonical concepts.</p></div><div className="two-column"><div className="panel source-list">{items.map((item) => <button type="button" className="list-action" key={item.id} onClick={() => open(item.id)}><div><strong>{item.name}</strong><span>{item.concept_count} concepts</span></div><span>{item.pagerank.toFixed(3)}</span></button>)}</div><div className="panel">{selected ? <><h3>{selected.name}</h3><div className="source-list">{selected.concepts?.map((concept) => <article key={concept.id}><div><strong>{concept.title}</strong><span>{concept.description}</span></div></article>)}</div></> : <p className="empty">Select an entity hub.</p>}</div></div></section>;
}

function BranchesView({ current, branches, reload }: { current: User; branches: Branch[]; reload: () => Promise<void> }) {
  const [name, setName] = useState(""); const [message, setMessage] = useState(""); const [selected, setSelected] = useState<Branch | null>(null); const [members, setMembers] = useState<Array<User & { role: Role }>>([]); const [users, setUsers] = useState<Array<User & { active: number }>>([]); const [memberId, setMemberId] = useState(0); const [memberRole, setMemberRole] = useState<Role>("reader");
  useEffect(() => { if (current.role === "admin") void api.users().then((items) => { setUsers(items); if (items.length) setMemberId(items[0].id); }); }, [current.role]);
  async function open(item: Branch) { setSelected(item); try { setMembers(await api.branchMembers(item.id)); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Cannot manage this branch"); } }
  async function create(event: FormEvent) { event.preventDefault(); try { await api.addBranch(name); setName(""); setMessage("Branch created."); await reload(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not create branch"); } }
  async function assign(event: FormEvent) { event.preventDefault(); if (!selected) return; try { await api.setBranchMember(selected.id, memberId, memberRole); setMembers(await api.branchMembers(selected.id)); setMessage("Branch membership updated."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Membership update failed"); } }
  return <section><div className="section-heading"><div><p className="eyebrow">Branch ACLs</p><h2>Knowledge branches</h2></div><p>Membership controls reading, curation, merging, and synchronization.</p></div><div className="two-column"><div>{current.role === "admin" && <form className="panel" onSubmit={create}><h3>Create shared branch</h3><label>Branch name<input value={name} onChange={(event) => setName(event.target.value)} required /></label><button type="submit">Create branch</button></form>}<div className="panel source-list">{branches.map((branch) => <button type="button" className="list-action" key={branch.id} onClick={() => open(branch)}><div><strong>{branch.name}</strong><span>{branch.is_canonical ? "canonical · protected" : `protected · ${branch.member_role || current.role}`}</span></div></button>)}</div></div><div className="panel">{selected ? <><h3>{selected.name} members</h3><div className="source-list">{members.map((member) => <article key={member.id}><div><strong>{member.username}</strong><span>{member.role}</span></div></article>)}</div>{current.role === "admin" && <form onSubmit={assign}><label>User<select value={memberId} onChange={(event) => setMemberId(Number(event.target.value))}>{users.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}</select></label><label>Branch role<select value={memberRole} onChange={(event) => setMemberRole(event.target.value as Role)}><option value="reader">Reader</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option></select></label><button type="submit">Assign role</button></form>}</> : <p className="empty">Select a branch to manage its ACL.</p>}</div></div>{message && <p className="notice">{message}</p>}</section>;
}

function SettingsView({ current }: { current: User }) {
  const [gitUser, setGitUser] = useState(""); const [gitToken, setGitToken] = useState(""); const [lmToken, setLmToken] = useState(""); const [statusText, setStatusText] = useState(""); const [configured, setConfigured] = useState<{ git: boolean; lm: boolean }>({ git: false, lm: false });
  const loadStatus = useCallback(async () => { const value = await api.secretStatus() as { git?: Array<{ name: string }>; global?: Array<{ name: string }> }; setConfigured({ git: Boolean(value.git?.some((item) => item.name === "git_https_credentials")), lm: Boolean(value.global?.some((item) => item.name === "lm_studio_token")) }); }, []);
  useEffect(() => { void loadStatus(); }, [loadStatus]);
  async function saveGit(event: FormEvent) { event.preventDefault(); try { await api.setGitSecret(gitUser, gitToken); setGitToken(""); setStatusText("Encrypted Git credential saved in the OS-keyring-backed vault."); await loadStatus(); } catch (reason) { setStatusText(reason instanceof Error ? reason.message : "Could not save credential"); } }
  async function saveLm(event: FormEvent) { event.preventDefault(); try { await api.setLmSecret(lmToken); setLmToken(""); setStatusText("Encrypted LM Studio token saved."); await loadStatus(); } catch (reason) { setStatusText(reason instanceof Error ? reason.message : "Could not save token"); } }
  return <section><div className="section-heading"><div><p className="eyebrow">Encrypted configuration</p><h2>Credentials</h2></div><p>Values are encrypted with AES-GCM and are never displayed after saving.</p></div><div className="two-column"><form className="panel" onSubmit={saveGit}><h3>Private Git remote</h3><p className="notice">{configured.git ? "Credential configured" : "Not configured"}</p><label>Username<input value={gitUser} onChange={(event) => setGitUser(event.target.value)} required /></label><label>Access token<input type="password" value={gitToken} onChange={(event) => setGitToken(event.target.value)} required /></label><div className="button-row"><button type="submit">Save Git credential</button>{configured.git && <button type="button" className="danger" onClick={async () => { await api.deleteGitSecret(); await loadStatus(); }}>Delete</button>}</div></form>{current.role === "admin" && <form className="panel" onSubmit={saveLm}><h3>LM Studio bearer token</h3><p className="notice">{configured.lm ? "Token configured" : "Not configured"}</p><label>Bearer token<input type="password" value={lmToken} onChange={(event) => setLmToken(event.target.value)} required /></label><div className="button-row"><button type="submit">Save LM token</button>{configured.lm && <button type="button" className="danger" onClick={async () => { await api.deleteLmSecret(); await loadStatus(); }}>Delete</button>}</div></form>}</div>{statusText && <p className="notice">{statusText}</p>}</section>;
}

function GitView({ current }: { current: User }) {
  const [state, setState] = useState<{ branch: string; head: string; changes: string; remotes: string } | null>(null);
  const [message, setMessage] = useState("");
  const reload = useCallback(() => api.gitStatus().then(setState).catch((reason) => setMessage(reason instanceof Error ? reason.message : "Git status failed")), []);
  useEffect(() => { void reload(); }, [reload]);
  async function pull() { setMessage("Synchronizing…"); try { const result = await api.gitPull(); setState(result); setMessage(result.remotes ? "Pull with rebase completed." : "No remote is configured; local state is unchanged."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Pull failed"); } }
  async function push() { setMessage("Pushing…"); try { await api.gitPush(); setMessage("Push completed."); await reload(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Push failed"); } }
  return <section><div className="section-heading"><div><p className="eyebrow">Canonical history</p><h2>Git synchronization</h2></div><p>Publication commits only validated OKF knowledge files.</p></div><div className="panel git-state">{state ? <><div className="metrics"><Metric label="Branch" value={state.branch || "detached"} /><Metric label="Head" value={state.head ? state.head.slice(0, 8) : "unborn"} /></div><h3>Working tree</h3><pre>{state.changes || "Clean"}</pre><h3>Remotes</h3><pre>{state.remotes || "No remote configured"}</pre><div className="button-row"><button type="button" onClick={pull}>Pull with rebase</button>{current.role === "admin" && <button type="button" onClick={push}>Push current branch</button>}</div></> : <p className="empty">Loading repository state…</p>}{message && <p className="notice">{message}</p>}</div></section>;
}

function Users({ current }: { current: User }) {
  const [users, setUsers] = useState<Array<User & { active: number }>>([]);
  const [username, setUsername] = useState(""); const [password, setPassword] = useState(""); const [role, setRole] = useState<Role>("reader"); const [message, setMessage] = useState("");
  const reload = useCallback(() => api.users().then(setUsers), []);
  useEffect(() => { if (current.role === "admin") void reload(); }, [current.role, reload]);
  async function submit(event: FormEvent) { event.preventDefault(); try { await api.addUser(username, password, role); setUsername(""); setPassword(""); await reload(); setMessage("User created."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Could not create user"); } }
  if (current.role !== "admin") return <div className="panel empty">Only administrators manage accounts.</div>;
  return <section><div className="section-heading"><div><p className="eyebrow">Access control</p><h2>Team accounts</h2></div><p>Admins configure; reviewers curate; readers search and give feedback.</p></div><div className="two-column"><form className="panel" onSubmit={submit}><h3>Create account</h3><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label>Temporary password<input type="password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required /></label><label>Role<select value={role} onChange={(event) => setRole(event.target.value as Role)}><option value="reader">Reader</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option></select></label><button type="submit">Create account</button>{message && <p className="notice">{message}</p>}</form><div className="panel"><h3>Accounts</h3><div className="source-list">{users.map((user) => <article key={user.id}><div><strong>{user.username}</strong><span>{user.role}</span></div><span className={`badge ${user.active ? "published" : "failed"}`}>{user.active ? "active" : "disabled"}</span></article>)}</div></div></div></section>;
}

function App() {
  const [user, setUser] = useState<User | null>(null); const [loading, setLoading] = useState(true); const [view, setView] = useState<View>("dashboard"); const [sources, setSources] = useState<Source[]>([]); const [jobs, setJobs] = useState<Job[]>([]); const [concepts, setConcepts] = useState<Concept[]>([]); const [branches, setBranches] = useState<Branch[]>([]); const [branch, setBranch] = useState("");
  const sessionGeneration = useRef(0);
  const clearProtectedState = useCallback(() => {
    sessionGeneration.current += 1;
    setSources([]);
    setJobs([]);
    setConcepts([]);
    setBranches([]);
    setBranch("");
    setView("dashboard");
  }, []);
  const reload = useCallback(async () => {
    const generation = sessionGeneration.current;
    const branchData = await api.branches();
    const selectedBranch = branchData.some((item) => item.name === branch)
      ? branch
      : branchData.find((item) => Boolean(item.is_canonical))?.name || branchData[0]?.name || "";
    const [sourceData, jobData, conceptData] = await Promise.all([
      api.sources(),
      api.jobs(),
      selectedBranch ? api.concepts(undefined, selectedBranch) : Promise.resolve([] as Concept[]),
    ]);
    if (generation !== sessionGeneration.current) return;
    setSources(sourceData); setJobs(jobData); setConcepts(conceptData); setBranches(branchData);
    if (selectedBranch !== branch) setBranch(selectedBranch);
  }, [branch]);
  useEffect(() => {
    let active = true;
    api.me()
      .then((result) => {
        if (!active) return;
        clearProtectedState();
        setUser(result);
      })
      .catch(() => {
        if (!active) return;
        clearProtectedState();
        setUser(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [clearProtectedState]);
  useEffect(() => {
    if (!user) return;
    const generation = sessionGeneration.current;
    void reload().catch(() => {
      if (generation !== sessionGeneration.current) return;
      clearProtectedState();
      setUser(null);
    });
  }, [user, reload, clearProtectedState]);
  const visibleViews = useMemo(() => (["dashboard", "sources", "search", "entities", "branches", ...(user?.role !== "reader" ? ["review", "publications", "git"] : []), "settings", ...(user?.role === "admin" ? ["users"] : [])] as View[]), [user?.role]);
  function acceptLogin(nextUser: User) {
    clearProtectedState();
    setUser(nextUser);
  }
  async function logout() {
    try {
      await api.logout();
    } finally {
      clearProtectedState();
      setUser(null);
    }
  }
  if (loading) return <div className="loading">Loading local knowledge…</div>;
  if (!user) return <Login onLogin={acceptLogin} />;
  return <div className="app-shell"><aside><div className="brand"><span>CKB</span><div><strong>Company Knowledge</strong><small>Local · cited · Git-backed</small></div></div><label className="branch-picker">Branch<select value={branch} onChange={(event) => setBranch(event.target.value)}>{branches.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select></label><nav>{visibleViews.map((item) => <button type="button" key={item} className={view === item ? "active" : ""} onClick={() => setView(item)}>{item}</button>)}</nav><div className="account"><div><strong>{user.username}</strong><span>{user.role}</span></div><button type="button" className="link-button" onClick={logout}>Sign out</button></div></aside><main className="workspace">{view === "dashboard" && <Dashboard sources={sources.filter((item) => (item.branch || "main") === branch)} jobs={jobs.filter((item) => (item as Job & { branch?: string }).branch === branch || !(item as Job & { branch?: string }).branch)} concepts={concepts} />}{view === "sources" && <Sources sources={sources} jobs={jobs} reload={reload} branches={branches} branch={branch} />}{view === "search" && <SearchView branch={branch} />}{view === "entities" && <EntitiesView branch={branch} />}{view === "branches" && <BranchesView current={user} branches={branches} reload={reload} />}{view === "review" && <Review concepts={concepts} reload={reload} />}{view === "publications" && <PublicationsView />}{view === "git" && <GitView current={user} />}{view === "settings" && <SettingsView current={user} />}{view === "users" && <Users current={user} />}</main></div>;
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Portal root element was not found.");
}
createRoot(rootElement).render(<React.StrictMode><App /></React.StrictMode>);
