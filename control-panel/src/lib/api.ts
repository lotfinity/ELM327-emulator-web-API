import axios from 'axios';

const apiClient = axios.create({
  baseURL:
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    'http://localhost:8000',
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
};

export type HistoryEntry = {
  timestamp: string;
  command: string;
  response: string;
  outcome: string;
  execution_time: number;
  scenario: string;
};

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
  getStatus: async (): Promise<{ status: string; emulator: EmulatorState }> => {
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
};
