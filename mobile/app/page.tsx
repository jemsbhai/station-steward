'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, Check, ChevronRight, Expand, History, Moon, Radio, ScanLine, Smartphone, Square, Wifi } from 'lucide-react';
import { Button } from '@/components/ui/button';
import AgentPanel from '@/components/agent-panel';

type Station = { id: string; name: string; kind: string; capabilities: string[]; connection: string };
type Scan = { verified: boolean; complete: boolean; reason: string; payload: string; payloads: string[]; received_at: string };
type Passport = { id: string; station: Station; expired: boolean; active?: boolean; expires_at: string; qr_payload: string;
  evidence: { fresh: boolean; age_seconds: number | null; observed_at: string | null };
  budget: { used: number; limit: number; remaining: number; decode_seconds: number }; last_scan: Scan | null };
type State = { stations: Station[]; active: Passport | null; phone_url: string; camera_url: string };
type Replay = { historical: boolean; records: (Scan & { received_at_ms: number })[]; report: { avoided: { steps?: number } } };
type ToolContext = { registerTool: (tool: { name: string; title: string; description: string; inputSchema: object; annotations: object; execute: (input: unknown) => Promise<unknown> }, options: { signal: AbortSignal }) => void | Promise<void> };
type ExposureRange = { min: number; max: number; step?: number };
type ExposureState = { min: number; max: number; step: number; value: number; initial: number };
type ExposureSettings = MediaTrackSettings & { exposureCompensation?: number };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}

