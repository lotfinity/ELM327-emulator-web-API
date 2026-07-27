"use client";

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Slider } from '@/components/ui/slider';
import { api } from '@/lib/api';

interface ParameterRanges {
  [key: string]: {
    min: number;
    max: number;
    step: number;
    unit: string;
    pid: string;
  };
}

const parameterRanges: ParameterRanges = {
  engine_rpm: { min: 0, max: 8000, step: 50, unit: 'RPM', pid: '0C' },
  vehicle_speed: { min: 0, max: 255, step: 1, unit: 'km/h', pid: '0D' },
  throttle_position: { min: 0, max: 100, step: 1, unit: '%', pid: '11' },
  engine_coolant_temp: { min: -40, max: 215, step: 1, unit: '°C', pid: '05' },
  engine_load: { min: 0, max: 100, step: 1, unit: '%', pid: '04' },
  fuel_level: { min: 0, max: 100, step: 1, unit: '%', pid: '2F' },
  intake_manifold_pressure: { min: 0, max: 255, step: 1, unit: 'kPa', pid: '0B' },
  timing_advance: { min: -64, max: 63.5, step: 0.5, unit: '°', pid: '0E' },
  oxygen_sensor_voltage: { min: 0, max: 1.275, step: 0.005, unit: 'V', pid: '15' },
  mass_air_flow: { min: 0, max: 655.35, step: 0.01, unit: 'g/s', pid: '10' },
};

interface ParameterControlProps {
  parameter: string;
  value: number;
  onChange: (parameter: string, value: number) => void;
  protocol?: string;
}

export function ParameterControl({ parameter, value, onChange, protocol = 'auto' }: ParameterControlProps) {
  const range = parameterRanges[parameter];
  const [localValue, setLocalValue] = useState(value);
  const [rawResponse, setRawResponse] = useState<unknown>(null);

  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  if (!range) {
    return <p className="text-sm text-red-400">Unsupported parameter: {parameter}</p>;
  }

  const commitValue = (nextValue: number) => {
    const clamped = Math.min(range.max, Math.max(range.min, nextValue));
    setLocalValue(clamped);
    onChange(parameter, clamped);
  };

  const fetchRawData = async () => {
    try {
      setRawResponse(await api.sendCommand({ command: `01 ${range.pid}`, protocol }));
    } catch (error) {
      setRawResponse({ error: error instanceof Error ? error.message : 'Failed to fetch raw data' });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={range.min}
          max={range.max}
          step={range.step}
          value={localValue}
          onChange={(event) => setLocalValue(Number(event.target.value))}
          onBlur={() => commitValue(localValue)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commitValue(localValue);
          }}
          className="h-9 bg-black/30 font-mono"
        />
        <span className="min-w-12 text-sm text-zinc-500">{range.unit}</span>
      </div>

      <Slider
        min={range.min}
        max={range.max}
        step={range.step}
        value={[localValue]}
        onValueChange={([nextValue]) => setLocalValue(nextValue)}
        onValueCommit={([nextValue]) => commitValue(nextValue)}
      />

      <div className="flex justify-between text-xs text-zinc-600">
        <span>{range.min}</span>
        <span>{range.max}</span>
      </div>

      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="outline" size="sm" className="w-full font-mono text-xs">
            Raw response · PID 01 {range.pid}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="mt-2 space-y-2 rounded-lg border border-zinc-800 bg-black/30 p-3">
          <Button variant="ghost" size="sm" onClick={fetchRawData}>Request PID</Button>
          {rawResponse !== null && (
            <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-xs text-zinc-400">
              {JSON.stringify(rawResponse, null, 2)}
            </pre>
          )}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
