import React from 'react';
import { AgentOpinion, AnalysisResult } from '../../types';
import { DataIntegrityBanner } from './DataIntegrityBanner';

interface Props {
  stockSymbol: string;
  stockName?: string;
  result: AnalysisResult;
}

export const DecisionSummary: React.FC<Props> = ({ stockSymbol, stockName, result }) => {
  // Aggregate overall signal and confidence based on agents
  const agents = Object.values(result.agents) as AgentOpinion[];
  const buyCount = agents.filter(a => a.signal === 'BUY').length;
  const sellCount = agents.filter(a => a.signal === 'SELL').length;
  
  let overallSignal = 'HOLD';
  let signalColor = 'text-neutral-400';
  let signalBg = 'bg-neutral-500/10 border-neutral-500/20';

  if (buyCount > sellCount && buyCount > 0) {
    overallSignal = 'BUY';
    signalColor = 'text-rose-400';
    signalBg = 'bg-rose-500/10 border-rose-500/20';
  } else if (sellCount > buyCount && sellCount > 0) {
    overallSignal = 'SELL';
    signalColor = 'text-emerald-400'; // Green for sell in CN
    signalBg = 'bg-emerald-500/10 border-emerald-500/20';
  }

  const avgConfidence = agents.length > 0 
    ? agents.reduce((acc, a) => acc + a.confidence, 0) / agents.length 
    : 0;

  return (
    <div className="flex flex-col gap-4 mb-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 py-4">
        <div className="min-w-0">
          <h2 className="sr-only">
            {stockName || 'Unknown'} <span className="text-white/50 text-base font-normal ml-2">{stockSymbol}</span>
          </h2>
          <div className="text-xs text-neutral-400 mt-1 flex items-center gap-2">
            <span>Agent 汇总观点:</span>
            <span className={`px-2 py-0.5 rounded border ${signalBg} ${signalColor} font-bold tracking-wide`}>
              {overallSignal}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4 text-right">
          <div>
            <div className="text-xs text-neutral-400 mb-1">Agent 平均置信度</div>
            <div className="text-xl font-mono text-sky-400">
              {(avgConfidence * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      <DataIntegrityBanner result={result} />
    </div>
  );
};
