'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, Link2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

type Choice = { id: string; name: string };
type Handoff = { mission_id: string; summary: string; status: string; verified: boolean; url?: string; task_title?: string; remote_status?: string; error?: string; checked_at?: string };
type Connection = { connected: boolean; enabled: boolean; identity?: { display_name: string; workspace_id: string; type: string };
  people?: Choice[]; projects?: Choice[]; assignee?: Choice; project?: Choice | null; more_people?: boolean; more_projects?: boolean; recent: Handoff[]; problem: string };

async function api<T>(path: string, data?: unknown): Promise<T> {
  const response = await fetch(`/api/ambiguous${path}`, { cache: 'no-store', ...(data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }) });
  if (!response.ok) {
    const result = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof result.detail === 'string' ? result.detail : 'The connection request failed.');
  }
  return response.json();
}

export default function AmbiguousPanel() {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [key, setKey] = useState('');
  const [assignee, setAssignee] = useState('');
  const [project, setProject] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const state = await api<Connection>('/connection');
        if (!cancelled) { setConnection(state); setOffline(false); }
      } catch { if (!cancelled) setOffline(true); }
      finally { if (!cancelled) timer = setTimeout(refresh, 4000); }
    }
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);
  useEffect(() => {
    setAssignee(connection?.assignee?.id || '');
    setProject(connection?.project?.id || '');
  }, [connection?.assignee?.id, connection?.project?.id]);

  async function connect() {
    setBusy(true); setError('');
    try { setConnection(await api<Connection>('/connect', { key })); setEditing(true); }
    catch (err) { setError((err as Error).message); }
    finally { setKey(''); setBusy(false); }
  }
  async function enable() {
    setBusy(true); setError('');
    try { setConnection(await api<Connection>('/destination', { assignee_id: assignee, project_id: project || null })); setEditing(false); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function disconnect() {
    setBusy(true); setError('');
    try { setConnection(await api<Connection>('/disconnect', {})); setEditing(false); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function checkTask(missionId: string) {
    setBusy(true); setError('');
    try { await api(`/handoffs/${missionId}/refresh`, {}); setConnection(await api<Connection>('/connection')); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  return <section className="ambiguous-panel" aria-label="Ambiguous human handoffs">
    <div className="ambiguous-heading"><h3><Link2 size={19} /> Human handoffs · Ambiguous</h3><span>{connection?.enabled ? 'Automatic task handoffs enabled' : connection?.connected ? 'Choose a destination' : 'Not connected'}</span></div>
    {offline && <p className="small-detail">Connection settings are available on the laptop’s localhost page.</p>}
    {(error || connection?.problem) && <p className="alert" role="alert">{error || connection?.problem}</p>}
    {!connection?.connected ? <>
      <p>Connect a workspace to turn the agent’s requests for help into assigned, persistent tasks.</p>
      <ol className="ambiguous-steps"><li>Sign in to <a href="https://app.ambiguous.ai/" target="_blank" rel="noreferrer">Ambiguous</a> and create or select your demo workspace.</li><li>Follow its <strong>Connect</strong> instructions to obtain an API key with task read/write access. Invite your teammate if you want to assign them work.</li><li>Paste the key here, then choose the person and project.</li></ol>
      <div className="ambiguous-key"><label htmlFor="ambiguous-key">Ambiguous API key</label><Input id="ambiguous-key" type="password" autoComplete="new-password" placeholder="ak_…" value={key} onChange={event => setKey(event.target.value)} disabled={busy} /><Button disabled={busy || offline || !key.trim()} onClick={connect}>{busy ? 'Checking connection…' : 'Connect Ambiguous'}</Button></div>
      <p className="small-detail">The key is encrypted for your Windows account and stays on this laptop. It is never given to the model.</p>
    </> : <>
      <p className="ambiguous-identity">Connected as <strong>{connection.identity?.display_name}</strong> · {connection.identity?.type}<small>Workspace: {connection.identity?.workspace_id}</small></p>
      {(!connection.enabled || editing) ? <div className="ambiguous-destination">
        <label>Assign human work to<select value={assignee} onChange={event => setAssignee(event.target.value)} disabled={busy}><option value="">Choose a person</option>{connection.people?.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label>
        <label>Project<select value={project} onChange={event => setProject(event.target.value)} disabled={busy}><option value="">No project · creator and assignee only</option>{connection.projects?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <p>New agent handoffs will create a task for this person in the selected destination.</p>
        {!connection.people?.length && <p className="agent-prerequisite">No human members were found. Add yourself or your teammate to this workspace, then reconnect.</p>}
        {(connection.more_people || connection.more_projects) && <p className="small-detail">Showing the first 100 people/projects. Use a demo workspace where the intended destination appears in these lists.</p>}
        <Button disabled={busy || !assignee} onClick={enable}>Enable task handoffs</Button>
      </div> : <p className="ambiguous-destination-summary">Tasks go to <strong>{connection.assignee?.name}</strong>{connection.project ? <> in <strong>{connection.project.name}</strong></> : ' without a project'}.</p>}
      <div className="ambiguous-buttons"><Button variant="ghost" disabled={busy} onClick={() => setEditing(value => !value)}>Change destination</Button><Button variant="ghost" disabled={busy} onClick={disconnect}>Disconnect</Button></div>
      {connection.enabled && <p className="small-detail">To test: reset the virtual scene, disconnect its arm, refresh the QR scan, and run “Clear staging.” Open the task link after the agent asks for help.</p>}
    </>}
    {!!connection?.recent.length && <div className="ambiguous-tasks"><h4>Recent handoff tasks</h4>{connection.recent.map(task => <div key={task.mission_id} className="ambiguous-task"><strong>{task.task_title || task.summary}</strong><p>{task.verified ? `Read back from Ambiguous · ${task.remote_status?.replaceAll('_', ' ')}` : task.status.replaceAll('_', ' ')}</p>{task.error && <p className="agent-prerequisite">{task.error}</p>}<div>{task.url && <a href={task.url} target="_blank" rel="noreferrer">Open task <ExternalLink size={14} /></a>}<Button variant="outline" disabled={busy} onClick={() => checkTask(task.mission_id)}>Check task status</Button></div></div>)}<p className="small-detail">Task completion is a human report. Run a fresh workcell verification afterward. Replay never creates or updates these tasks.</p></div>}
  </section>;
}
