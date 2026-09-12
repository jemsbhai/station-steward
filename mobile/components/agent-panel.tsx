'use client';

import { useEffect, useState } from 'react';
import { Bot, History, Play, RotateCcw, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import AmbiguousPanel from '@/components/ambiguous-panel';
import HardwarePanel, { type HardwareState } from '@/components/hardware-panel';

const VIRTUAL_GOAL = 'Prepare the virtual station for handoff. Clear staging using the shortest legal move.';
const BENCH_GOAL = 'Check the Arduino inspection zone. It must have at least 20 cm clearance. If blocked or unmeasurable, assign a human to inspect or clear it.';

type Passport = { id: string; station: { id: string }; expired: boolean; evidence: { fresh: boolean } };
type Scene = { revision: number; arm_available: boolean; arm_at: string;
  slots: { id: string; label: string; x: number; y: number }[]; objects: { id: string; label: string; slot: string }[] };
type Mission = { id: string; station_id: string; goal: string; status: string; running: boolean; summary: string; model: string;
  objective: { summary: string } | null; verification_current: boolean;
  events: { index: number; at: string; title: string; detail: string; kind: string }[];
  evidence: { fresh: boolean; revision: number | null; observed_at: string | null };
  budget: { used: number; limit: number; model_calls: number; model_call_limit: number; tokens: number; usage_unknown: boolean };
  handoff: { summary: string; status: string; sent_to_ambiguous: boolean; verified?: boolean; url?: string; remote_status?: string; error?: string } | null;
  comparison: { object_id: string; revision: number; shortest: string | null; options: { destination: string; legal: boolean; travel_units: number }[] } | null };
type AgentState = { configured: boolean; model: string; scene: Scene; mission: Mission | null; hardware?: HardwareState | null };
type MissionReplay = { historical: boolean; records: unknown[]; report: { avoided: { steps?: number; model_calls?: number } } };

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/agent${path}`, { cache: 'no-store', ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof detail.detail === 'string' ? detail.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}

function Workcell({ scene }: { scene: Scene }) {
  const target = scene.slots.find(slot => slot.id === scene.arm_at) || { x: 280, y: 180 };
  const elbow = { x: 130, y: 210 };
  return <svg className="workcell-map" viewBox="0 0 600 360" role="img" aria-label={`Simulated workcell, revision ${scene.revision}. ${scene.objects.map(object => `${object.label} in ${object.slot.replace('_', ' ')}`).join('. ')}. Arm ${scene.arm_available ? 'available' : 'disconnected'}.`}>
    <rect x="1" y="1" width="598" height="358" rx="14" fill="#080f19" stroke="#2a384a" />
    <text x="24" y="30" fill="#a3b3c7" fontSize="12" letterSpacing="1.5">SIMULATED WORKCELL</text>
    {scene.slots.map(slot => <g key={slot.id}>
      <rect x={slot.x - 48} y={slot.y - 40} width="96" height="80" rx="8" fill={slot.id === 'staging' ? '#29251c' : '#152131'} stroke={slot.id === 'staging' ? '#aa8747' : '#3a5069'} strokeDasharray="5 4" />
      <text x={slot.x} y={slot.y + 59} textAnchor="middle" fill="#a3b3c7" fontSize="14">{slot.label}</text>
    </g>)}
    <g opacity={scene.arm_available ? 1 : 0.25}>
      <path d={`M 65 285 L ${elbow.x} ${elbow.y} L ${target.x} ${target.y}`} fill="none" stroke="#647f94" strokeWidth="16" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx="65" cy="285" r="22" fill="#253c4f" stroke="#8aabba" strokeWidth="3" />
      <circle cx={elbow.x} cy={elbow.y} r="13" fill="#253c4f" stroke="#8aabba" strokeWidth="3" />
      <circle cx={target.x} cy={target.y} r="12" fill="none" stroke="#77ecd0" strokeWidth="3" />
    </g>
    {scene.objects.map(object => {
      const slot = scene.slots.find(item => item.id === object.slot)!;
      return <g key={object.id}><circle cx={slot.x} cy={slot.y} r="23" fill={object.id === 'red_can' ? '#c96265' : '#5a8ece'} stroke="#e2ecf5" strokeWidth="2" /><text x={slot.x} y={slot.y + 5} textAnchor="middle" fill="#fff" fontSize="14" fontWeight="700">{object.id === 'red_can' ? 'R' : 'B'}</text></g>;
    })}
    <text x="24" y="334" fill={scene.arm_available ? '#77ecd0' : '#efce87'} fontSize="14">{scene.arm_available ? 'Arm available' : 'Arm disconnected'}</text>
    <text x="574" y="334" textAnchor="end" fill="#a3b3c7" fontSize="12">Revision {scene.revision}</text>
  </svg>;
}

export default function AgentPanel({ passport }: { passport: Passport | null }) {
  const [state, setState] = useState<AgentState | null>(null);
  const [goal, setGoal] = useState(VIRTUAL_GOAL);
  const [limit, setLimit] = useState(24);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [replay, setReplay] = useState<MissionReplay | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const next = await api<AgentState>('/state');
        if (!cancelled) { setState(next); setOffline(false); }
      } catch { if (!cancelled) setOffline(true); }
      finally { if (!cancelled) timer = setTimeout(refresh, 900); }
    }
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);
  useEffect(() => { setReplay(null); setStopping(false); }, [state?.mission?.id]);
  useEffect(() => { setGoal(passport?.station.id === 'bench' ? BENCH_GOAL : VIRTUAL_GOAL); }, [passport?.station.id]);

  async function refreshState() { setState(await api<AgentState>('/state')); }

  async function run() {
    if (!passport) return;
    setBusy(true); setError(''); setReplay(null); setStopping(false);
    try {
      await api('/missions', { goal, step_limit: limit, passport_id: passport.id });
      setState(await api<AgentState>('/state'));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function stop() {
    if (!state?.mission) return;
    setBusy(true); setError('');
    try { await api(`/missions/${state.mission.id}/stop`, {}); setStopping(true); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function changeScene(action: string) {
    setBusy(true); setError('');
    try { setState(await api<AgentState>('/scene', { action })); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  async function replayMission() {
    if (!state?.mission) return;
    setBusy(true); setError('');
    try { setReplay(await api<MissionReplay>(`/missions/${state.mission.id}/replay`)); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  const mission = state?.mission;
  const running = !!mission?.running;
  const bench = passport?.station.id === 'bench';
  const ready = !!passport && ['virtual', 'bench'].includes(passport.station.id) && !passport.expired && passport.evidence.fresh;
  const status = running ? stopping ? 'Stopping after current call' : 'Agent running' : mission?.status === 'completed' ? 'Mission completed' : mission?.status.replaceAll('_', ' ') || 'Ready for a goal';

  return <section className="agent-panel" id="agent-workcell" aria-label="Agent workcell">
    <div className="agent-heading"><div><span className="eyebrow">GOAL → TOOLS → VERIFIED RESULT</span><h2><Bot size={24} /> Agent workcell</h2></div><span className={`agent-state ${running ? 'is-running' : ''}`}>{status}</span></div>
    <p className="agent-intro">{bench ? 'The QR selected your real Arduino bench. The agent checks live readings and assigns work it cannot perform to a person.' : 'Give the agent a goal. It discovers the available tools, chooses moves, and checks the result in this simulator.'}</p>
    {offline && <p className="alert" role="alert">Agent controls are reconnecting to the laptop.</p>}
    {error && <p className="alert" role="alert">{error}</p>}
    <div className="agent-layout"><div>
      <label className="agent-label" htmlFor="mission-goal">What should the station accomplish?</label>
      <Textarea id="mission-goal" value={goal} maxLength={1000} onChange={event => setGoal(event.target.value)} disabled={running} className="mission-goal" />
      <div className="goal-examples">{bench ? <Button variant="ghost" disabled={running} onClick={() => setGoal(BENCH_GOAL)}>Check 20 cm clearance</Button> : <><Button variant="ghost" disabled={running} onClick={() => setGoal(VIRTUAL_GOAL)}>Clear staging</Button><Button variant="ghost" disabled={running} onClick={() => setGoal('Put the blue can in rack 1 and the red can in rack 2. Leave staging empty.')}>Sort the cans</Button></>}</div>
      <div className="mission-start"><label htmlFor="mission-budget">Call budget <select id="mission-budget" value={limit} disabled={running} onChange={event => setLimit(Number(event.target.value))}>{[4, 12, 24, 40].map(value => <option key={value} value={value}>{value} steps</option>)}</select></label>
        {running ? <Button variant="outline" disabled={busy || stopping} onClick={stop}><Square size={16} /> {stopping ? 'Stopping…' : 'Stop agent'}</Button> : <Button disabled={busy || offline || !state?.configured || !ready || !goal.trim()} onClick={run}><Play size={17} /> Run agent</Button>}
      </div>
      {!ready && <p className="agent-prerequisite">Choose <strong>Arduino bench</strong> or <strong>Virtual workcell</strong> on your phone and scan its QR below before starting.</p>}
      {state && !state.configured && <p className="agent-prerequisite">An OpenAI API key needs to be configured on the laptop before the agent can run.</p>}
      {state && <p className="small-detail">OpenAI · {state.model} · {bench ? 'physical readings and human handoffs' : 'simulated movement and human handoffs'}</p>}
      {mission?.objective && <div className="agent-objective"><span className="eyebrow">AGENT’S INTERPRETATION</span><p>{mission.objective.summary}</p></div>}
      {mission && <>
        <div className="mission-meters"><div><strong>{mission.budget.used}/{mission.budget.limit}</strong><span>Pollard steps</span></div><div><strong>{mission.budget.model_calls}/{mission.budget.model_call_limit}</strong><span>Model calls</span></div><div><strong>{mission.budget.tokens.toLocaleString()}</strong><span>Reported tokens{mission.budget.usage_unknown ? ' · incomplete' : ''}</span></div></div>
        <p className="small-detail">Chronofy: {mission.evidence.fresh ? mission.station_id === 'bench' ? 'fresh physical observation' : `fresh observation of revision ${mission.evidence.revision}` : mission.evidence.observed_at ? 'observation needs refreshing' : 'awaiting observation'}. Model and tool calls share this mission’s budget.</p>
        {!running && <div className="mission-result" role="status"><strong>{mission.status === 'completed' ? mission.station_id === 'bench' ? 'Physical clearance verified at observation time.' : 'Simulator verified the objective.' : 'Mission result'}</strong><p>{mission.summary}</p>{mission.status === 'completed' && !mission.verification_current && <p>Conditions changed or this observation aged. The receipt remains historical.</p>}</div>}
        {mission.handoff && <div className="agent-handoff"><strong>Human help needed</strong><p>{mission.handoff.summary}</p><small>{mission.handoff.verified ? `Task read back from Ambiguous · ${mission.handoff.remote_status?.replaceAll('_', ' ')}` : mission.handoff.status === 'pending_local' ? 'Saved locally. Connect Ambiguous below for future handoffs.' : mission.handoff.error || 'Task delivery needs checking.'}</small>{mission.handoff.url && <a className="handoff-link" href={mission.handoff.url} target="_blank" rel="noreferrer">Open Ambiguous task</a>}</div>}
        <Button className="agent-replay" variant="outline" disabled={busy || running || !mission.budget.used} onClick={replayMission}><History size={17} /> Replay mission</Button>
      </>}
      {replay && <p className="notice" role="status">Historical replay: {replay.records.length} recorded calls, including {replay.report.avoided.model_calls || 0} model calls. No new model request, movement, or observation.</p>}
    </div><div>
      <HardwarePanel state={state?.hardware} onRefresh={refreshState} />
      {!bench && <>{state && <Workcell scene={state.scene} />}
      <div className="scene-controls"><Button variant="outline" disabled={busy || running || offline} onClick={() => changeScene('reset')}><RotateCcw size={16} /> Reset scene</Button><Button variant="outline" disabled={busy || !state || offline} onClick={() => changeScene('toggle_arm')}>{state?.scene.arm_available ? 'Disconnect arm' : 'Connect arm'}</Button></div>
      <details className="adaptation-controls"><summary>Test adaptation while the agent runs</summary><p>Change the evidence or available tools. The next action must use the new state.</p><div><Button variant="outline" disabled={busy || !state || offline} onClick={() => changeScene('swap')}>Swap can positions</Button><Button variant="outline" disabled={busy || !mission?.evidence.observed_at || offline} onClick={() => changeScene('age_observation')}>Age observation by 31s</Button></div></details>
      {mission?.comparison && <div className="move-comparison"><span className="eyebrow">MOVE COMPARISON · REVISION {mission.comparison.revision}</span><table><thead><tr><th>Destination</th><th>Travel units</th><th>Available</th></tr></thead><tbody>{mission.comparison.options.map(option => <tr key={option.destination}><td>{option.destination.replace('_', ' ')}{mission.comparison?.shortest === option.destination ? ' · shortest' : ''}</td><td>{option.travel_units}</td><td>{option.legal ? 'Yes' : 'No'}</td></tr>)}</tbody></table><p className="small-detail">Compared without moving; recorded by Pollard. Distance in the simulator, not measured energy savings.</p></div>}</>}
    </div></div>
    {mission && <div className="agent-activity"><span className="eyebrow">LIVE ACTIVITY</span><ol aria-label="Agent actions">{mission.events.map(event => <li key={event.index} className={event.kind}><span className="activity-number">{event.index}</span><div><strong>{event.title}</strong>{event.detail && <p>{event.detail}</p>}</div><time>{new Date(event.at).toLocaleTimeString()}</time></li>)}</ol></div>}
    <AmbiguousPanel />
  </section>;
}
