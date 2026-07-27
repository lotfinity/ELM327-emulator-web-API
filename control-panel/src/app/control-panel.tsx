"use client";

import { useCallback, useEffect, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { APITester } from '@/components/APITester';
import { ParameterControl } from '@/components/ParameterControl';
import { api, EmulatorState, getWebSocketUrl, HistoryEntry } from '@/lib/api';

interface Values {
  engine_rpm: number;
  vehicle_speed: number;
  throttle_position: number;
  engine_coolant_temp: number;
  engine_load: number;
  fuel_level: number;
  intake_manifold_pressure: number;
  timing_advance: number;
  oxygen_sensor_voltage: number;
  mass_air_flow: number;
}

type ParameterMeta = {
  min: number;
  max: number;
  unit: string;
};

const parameterMeta: Record<keyof Values, ParameterMeta> = {
  engine_rpm: { min: 0, max: 8000, unit: 'RPM' },
  vehicle_speed: { min: 0, max: 255, unit: 'km/h' },
  throttle_position: { min: 0, max: 100, unit: '%' },
  engine_coolant_temp: { min: -40, max: 215, unit: '°C' },
  engine_load: { min: 0, max: 100, unit: '%' },
  fuel_level: { min: 0, max: 100, unit: '%' },
  intake_manifold_pressure: { min: 0, max: 255, unit: 'kPa' },
  timing_advance: { min: -64, max: 63.5, unit: '°' },
  oxygen_sensor_voltage: { min: 0, max: 1.275, unit: 'V' },
  mass_air_flow: { min: 0, max: 655.35, unit: 'g/s' },
};

const initialValues: Values = {
  engine_rpm: 0,
  vehicle_speed: 0,
  throttle_position: 0,
  engine_coolant_temp: 0,
  engine_load: 0,
  fuel_level: 0,
  intake_manifold_pressure: 0,
  timing_advance: 0,
  oxygen_sensor_voltage: 0,
  mass_air_flow: 0,
};

const faultPresets = [
  { value: 'healthy', label: 'Healthy' },
  { value: 'engine_off', label: 'Engine off' },
  { value: 'slow_adapter', label: 'Slow adapter' },
  { value: 'intermittent_drop', label: 'Drop requests' },
  { value: 'malformed_frames', label: 'Malformed frames' },
  { value: 'ecu_unavailable', label: 'ECU unavailable' },
];

function StatePill({ state }: { state: EmulatorState['state'] }) {
  const classes = {
    running: 'border-emerald-700 bg-emerald-950/40 text-emerald-300',
    paused: 'border-amber-700 bg-amber-950/40 text-amber-300',
    stopped: 'border-red-800 bg-red-950/40 text-red-300',
  }[state];

  return (
    <span className={`rounded-full border px-3 py-1 text-sm font-medium ${classes}`}>
      {state.toUpperCase()}
    </span>
  );
}

function NumberField({
  label,
  value,
  step = 0.1,
  onChange,
}: {
  label: string;
  value: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="space-y-1 text-sm">
      <span className="text-zinc-400">{label}</span>
      <Input
        type="number"
        min={0}
        step={step}
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => onChange(Number(event.target.value))}
        className="bg-zinc-950/60 font-mono"
      />
    </label>
  );
}

