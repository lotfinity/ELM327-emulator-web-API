"use client";

import { useCallback, useEffect, useState } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { api, BluetoothStartConfig, BluetoothState } from '@/lib/api';

const defaultConfig: BluetoothStartConfig = {
  service_name: 'LotoT ELM327',
  adapter: 'hci0',
  channel: 1,
  discoverable: true,
  pairable: true,
  auto_pair: false,
  legacy_pin: '1234',
  require_authentication: false,
  require_authorization: false,
  manage_adapter: true,
};

function BooleanOption({
  label,
  checked,
  onChange,
  description,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  description?: string;
}) {
  return (
    <label className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-1"
      />
      <span>
        <span className="block font-medium text-zinc-200">{label}</span>
        {description && <span className="mt-1 block text-xs text-zinc-500">{description}</span>}
      </span>
    </label>
  );
}

function stateClasses(state: BluetoothState['state'] | undefined) {
  if (state === 'connected') return 'border-emerald-700 bg-emerald-950/40 text-emerald-300';
  if (state === 'registered') return 'border-cyan-700 bg-cyan-950/40 text-cyan-300';
  if (state === 'starting') return 'border-amber-700 bg-amber-950/40 text-amber-300';
  if (state === 'error') return 'border-red-800 bg-red-950/40 text-red-300';
  return 'border-zinc-700 bg-zinc-900 text-zinc-300';
}

export function BluetoothPanel() {
  const [status, setStatus] = useState<BluetoothState | null>(null);
  const [config, setConfig] = useState<BluetoothStartConfig>(defaultConfig);
  const [initialized, setInitialized] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await api.getBluetoothStatus();
      setStatus(response.bluetooth);
      if (!initialized) {
        setConfig({
          ...response.bluetooth.config,
          legacy_pin: defaultConfig.legacy_pin,
        });
        setInitialized(true);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Bluetooth state');
    }
  }, [initialized]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const run = async (label: string, action: () => Promise<{ bluetooth: BluetoothState }>) => {
    setBusy(label);
    try {
      const response = await action();
      setStatus(response.bluetooth);
      setError(null);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(detail || err?.message || `Failed to ${label}`);
    } finally {
      setBusy(null);
    }
  };

  const isActive = Boolean(status?.registered || status?.connected || status?.state === 'starting');

  return (
    <div className="relative z-10 container mx-auto max-w-7xl px-4 pt-4 lg:px-6 lg:pt-6">
      <Card className="border-cyan-900/60 bg-black/50 shadow-2xl shadow-cyan-950/10">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>Bluetooth Classic ELM327 transport</CardTitle>
              <CardDescription className="mt-1">
                BlueZ Serial Port Profile using the standard Android OBD-II SPP UUID.
              </CardDescription>
            </div>
            <span className={`rounded-full border px-3 py-1 text-sm font-medium ${stateClasses(status?.state)}`}>
              {(status?.state || 'loading').toUpperCase()}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {(error || status?.last_error) && (
            <Alert variant="destructive" className="border-red-900 bg-red-950/30">
              <AlertDescription>{error || status?.last_error}</AlertDescription>
            </Alert>
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
              <div className="text-xs text-zinc-500">Adapter</div>
              <div className="mt-1 font-mono text-sm">{status?.adapter.name || config.adapter}</div>
              <div className="mt-1 text-xs text-zinc-500">{status?.adapter.address || 'Not detected yet'}</div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
              <div className="text-xs text-zinc-500">Connected phone</div>
              <div className="mt-1 font-mono text-sm">{status?.client.address || 'None'}</div>
              <div className="mt-1 text-xs text-zinc-500">Single client at a time</div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
              <div className="text-xs text-zinc-500">Bluetooth commands</div>
              <div className="mt-1 font-mono text-lg">{status?.traffic.commands ?? 0}</div>
              <div className="mt-1 truncate text-xs text-zinc-500">Last: {status?.traffic.last_command || '—'}</div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
              <div className="text-xs text-zinc-500">Traffic</div>
              <div className="mt-1 font-mono text-sm">
                RX {status?.traffic.rx_bytes ?? 0} / TX {status?.traffic.tx_bytes ?? 0} bytes
              </div>
              <div className="mt-1 truncate text-xs text-zinc-500">Channel {config.channel}</div>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <label className="space-y-1 text-sm">
              <span className="text-zinc-400">Advertised device name</span>
              <Input
                value={config.service_name}
                disabled={isActive}
                onChange={(event) => setConfig({ ...config, service_name: event.target.value })}
                className="bg-zinc-950/60"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-zinc-400">BlueZ adapter</span>
              <Input
                value={config.adapter}
                disabled={isActive}
                onChange={(event) => setConfig({ ...config, adapter: event.target.value })}
                className="bg-zinc-950/60 font-mono"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="space-y-1 text-sm">
                <span className="text-zinc-400">RFCOMM channel</span>
                <Input
                  type="number"
                  min={1}
                  max={30}
                  value={config.channel}
                  disabled={isActive}
                  onChange={(event) => setConfig({ ...config, channel: Number(event.target.value) })}
                  className="bg-zinc-950/60 font-mono"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span className="text-zinc-400">Legacy PIN</span>
                <Input
                  value={config.legacy_pin}
                  disabled={isActive || !config.auto_pair}
                  onChange={(event) => setConfig({ ...config, legacy_pin: event.target.value })}
                  className="bg-zinc-950/60 font-mono"
                />
              </label>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <BooleanOption
              label="Manage adapter"
              checked={config.manage_adapter}
              onChange={(manage_adapter) => setConfig({ ...config, manage_adapter })}
              description="Power on and set the BlueZ alias from this app."
            />
            <BooleanOption
              label="Discoverable and pairable"
              checked={config.discoverable && config.pairable}
              onChange={(enabled) => setConfig({ ...config, discoverable: enabled, pairable: enabled })}
              description="Expose the host as an OBD-II Bluetooth device."
            />
            <BooleanOption
              label="Headless auto-pair"
              checked={config.auto_pair}
              onChange={(auto_pair) => setConfig({ ...config, auto_pair })}
              description="Accept nearby pairing requests with the configured PIN. Enable only while testing."
            />
            <BooleanOption
              label="Require secure link"
              checked={config.require_authentication}
              onChange={(require_authentication) => setConfig({ ...config, require_authentication })}
              description="Require Bluetooth authentication; some clone-style OBD apps prefer insecure SPP."
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => run('start Bluetooth', () => api.startBluetooth(config))}
              disabled={busy !== null || isActive}
            >
              Start Bluetooth SPP
            </Button>
            <Button
              variant="outline"
              onClick={() => run('disconnect Bluetooth client', () => api.disconnectBluetooth())}
              disabled={busy !== null || !status?.connected}
            >
              Disconnect phone
            </Button>
            <Button
              variant="destructive"
              onClick={() => run('stop Bluetooth', () => api.stopBluetooth())}
              disabled={busy !== null || !isActive}
            >
              Stop Bluetooth
            </Button>
          </div>

          <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-xs text-zinc-400">
            <div className="font-mono text-zinc-300">UUID: {status?.service_uuid || '00001101-0000-1000-8000-00805F9B34FB'}</div>
            <div className="mt-1">
              Pair the phone with <strong>{config.service_name}</strong>, then choose that paired device in Torque,
              Car Scanner, or the LotoT Bluetooth connector.
            </div>
            {status?.last_pairing_event && <div className="mt-1">Pairing: {status.last_pairing_event}</div>}
            {status?.warnings.map((warning) => <div key={warning} className="mt-1 text-amber-300">{warning}</div>)}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
