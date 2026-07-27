import axios from 'axios';

const browserDefaultApiUrl =
  typeof window === 'undefined'
    ? 'http://localhost:8000'
    : `${window.location.protocol}//${window.location.hostname}:8000`;

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  browserDefaultApiUrl;

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export type EmulatorState = {
  state: 'running' | 'paused' | 'stopped';
  running: boolean;
  paused: boolean;
  scenario: string;
  scenarios: string[];
  interface: string;
  client_connected: boolean;
  request_count: number;
  last_execution_time: number;
  timing: {
    p1: number;
    p2: number;
    p3: number;
    p4: number;
    response_delay: number;
  };
  choice: {
    mode: 'sequential' | 'random';
    weights: number[];
  };
  faults: {
    no_response: boolean;
    drop_every_n: number;
    malformed_every_n: number;
    latency_jitter_ms: number;
    next_command_delay_seconds: number;
  };
  version: string;
  vehicle: {
    make: string;
    model: string;
    model_year: number;
    engine: string;
    power_kw: number;
    power_ps: number;
    fuel: string;
    odometer_km: number;
    vin: string;
    vin_is_synthetic: boolean;
    engine_ecu: string;
    calibration_id: string;
  };
};

export type BluetoothStartConfig = {
  service_name: string;
  adapter: string;
  channel: number;
  discoverable: boolean;
  pairable: boolean;
  auto_pair: boolean;
  legacy_pin: string;
  require_authentication: boolean;
  require_authorization: boolean;
  manage_adapter: boolean;
};

export type BluetoothState = {
  available: boolean;
  state: 'stopped' | 'starting' | 'registered' | 'connected' | 'released' | 'error';
  registered: boolean;
  connected: boolean;
  service_uuid: string;
  profile_path: string;
  config: BluetoothStartConfig;
  adapter: {
    path: string | null;
    name: string;
    address: string | null;
    alias: string | null;
  };
  client: {
    device_path: string | null;
    address: string | null;
    connected_since: string | null;
    last_disconnected_at: string | null;
  };
  traffic: {
    rx_bytes: number;
    tx_bytes: number;
    commands: number;
    last_command: string | null;
  };
  agent_registered: boolean;
  last_pairing_event: string | null;
  warnings: string[];
  last_error: string | null;
};

export type HistoryEntry = {
  timestamp: string;
  command: string;
  response: string;
  outcome: string;
  execution_time: number;
  scenario: string;
};

export const getWebSocketUrl = () => `${API_BASE_URL.replace(/^http/, 'ws')}/api/v1/ws`;

export const api = {
  getAllValues: async () => {
    const response = await apiClient.get('/api/v1/ecu/values');
    return response.data;
  },
  setValue: async (parameter: string, value: number) => {
    const response = await apiClient.post('/api/v1/ecu/set-value', { parameter, value });
    return response.data;
  },
  sendCommand: async (command: { command: string; protocol: string }) => {
    const response = await apiClient.post('/api/v1/command', command);
    return response.data;
  },
  resetValues: async () => {
    const response = await apiClient.post('/api/v1/ecu/reset');
    return response.data;
  },
  getStatus: async (): Promise<{ status: string; emulator: EmulatorState; bluetooth?: BluetoothState }> => {
    const response = await apiClient.get('/api/v1/status');
    return response.data;
  },
  control: async (action: 'start' | 'pause' | 'resume' | 'stop' | 'reset') => {
    const response = await apiClient.post('/api/v1/control', { action });
    return response.data;
  },
  setScenario: async (scenario: string) => {
    const response = await apiClient.post('/api/v1/scenario', { scenario });
    return response.data;
  },
  setTiming: async (timing: Partial<EmulatorState['timing']>) => {
    const response = await apiClient.post('/api/v1/timing', timing);
    return response.data;
  },
  setChoice: async (mode: 'sequential' | 'random', weights: number[]) => {
    const response = await apiClient.post('/api/v1/choice', { mode, weights });
    return response.data;
  },
  setFaults: async (faults: Partial<EmulatorState['faults']>) => {
    const response = await apiClient.post('/api/v1/faults', faults);
    return response.data;
  },
  applyFaultPreset: async (preset: string) => {
    const response = await apiClient.post('/api/v1/faults/preset', { preset });
    return response.data;
  },
  getHistory: async (limit = 40): Promise<{ status: string; history: HistoryEntry[] }> => {
    const response = await apiClient.get('/api/v1/history', { params: { limit } });
    return response.data;
  },
  getCounters: async () => {
    const response = await apiClient.get('/api/v1/counters');
    return response.data;
  },
  getTasks: async () => {
    const response = await apiClient.get('/api/v1/tasks');
    return response.data;
  },
  getBluetoothStatus: async (): Promise<{ status: string; bluetooth: BluetoothState }> => {
    const response = await apiClient.get('/api/v1/bluetooth/status');
    return response.data;
  },
  startBluetooth: async (config: BluetoothStartConfig): Promise<{ status: string; bluetooth: BluetoothState }> => {
    const response = await apiClient.post('/api/v1/bluetooth/start', config);
    return response.data;
  },
  stopBluetooth: async (): Promise<{ status: string; bluetooth: BluetoothState }> => {
    const response = await apiClient.post('/api/v1/bluetooth/stop');
    return response.data;
  },
  disconnectBluetooth: async (): Promise<{ status: string; bluetooth: BluetoothState }> => {
    const response = await apiClient.post('/api/v1/bluetooth/disconnect');
    return response.data;
  },
};