function ControlPanel() {
  const [values, setValues] = useState<Values>(initialValues);
  const [emulator, setEmulator] = useState<EmulatorState | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [counters, setCounters] = useState<Record<string, unknown>>({});
  const [activeTasks, setActiveTasks] = useState<Record<string, string[]>>({});
  const [liveConnected, setLiveConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [timingDraft, setTimingDraft] = useState({ p1: 0, p2: 0, p3: 5, p4: 1440 });
  const [faultDraft, setFaultDraft] = useState({
    no_response: false,
    drop_every_n: 0,
    malformed_every_n: 0,
    latency_jitter_ms: 0,
    next_command_delay_seconds: 0,
  });
  const [choiceMode, setChoiceMode] = useState<'sequential' | 'random'>('sequential');
  const [choiceWeights, setChoiceWeights] = useState('1');

  const refresh = useCallback(async () => {
    try {
      const [valueResponse, statusResponse, historyResponse, counterResponse, taskResponse] = await Promise.all([
        api.getAllValues(),
        api.getStatus(),
        api.getHistory(40),
        api.getCounters(),
        api.getTasks(),
      ]);
      setValues(valueResponse.values);
      setEmulator(statusResponse.emulator);
      setHistory(historyResponse.history);
      setCounters(counterResponse.counters || {});
      setActiveTasks(taskResponse.tasks?.active || {});
      setTimingDraft({
        p1: statusResponse.emulator.timing.p1,
        p2: statusResponse.emulator.timing.p2,
        p3: statusResponse.emulator.timing.p3,
        p4: statusResponse.emulator.timing.p4,
      });
      setFaultDraft(statusResponse.emulator.faults);
      setChoiceMode(statusResponse.emulator.choice.mode);
      setChoiceWeights(statusResponse.emulator.choice.weights.join(', '));
      setError(null);
    } catch (err) {
      setError('Unable to reach the emulator backend. Start FastAPI on port 8000 and check NEXT_PUBLIC_API_BASE_URL.');
    }
  }, []);

  useEffect(() => {
    refresh();
    let socket: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(getWebSocketUrl());
      socket.onopen = () => setLiveConnected(true);
      socket.onmessage = (event) => {
        try {
          const snapshot = JSON.parse(event.data);
          if (snapshot.type !== 'snapshot') return;
          setEmulator(snapshot.emulator);
          setValues(snapshot.values);
          setHistory(snapshot.history || []);
          setCounters(snapshot.counters || {});
          setActiveTasks(snapshot.tasks || {});
          setError(null);
        } catch (messageError) {
          console.error('Invalid emulator WebSocket message', messageError);
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setLiveConnected(false);
        if (!disposed) reconnectTimer = window.setTimeout(connect, 3000);
      };
    };

    connect();
    const fallbackInterval = window.setInterval(refresh, 10000);
    return () => {
      disposed = true;
      window.clearInterval(fallbackInterval);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [refresh]);

  const execute = async (label: string, operation: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await operation();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${label}`);
    } finally {
      setBusy(null);
    }
  };

  const handleValueChange = async (parameter: string, newValue: number) => {
    await execute(`update ${parameter}`, async () => {
      await api.setValue(parameter, newValue);
      setValues((previous) => ({ ...previous, [parameter]: newValue }));
    });
  };

  const saveTiming = () => execute('save timing', () => api.setTiming(timingDraft));

  const saveFaults = () => execute('save faults', () => api.setFaults(faultDraft));

  const saveChoice = () => {
    const weights = choiceWeights
      .split(',')
      .map((item) => Number(item.trim()))
      .filter((item) => Number.isFinite(item) && item >= 0);
    return execute('save response choice', () => api.setChoice(choiceMode, weights.length ? weights : [1]));
  };

  return (
    <div className="container mx-auto max-w-7xl space-y-6 p-4 lg:p-6">
      {error && (
        <Alert variant="destructive" className="border-red-900 bg-red-950/30">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader className="pb-2">
            <CardDescription>Emulator state</CardDescription>
          </CardHeader>
          <CardContent>{emulator ? <StatePill state={emulator.state} /> : 'Loading…'}</CardContent>
        </Card>
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader className="pb-2"><CardDescription>Scenario</CardDescription></CardHeader>
          <CardContent className="font-mono text-lg">{emulator?.scenario || '—'}</CardContent>
        </Card>
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader className="pb-2"><CardDescription>Processed requests</CardDescription></CardHeader>
          <CardContent className="font-mono text-lg">{emulator?.request_count ?? 0}</CardContent>
        </Card>
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader className="pb-2"><CardDescription>Last response</CardDescription></CardHeader>
          <CardContent className="font-mono text-lg">
            {emulator ? `${(emulator.last_execution_time * 1000).toFixed(1)} ms` : '—'}
          </CardContent>
        </Card>
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader className="pb-2"><CardDescription>Live stream</CardDescription></CardHeader>
          <CardContent className="font-mono text-lg">
            {liveConnected ? 'CONNECTED' : 'RECONNECTING'}
          </CardContent>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-black/40">
        <CardHeader>
          <CardTitle>Runtime controls</CardTitle>
          <CardDescription>Control command processing without touching the upstream terminal.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => execute('start', () => api.control('start'))} disabled={busy !== null}>Start</Button>
            <Button variant="outline" onClick={() => execute('pause', () => api.control('pause'))} disabled={busy !== null}>Pause</Button>
            <Button variant="outline" onClick={() => execute('resume', () => api.control('resume'))} disabled={busy !== null}>Resume</Button>
            <Button variant="outline" onClick={() => execute('stop', () => api.control('stop'))} disabled={busy !== null}>Stop</Button>
            <Button variant="destructive" onClick={() => execute('reset', () => api.control('reset'))} disabled={busy !== null}>Reset all</Button>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-zinc-400">Vehicle scenario</span>
              <Select
                value={emulator?.scenario || 'default'}
                onValueChange={(scenario) => execute('change scenario', () => api.setScenario(scenario))}
              >
                <SelectTrigger><SelectValue placeholder="Select scenario" /></SelectTrigger>
                <SelectContent>
                  {(emulator?.scenarios || ['default']).map((scenario) => (
                    <SelectItem key={scenario} value={scenario}>{scenario}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>

            <div className="space-y-1 text-sm">
              <span className="text-zinc-400">Response selection</span>
              <div className="grid grid-cols-2 gap-2">
                <Select value={choiceMode} onValueChange={(value) => setChoiceMode(value as 'sequential' | 'random')}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sequential">Sequential</SelectItem>
                    <SelectItem value="random">Random</SelectItem>
                  </SelectContent>
                </Select>
                <Input
                  value={choiceWeights}
                  onChange={(event) => setChoiceWeights(event.target.value)}
                  placeholder="Weights: 10, 1, 0.5"
                  className="font-mono"
                />
              </div>
              <Button size="sm" variant="outline" onClick={saveChoice} className="mt-2">Apply choice mode</Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader>
            <CardTitle>UDS and response timing</CardTitle>
            <CardDescription>P1–P4 timers are passed directly to the upstream emulator.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <NumberField label="P1 inter-byte (s)" value={timingDraft.p1} onChange={(p1) => setTimingDraft({ ...timingDraft, p1 })} />
              <NumberField label="P2 response (s)" value={timingDraft.p2} onChange={(p2) => setTimingDraft({ ...timingDraft, p2 })} />
              <NumberField label="P3 multiframe (s)" value={timingDraft.p3} onChange={(p3) => setTimingDraft({ ...timingDraft, p3 })} />
              <NumberField label="P4 request (s)" value={timingDraft.p4} onChange={(p4) => setTimingDraft({ ...timingDraft, p4 })} />
            </div>
            <Button onClick={saveTiming} disabled={busy !== null}>Apply timing</Button>
          </CardContent>
        </Card>

        <Card className="border-zinc-800 bg-black/40">
          <CardHeader>
            <CardTitle>Fault injection</CardTitle>
            <CardDescription>Simulate timeouts, interruptions, missing frames, and corrupted replies.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {faultPresets.map((preset) => (
                <Button
                  key={preset.value}
                  size="sm"
                  variant="outline"
                  onClick={() => execute(`apply ${preset.label}`, () => api.applyFaultPreset(preset.value))}
                >
                  {preset.label}
                </Button>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={faultDraft.no_response}
                onChange={(event) => setFaultDraft({ ...faultDraft, no_response: event.target.checked })}
              />
              Return no response for every command
            </label>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <NumberField label="Drop every N" value={faultDraft.drop_every_n} step={1} onChange={(drop_every_n) => setFaultDraft({ ...faultDraft, drop_every_n })} />
              <NumberField label="Malformed every N" value={faultDraft.malformed_every_n} step={1} onChange={(malformed_every_n) => setFaultDraft({ ...faultDraft, malformed_every_n })} />
              <NumberField label="Random jitter (ms)" value={faultDraft.latency_jitter_ms} step={10} onChange={(latency_jitter_ms) => setFaultDraft({ ...faultDraft, latency_jitter_ms })} />
              <NumberField label="Delay next command (s)" value={faultDraft.next_command_delay_seconds} onChange={(next_command_delay_seconds) => setFaultDraft({ ...faultDraft, next_command_delay_seconds })} />
            </div>
            <Button onClick={saveFaults} disabled={busy !== null}>Apply fault configuration</Button>
          </CardContent>
        </Card>
      </div>

      <Card className="border-zinc-800 bg-black/40">
        <CardHeader>
          <CardTitle>Live ECU parameters</CardTitle>
          <CardDescription>These controls now modify the actual PID answer overrides used by the emulator.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(Object.entries(values) as [keyof Values, number][]).map(([parameter, value]) => {
              const meta = parameterMeta[parameter];
              return (
                <div key={parameter} className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="text-sm font-medium">{parameter.toUpperCase().replace(/_/g, ' ')}</span>
                    <span className="font-mono text-sm text-zinc-300">{value} {meta.unit}</span>
                  </div>
                  <ParameterControl
                    parameter={parameter}
                    value={value}
                    onChange={handleValueChange}
                    protocol="auto"
                  />
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-black/40">
        <CardHeader>
          <CardTitle>Counters and active tasks</CardTitle>
          <CardDescription>Runtime counters from the upstream emulator and currently active plugin tasks.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5 lg:grid-cols-2">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {Object.entries(counters).slice(0, 15).map(([name, value]) => (
              <div key={name} className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
                <div className="truncate text-xs text-zinc-500">{name}</div>
                <div className="mt-1 truncate font-mono text-sm">{String(value)}</div>
              </div>
            ))}
            {Object.keys(counters).length === 0 && <p className="text-sm text-zinc-500">No counters yet.</p>}
          </div>
          <div className="space-y-2">
            {Object.entries(activeTasks).map(([ecu, tasks]) => (
              <div key={ecu} className="rounded-lg border border-zinc-800 p-3">
                <div className="font-mono text-sm">ECU {ecu}</div>
                <div className="mt-1 text-xs text-zinc-500">{tasks.join(', ')}</div>
              </div>
            ))}
            {Object.keys(activeTasks).length === 0 && (
              <p className="text-sm text-zinc-500">No active tasks. Task-based UDS flows will appear here when triggered.</p>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <APITester />
        <Card className="border-zinc-800 bg-black/40">
          <CardHeader>
            <CardTitle>Live request history</CardTitle>
            <CardDescription>The most recent commands, outcomes, scenarios, and response times.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {history.length === 0 && <p className="text-sm text-zinc-500">No requests yet.</p>}
              {history.slice(0, 15).map((entry, index) => (
                <div key={`${entry.timestamp}-${index}`} className="rounded-lg border border-zinc-800 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <code className="font-medium text-zinc-100">{entry.command}</code>
                    <span className="text-zinc-500">
                      {entry.outcome} · {(entry.execution_time * 1000).toFixed(1)} ms · {entry.scenario}
                    </span>
                  </div>
                  <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap text-xs text-zinc-400">
                    {entry.response || '(empty response)'}
                  </pre>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default ControlPanel;
