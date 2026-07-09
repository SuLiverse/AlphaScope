/**
 * 量化页演示样例行情 opt-in + 响应 is_preview 契约读取。
 */
import { useState } from 'react';

export type PreviewAwareResult = {
  is_preview?: boolean;
  data_source?: string;
  degraded?: boolean;
  summary?: {
    is_preview?: boolean;
    data_source?: string;
    data_source_label?: string;
  };
};

/** 优先读后端 is_preview；兼容旧响应的 data_source。 */
export function isPreviewResult(res: PreviewAwareResult | null | undefined): boolean {
  if (!res) return false;
  if (typeof res.is_preview === 'boolean') return res.is_preview;
  if (typeof res.summary?.is_preview === 'boolean') return res.summary.is_preview;
  return res.data_source === 'local_preview' || res.summary?.data_source === 'local_preview';
}

export function previewResultNote(res: PreviewAwareResult | null | undefined): string {
  return isPreviewResult(res) ? ' ⚠ 当前为演示样例行情，非真实行情。' : '';
}

export function useQuantPreviewOptIn(defaultValue = false) {
  const [allowPreviewData, setAllowPreviewData] = useState(defaultValue);
  return {
    allowPreviewData,
    setAllowPreviewData,
    /** 并入 POST body */
    previewBody: { allow_preview_data: allowPreviewData } as const,
  };
}