export default function Home() {
  const [view, setView] = useState('camera');
  const [state, setState] = useState<State | null>(null);
  const [passport, setPassport] = useState<Passport | null>(null);
  const [station, setStation] = useState('bench');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [online, setOnline] = useState(true);
  const [busy, setBusy] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [exposure, setExposure] = useState<ExposureState | null>(null);
  const [darkPhase, setDarkPhase] = useState<'countdown' | 'scanning' | 'result' | null>(null);
  const [countdown, setCountdown] = useState(3);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const phoneSession = useRef<string | null>(null);
  const alive = useRef(true);
  const display = useRef<HTMLDivElement>(null);
  const darkDialog = useRef<HTMLDialogElement>(null);
  const darkTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const darkAttempt = useRef<{ token: number; passportId: string } | null>(null);
  const nextDarkToken = useRef(0);
  const darkFullscreen = useRef(false);
  const scanInFlight = useRef(false);
  const latest = useRef({ passport, online });
  latest.current = { passport, online };

  const exitDarkScan = useCallback(() => {
    if (darkTimer.current) clearTimeout(darkTimer.current);
    darkTimer.current = null;
    darkAttempt.current = null;
    darkDialog.current?.close();
    setDarkPhase(null);
    if (darkFullscreen.current && document.fullscreenElement === document.documentElement) {
      void document.exitFullscreen().catch(() => {});
    }
    darkFullscreen.current = false;
  }, []);

  useEffect(() => {
    alive.current = true;
    setView(new URLSearchParams(window.location.search).get('view') === 'phone' ? 'phone' : 'camera');
    phoneSession.current = sessionStorage.getItem('station-passport');
    return () => {
      alive.current = false;
      if (darkTimer.current) clearTimeout(darkTimer.current);
      darkAttempt.current = null;
      stream.current?.getTracks().forEach(track => track.stop());
      if (darkFullscreen.current && document.fullscreenElement === document.documentElement) void document.exitFullscreen().catch(() => {});
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const current = await request<State>('/api/state');
        if (cancelled) return;
        setState(current);
        if (view === 'phone' && phoneSession.current) {
          try {
            const mine = await request<Passport>(`/api/passports/${phoneSession.current}`);
            if (!cancelled) setPassport(mine);
          } catch {
            phoneSession.current = null;
            sessionStorage.removeItem('station-passport');
            if (!cancelled) setPassport(null);
          }
        } else if (view === 'camera') setPassport(current.active);
        if (!cancelled) setOnline(true);
      } catch { if (!cancelled) setOnline(false); }
      finally { if (!cancelled) timer = setTimeout(refresh, 1200); }
    }
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [view]);

  useEffect(() => { setReplay(null); setNotice(''); }, [passport?.id]);

  useEffect(() => {
    if (darkAttempt.current && (!cameraOn || !online || !passport || passport.id !== darkAttempt.current.passportId || passport.expired || passport.active === false)) {
      exitDarkScan();
    }
  }, [cameraOn, online, passport?.id, passport?.expired, passport?.active, exitDarkScan]);

  useEffect(() => {
    const changed = () => { if (darkFullscreen.current && !document.fullscreenElement) exitDarkScan(); };
    const escaped = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && darkAttempt.current) { event.preventDefault(); exitDarkScan(); }
    };
    document.addEventListener('fullscreenchange', changed);
    document.addEventListener('keydown', escaped);
    return () => {
      document.removeEventListener('fullscreenchange', changed);
      document.removeEventListener('keydown', escaped);
    };
  }, [exitDarkScan]);

  useEffect(() => {
    const context = (document as Document & { modelContext?: ToolContext }).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    try {
      void Promise.resolve(context.registerTool({
        name: 'get_station_passport_status', title: 'Read station passport status',
        description: 'Read the current station, last camera scan, evidence freshness and remaining scan budget. Does not start a camera or move hardware.',
        inputSchema: { type: 'object', properties: {}, additionalProperties: false },
        annotations: { readOnlyHint: true, untrustedContentHint: false },
        async execute(input) {
          if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length) throw new Error('Use an empty object.');
          return request<State>('/api/state');
        },
      }, { signal: lifecycle.signal })).catch(() => {});
    } catch { /* Browsers without this optional capability keep the normal UI. */ }
    return () => lifecycle.abort();
  }, []);

  async function createPassport() {
    setBusy(true); setError(''); setReplay(null);
    try {
      const next = await request<Passport>('/api/passports', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ station_id: station }) });
      phoneSession.current = next.id;
      sessionStorage.setItem('station-passport', next.id);
      setPassport(next);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  const stopCamera = useCallback(() => {
    exitDarkScan();
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setCameraOn(false);
    setExposure(null);
  }, [exitDarkScan]);

  async function startCamera() {
    setError(''); setBusy(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Open the laptop page at http://localhost:8765/?view=camera to use its camera.');
      const media = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false });
      if (!alive.current) { media.getTracks().forEach(track => track.stop()); return; }
      stream.current = media;
      media.getVideoTracks().forEach(track => track.addEventListener('ended', stopCamera));
      if (video.current) { video.current.srcObject = media; await video.current.play(); }
      setCameraOn(true);
      try {
        const track = media.getVideoTracks()[0];
        const capabilities = track.getCapabilities?.() as (MediaTrackCapabilities & { exposureCompensation?: ExposureRange }) | undefined;
        const range = capabilities?.exposureCompensation;
        const value = (track.getSettings() as ExposureSettings).exposureCompensation;
        if (range && Number.isFinite(range.min) && Number.isFinite(range.max) && range.min < range.max && typeof value === 'number' && Number.isFinite(value)) {
          setExposure({ min: range.min, max: range.max, step: range.step && range.step > 0 ? range.step : 0.1, value, initial: value });
        }
      } catch { setExposure(null); }
    } catch (err) {
      stopCamera();
      setError((err as Error).name === 'NotAllowedError' ? 'Camera access was declined. Allow camera access in your browser, then try again.' : (err as Error).message);
    } finally { setBusy(false); }
  }

  async function adjustExposure(reset = false) {
    const track = stream.current?.getVideoTracks()[0];
    if (!track || !exposure) return;
    const delta = Math.max(exposure.step, (exposure.max - exposure.min) / 6);
    const target = reset ? exposure.initial : exposure.value - delta;
    const value = Math.max(exposure.min, Math.min(exposure.max, exposure.min + Math.round((target - exposure.min) / exposure.step) * exposure.step));
    setBusy(true); setError('');
    try {
      const constraint = { exposureCompensation: value } as MediaTrackConstraintSet & { exposureCompensation: number };
      await track.applyConstraints({ advanced: [constraint] });
      const actual = (track.getSettings() as ExposureSettings).exposureCompensation;
      if (typeof actual !== 'number' || !Number.isFinite(actual) || Math.abs(actual - value) > exposure.step / 2) throw new Error('The camera did not apply that exposure setting. Lower the phone brightness instead.');
      if (stream.current?.getVideoTracks()[0] === track) setExposure(previous => previous ? { ...previous, value: actual } : null);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  async function scan(darkToken?: number) {
    const current = latest.current.passport;
    const isCurrentAttempt = () => darkToken === undefined || darkAttempt.current?.token === darkToken;
    if (scanInFlight.current || !isCurrentAttempt()) return;
    if (!current || current.expired || current.active === false || Date.parse(current.expires_at) <= Date.now() || !latest.current.online || current.budget.remaining <= 0) {
      setError('Show an active passport with attempts remaining, then try again.');
      if (darkToken !== undefined) setDarkPhase('result');
      return;
    }
    if (darkToken !== undefined && darkAttempt.current?.passportId !== current.id) return;
    scanInFlight.current = true;
    if (darkToken !== undefined) setDarkPhase('scanning');
    setBusy(true); setError(''); setNotice(''); setReplay(null);
    try {
      const frame = video.current;
      const track = stream.current?.getVideoTracks()[0];
      if (!frame || !track || track.readyState !== 'live' || frame.paused || frame.readyState < 2 || !frame.videoWidth || !frame.videoHeight) throw new Error('Wait for the live camera image before scanning.');
      const scale = Math.min(1, 1280 / frame.videoWidth, 960 / frame.videoHeight);
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(frame.videoWidth * scale); canvas.height = Math.round(frame.videoHeight * scale);
      const context = canvas.getContext('2d');
      if (!context) throw new Error('The camera frame could not be captured.');
      context.drawImage(frame, 0, 0, canvas.width, canvas.height);
      const image = await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Camera capture failed.')), 'image/png'));
      if (!alive.current || !isCurrentAttempt()) return;
      const active = latest.current.passport;
      if (!latest.current.online || !active || active.id !== current.id || active.expired || active.active === false || active.budget.remaining <= 0 || Date.parse(active.expires_at) <= Date.now()) throw new Error('The passport changed or expired. Show the current code and try again.');
      const result = await request<{ scan: Scan; passport: Passport }>(`/api/passports/${current.id}/scan`, { method: 'POST', headers: { 'Content-Type': 'image/png' }, body: image });
      if (!alive.current || latest.current.passport?.id !== current.id) return;
      setPassport(result.passport);
      setNotice(result.scan.verified ? 'QR code matches this station passport.' : result.scan.reason === 'different_passport' ? 'That is a different QR code. Show the current station passport on your phone.' : result.scan.reason === 'multiple_codes' ? 'More than one QR code was read. Keep only the current passport in view.' : result.scan.reason === 'expired' ? 'The passport expired during the scan. Show a new one on your phone.' : result.scan.reason === 'decoder_error' ? 'The QR reader could not process this frame. Try again.' : 'The QR code could not be read. Enlarge it, keep its white border visible, and hold still. Use Dark-screen scan or tilt the phone slightly to move reflections away.');
    } catch (err) { if (alive.current && latest.current.passport?.id === current.id) setError((err as Error).message); }
    finally {
      scanInFlight.current = false;
      if (alive.current) {
        setBusy(false);
        if (darkToken !== undefined && isCurrentAttempt()) setDarkPhase('result');
      }
    }
  }

  function startDarkScan() {
    const current = latest.current.passport;
    if (busy || scanInFlight.current || darkTimer.current || !cameraOn || !latest.current.online || !current || current.expired || current.active === false || current.budget.remaining <= 0) return;
    const token = ++nextDarkToken.current;
    darkAttempt.current = { token, passportId: current.id };
    setError(''); setNotice(''); setCountdown(3); setDarkPhase('countdown');
    darkDialog.current?.showModal();
    if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
      void document.documentElement.requestFullscreen().then(() => {
        if (alive.current && darkAttempt.current?.token === token) darkFullscreen.current = true;
        else if (document.fullscreenElement === document.documentElement) void document.exitFullscreen().catch(() => {});
      }).catch(() => { /* The black dialog still covers the app when fullscreen is unavailable. */ });
    }
    const tick = (remaining: number) => {
      darkTimer.current = setTimeout(() => {
        darkTimer.current = null;
        if (!alive.current || darkAttempt.current?.token !== token) return;
        if (remaining > 1) { setCountdown(remaining - 1); tick(remaining - 1); }
        else void scan(token);
      }, 1000);
    };
    tick(3);
  }

  async function replayReceipt() {
    if (!passport) return;
    setBusy(true); setError('');
    try { setReplay(await request<Replay>(`/api/passports/${passport.id}/replay`)); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  async function enlarge() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await display.current?.requestFullscreen();
    } catch { setFullscreen(value => !value); }
  }

  const usable = !!passport && !passport.expired && passport.active !== false;
  const evidenceStatus = !passport ? 'Waiting for a passport' : !usable ? 'Show a new passport' : passport.evidence.fresh ? 'Passport verified' : passport.evidence.observed_at ? 'Observation needs a refresh' : 'Ready to scan';

  return <main className={`steward ${view === 'phone' ? 'handheld' : ''}`}>
    <header className="app-header">
      <a className="brand" href="/?view=camera"><ScanLine size={25} /><span>STATION<br /><b>STEWARD</b></span></a>
      <nav aria-label="Device view"><a href="/?view=phone" aria-current={view === 'phone' ? 'page' : undefined}><Smartphone size={17} /> Phone</a><a href="/?view=camera" aria-current={view === 'camera' ? 'page' : undefined}><Camera size={17} /> Laptop</a></nav>
    </header>
    {!online && <p className="alert" role="alert">Laptop unreachable. Keep both devices on the same Wi-Fi or hotspot and keep the local app running.</p>}
    {error && <p className="alert" role="alert">{error}</p>}
    {view === 'phone' ? <section className="phone-content">
      <div className="section-title"><span className="eyebrow">PHONE PASSPORT</span><h1>Choose your station.</h1><p>Show its QR code to the laptop camera.</p></div>
      <div className="station-options" role="group" aria-label="Station">{(state?.stations || []).map(item => <Button key={item.id} variant="outline" className={`station-option ${station === item.id ? 'selected' : ''}`} aria-pressed={station === item.id} onClick={() => setStation(item.id)}><span><strong>{item.name}</strong><small>{item.kind === 'physical' ? 'Physical equipment' : 'Simulated equipment'}</small></span><span>{station === item.id ? <Check /> : <ChevronRight />}</span></Button>)}</div>
      <Button className="primary-action" disabled={busy || !online || !state} onClick={createPassport}><ScanLine /> {passport ? 'Show a new passport' : 'Show station passport'}</Button>
      {passport && <div ref={display} className={`passport-display ${fullscreen ? 'expanded' : ''}`}>
        <div className="passport-heading"><span>{passport.station.name}</span><Button variant="ghost" aria-label="Enlarge passport" onClick={enlarge}><Expand size={18} /> Full screen</Button></div>
        {usable ? <img className="qr-passport" src={`/api/passports/${passport.id}/code.png`} alt={`QR passport for ${passport.station.name}`} width={348} height={348} /> : <div className="expired">This passport is no longer active.<br />Show a new one to continue.</div>}
        <div className={`verification ${passport.evidence.fresh && usable ? 'verified' : ''}`} aria-live="polite"><Radio size={16} /> {evidenceStatus}</div>
        <p className="passport-help">Keep the full QR and white border visible. If it looks washed out in the camera, lower phone brightness.</p>
      </div>}
      <p className="scope-note">This passport identifies a station profile. Equipment still needs a live connection.</p>
    </section> : <>
      <div className="desktop-title"><div><span className="eyebrow">STATION STEWARD</span><h1>Give the station a goal.</h1></div><span className="connection"><Wifi size={16} /> Local connection</span></div>
      <AgentPanel passport={passport} />
      <div className="scanner-heading"><span className="eyebrow">CONNECT A STATION</span><h2>Scan the phone passport.</h2></div>
      <div className="workspace"><section className="camera-panel" aria-label="Laptop camera scanner">
        <div className="camera-stage"><video ref={video} muted playsInline aria-label="Live laptop camera" className={cameraOn ? '' : 'camera-hidden'} />{!cameraOn && <div className="camera-empty"><Camera size={42} strokeWidth={1.3} /><h2>Your laptop camera</h2><p>Start the camera, then hold your phone’s passport in view.</p></div>}{cameraOn && <><div className="viewfinder" aria-hidden="true" /><span className="live-label"><span /> CAMERA ON</span></>}</div>
        <div className="camera-controls"><Button variant={cameraOn ? 'outline' : 'default'} className="control-action" disabled={busy} onClick={cameraOn ? stopCamera : startCamera}>{cameraOn ? <Square /> : <Camera />}{cameraOn ? 'Stop camera' : 'Start camera'}</Button><Button className="control-action" disabled={busy || !cameraOn || !usable || !online || passport?.budget.remaining === 0} onClick={() => void scan()}><ScanLine /> {busy && cameraOn ? 'Reading…' : 'Scan passport'}</Button></div>
        {cameraOn && <Button variant="outline" className="dark-scan-action" disabled={busy || !usable || !online || passport?.budget.remaining === 0} onClick={startDarkScan}><Moon size={18} /> Dark-screen scan · 3s delay</Button>}
        {cameraOn && exposure && <div className="exposure-controls"><span>Camera exposure <strong>{exposure.value.toFixed(1)}</strong></span><Button variant="outline" disabled={busy || exposure.value <= exposure.min} onClick={() => adjustExposure()}>Darker</Button><Button variant="ghost" disabled={busy || exposure.value === exposure.initial} onClick={() => adjustExposure(true)}>Reset</Button></div>}
        <p className="camera-tip">Seeing repeated screen reflections? Align the phone, then use Dark-screen scan to hide the laptop preview. Tilt the phone slightly to move room-light reflections off the code.</p>{notice && <p className="notice" role="status">{notice}</p>}
      </section><aside className="inspection">
        {!passport ? <section className="join-panel"><span className="eyebrow">01 / CONNECT YOUR PHONE</span><h2>Open the phone display.</h2><img className="join-code" src={`/api/join.png?network=${encodeURIComponent(state?.phone_url ?? '')}`} width={180} height={180} alt="Ordinary QR code opening the phone display" /><p>Scan this with your Android’s normal camera. Both devices need the same Wi-Fi or hotspot.</p><a className="local-address" href={state?.phone_url}>{state?.phone_url || 'Finding your local address…'}</a></section> : <>
          <section className="inspection-card"><span className="eyebrow">CURRENT PASSPORT</span><h2>{passport.station.name}</h2><span className="kind-label">{passport.station.kind === 'physical' ? 'PHYSICAL STATION' : 'SIMULATED STATION'}</span><div className={`verification ${passport.evidence.fresh && usable ? 'verified' : ''}`} aria-live="polite"><Radio size={17} /> {evidenceStatus}</div><p className="small-detail">{passport.evidence.age_seconds !== null ? `Last matched observation: ${Math.floor(passport.evidence.age_seconds)}s ago. Refresh after 30s.` : 'The camera must read the current station’s QR code.'}</p><p className="device-status">{passport.station.connection}</p></section>
          <section className="qr-details"><span className="eyebrow">LAST QR READ</span><code>{passport.last_scan?.payload || (passport.last_scan?.reason === 'multiple_codes' ? 'Multiple QR codes in view' : 'Awaiting camera decode')}</code><p className="small-detail">The passport selects this station’s registered equipment profile.</p></section>
          <section className="budget"><div><span className="eyebrow">POLLARD SCAN BUDGET</span><strong>{passport.budget.used} <span>/ {passport.budget.limit}</span></strong></div><p>{passport.budget.remaining} attempts left · {passport.budget.decode_seconds.toFixed(2)}s decoding</p><Button variant="outline" className="receipt-action" disabled={busy || !passport.budget.used} onClick={replayReceipt}><History /> Replay scan receipt</Button></section>
          <details className="connection-details"><summary>Open the phone display</summary><img className="join-code" src={`/api/join.png?network=${encodeURIComponent(state?.phone_url ?? '')}`} width={150} height={150} alt="Open the phone display" /><a className="local-address" href={state?.phone_url}>{state?.phone_url}</a></details>
        </>}
      </aside></div>
      {replay && <section className="replay"><div><span className="eyebrow">HISTORICAL REPLAY</span><h2>{replay.records.length} recorded scan{replay.records.length === 1 ? '' : 's'}</h2><p>No camera capture or decoder call was repeated. Live observation time is unchanged.</p></div><ol>{replay.records.map((record, i) => <li key={i}><span>{new Date(record.received_at_ms).toLocaleTimeString()}</span><strong>{record.verified ? 'QR passport matched' : record.reason === 'multiple_codes' ? 'Multiple QR codes' : record.reason === 'expired' ? 'Passport expired' : record.complete ? 'Different QR code' : 'Unreadable QR'}</strong></li>)}</ol></section>}
      <footer className="app-footer"><span>OpenAI · QR · Pollard · Chronofy · MCP-Edge · Ambiguous</span><span>Live Arduino readings and a separate virtual workcell</span></footer>
    </>}
    <dialog ref={darkDialog} className="dark-scan-dialog" aria-labelledby="dark-scan-title" onCancel={event => { event.preventDefault(); exitDarkScan(); }}>
      <div className="dark-scan-content">
        <h2 id="dark-scan-title">{darkPhase === 'countdown' ? `Hold still · ${countdown}` : darkPhase === 'scanning' ? 'Reading…' : 'Scan finished'}</h2>
        <p role="status">{darkPhase === 'countdown' ? 'Camera stays on. One scan after the countdown.' : darkPhase === 'scanning' ? 'Processing one camera frame.' : error || notice || 'No scan result. Try again.'}</p>
        <div className="dark-scan-controls">
          {darkPhase === 'result' && <Button variant="outline" disabled={busy || !cameraOn || !usable || !online || passport?.budget.remaining === 0} onClick={startDarkScan}>Try again · 3s delay</Button>}
          <Button variant="ghost" onClick={exitDarkScan}>{darkPhase === 'countdown' ? 'Cancel' : 'Return to preview'}</Button>
        </div>
      </div>
    </dialog>
  </main>;
}
