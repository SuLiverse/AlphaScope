import React from 'react';

/** 演示样例行情 opt-in（回测页 / 策略实验室共用）。 */
export function QuantPreviewCheckbox({
  checked,
  onChange,
  testId = 'allow-preview-data',
  hint = '允许演示样例行情（无真实行情时才用合成数据；默认关闭）',
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  testId?: string;
  hint?: string;
}) {
  return (
    <label className="mt-3 inline-flex max-w-xl cursor-pointer items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-100/90">
      <input
        type="checkbox"
        data-testid={testId}
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 rounded border-amber-500/40 bg-black/40"
      />
      <span>{hint}</span>
    </label>
  );
}
