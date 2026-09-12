'use client';

import { useState } from 'react';
import { Cable, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export type HardwareState = {
  connected: boolean; fresh: boolean; received_at: string | null; age_seconds: number | null;
  sequence: number; session_id: string | null; port: string; error: string | null; dht_warning?: string | null;
  telemetry: { distance_cm: number | null; distance_valid: boolean; temperature_c: number | null;
    humidity_pct: number | null; fan_reported: string; fan_control?: string; joystick: { x: number; y: number; button: string } } | null;
};

export default function HardwarePanel({ state, onRefresh }: { state?: HardwareState | null; onRefresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function connection(action: string) {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/hardware/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const result = await response.json() as { detail?: unknown };
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The connection could not be changed.');
      await onRefresh();
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  const data = state?.telemetry;
  const live = state?.connected && state.fresh;
  return <section className="hardware-panel" aria-label="Live Arduino bench">
    <div className="hardware-heading"><h3><Cable size={20} /> Arduino bench</h3><span className={live ? 'hardware-live' : ''}>{live ? 'Live USB readings' : state?.connected ? 'Waiting for fresh readings' : 'Disconnected'}</span></div>
    <p className="small-detail">Physical hardware · {state?.port || 'COM3'} · MCP-Edge</p>
    {(error || state?.error) && <p className="alert" role="alert">{error || state?.error}</p>}
    {state?.dht_warning && <p className="agent-prerequisite">A DHT read failure was reported during this USB session. Displayed temperature/humidity may be old; the sketch cannot confirm recovery.</p>}
    <div className="hardware-readings">
      <div><span>Ultrasonic distance</span><strong>{live && data?.distance_valid ? `${data.distance_cm?.toFixed(1)} cm` : live ? 'Out of range / unknown' : 'Awaiting readings'}</strong><small>{live && data?.distance_valid ? 'Measured along the sensor’s beam' : 'An unknown reading does not mean clear'}</small></div>
      <div><span>Temperature / humidity</span><strong>{live && data?.temperature_c != null ? `${data.temperature_c.toFixed(1)} °C` : 'Unknown'}{live && data?.humidity_pct != null ? ` · ${data.humidity_pct.toFixed(1)}%` : ''}</strong><small>Cached by the sketch; sample age and sensor health are unknown</small></div>
      <div><span>Fan reported by Arduino</span><strong>{live && data ? data.fan_reported.toUpperCase() : 'Unknown'}</strong><small>{data?.fan_control === 'disabled_driver_required' ? 'Control disabled in the uploaded sketch; a driver is required.' : 'Original sketch uses 28/27 °C thresholds. Rotation is not measured.'}</small></div>
      <div><span>Joystick</span><strong>{live && data?.joystick ? `X ${data.joystick.x} · Y ${data.joystick.y}` : 'Unknown'}</strong><small>{live && data?.joystick ? `Button ${data.joystick.button}` : 'Awaiting readings'}</small></div>
    </div>
    <p className="small-detail">{state?.received_at ? `Last telemetry: ${new Date(state.received_at).toLocaleTimeString()} · ${state.age_seconds?.toFixed(1) ?? '?'}s ago` : 'Connect to read the sketch’s serial stream.'} · Expires after 3s</p>
    <div className="hardware-buttons"><Button variant="outline" disabled={busy} onClick={() => connection(state?.connected ? 'disconnect' : 'connect')}><RefreshCw size={16} />{busy ? 'Connecting…' : state?.connected ? 'Disconnect Arduino' : `Connect ${state?.port || 'COM3'}`}</Button></div>
    <p className="small-detail">The agent can inspect these readings and request human help. The sketch has no laptop command input. Keep the two-wire motor disconnected from Arduino signal pins until a suitable driver is wired.</p>
  </section>;
}
