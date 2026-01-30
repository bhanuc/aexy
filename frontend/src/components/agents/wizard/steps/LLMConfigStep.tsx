"use client";

import { Info } from "lucide-react";
import { LLMProviderSelector } from "@/components/agents/shared";

interface LLMConfigStepProps {
  provider: "claude" | "gemini" | "ollama";
  model: string;
  temperature: number;
  maxTokens: number;
  onProviderChange: (provider: "claude" | "gemini" | "ollama") => void;
  onModelChange: (model: string) => void;
  onTemperatureChange: (temp: number) => void;
  onMaxTokensChange: (tokens: number) => void;
}

export function LLMConfigStep({
  provider,
  model,
  temperature,
  maxTokens,
  onProviderChange,
  onModelChange,
  onTemperatureChange,
  onMaxTokensChange,
}: LLMConfigStepProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-white mb-2">
          LLM Configuration
        </h2>
        <p className="text-slate-400">
          Choose the language model that will power your agent's intelligence.
        </p>
      </div>

      {/* Provider & Model */}
      <LLMProviderSelector
        provider={provider}
        model={model}
        onChange={({ provider: p, model: m }) => {
          onProviderChange(p);
          onModelChange(m);
        }}
      />

      {/* Temperature */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Temperature
        </label>
        <div className="space-y-3">
          <div className="flex items-center gap-4">
            <input
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={temperature}
              onChange={(e) => onTemperatureChange(parseFloat(e.target.value))}
              className="flex-1 h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-purple-500"
            />
            <span className="w-12 text-right text-white font-medium">
              {temperature.toFixed(1)}
            </span>
          </div>
          <div className="flex justify-between text-xs text-slate-500">
            <span>Precise (0.0)</span>
            <span>Balanced (0.5)</span>
            <span>Creative (1.0)</span>
          </div>
        </div>
        <div className="mt-2 p-3 bg-slate-700/50 rounded-lg flex items-start gap-2">
          <Info className="h-4 w-4 text-blue-400 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-slate-400">
            Lower values make responses more focused and deterministic. Higher
            values allow more creativity and variation.
          </p>
        </div>
      </div>

      {/* Max Tokens */}
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-2">
          Max Response Length
        </label>
        <div className="grid grid-cols-4 gap-2">
          {[1000, 2000, 4000, 8000].map((tokens) => (
            <button
              key={tokens}
              onClick={() => onMaxTokensChange(tokens)}
              className={`px-4 py-2 rounded-lg border transition ${
                maxTokens === tokens
                  ? "bg-purple-500/20 border-purple-500 text-purple-400"
                  : "bg-slate-700 border-slate-600 text-slate-300 hover:border-slate-500"
              }`}
            >
              {tokens >= 1000 ? `${tokens / 1000}K` : tokens} tokens
            </button>
          ))}
        </div>
        <div className="mt-2 flex items-center gap-4">
          <span className="text-sm text-slate-400">Or enter custom:</span>
          <input
            type="number"
            value={maxTokens}
            onChange={(e) => onMaxTokensChange(parseInt(e.target.value) || 2000)}
            min={100}
            max={32000}
            className="w-28 px-3 py-1.5 bg-slate-700 border border-slate-600 rounded-lg text-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          />
        </div>
        <p className="mt-2 text-sm text-slate-500">
          Maximum number of tokens in the agent's response. ~750 words per 1K tokens.
        </p>
      </div>
    </div>
  );
}
