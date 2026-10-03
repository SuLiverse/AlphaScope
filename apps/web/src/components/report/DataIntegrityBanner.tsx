import React from 'react';
import { AlertTriangle, CheckCircle2, CircleHelp, XCircle } from 'lucide-react';
import { AnalysisResult } from '../../types';
import { deriveDataIntegritySeverity } from '../../lib/analysisAdapter';

interface Props {
  result: AnalysisResult;
}

export const DataIntegrityBanner: React.FC<Props> = ({ result }) => {
  const severity = deriveDataIntegritySeverity(result);

  if (severity === 'unknown') return <div className="flex items-start gap-2 border-l-2 border-neutral-500 p-3 text-sm text-neutral-400"><CircleHelp className="h-4 w-4 shrink-0 mt-0.5" /><span>未记录数据源健康状态，无法确认采集是否完整。AI 结论不构成投资建议。</span></div>;

  if (severity === 'green') {
    return (
      <div className="flex items-center gap-2 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded-lg text-sm">
        <CheckCircle2 className="w-4 h-4 shrink-0" />
        <span>已记录的采集请求未报告错误，不代表资料完整或结论已经核实。AI 结论不构成投资建议。</span>
      </div>
    );
  }

  if (severity === 'yellow') {
    return (
      <div className="flex items-center gap-2 p-3 bg-amber-500/10 border border-amber-500/20 text-amber-400 rounded-lg text-sm">
        <AlertTriangle className="w-4 h-4 shrink-0" />
        <span>部分数据源降级或补全，结论需结合来源细节复核。AI 结论不构成投资建议。</span>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 text-red-400 rounded-lg text-sm">
      <XCircle className="w-4 h-4 shrink-0" />
      <span>严重降级：核心行情或风控数据缺失，本次分析仅供粗略参考。AI 结论不构成投资建议。</span>
    </div>
  );
};
