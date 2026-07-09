/**
 * Settings form UI primitives (components only).
 */
import type { ComponentType, ReactNode } from "react";
import type { ModelOption } from "../../lib/aiModelRouting";
import type { ThemedSelectOption } from "../ThemedSelect";
import { modelOptionLabel } from "./helpers";

export function SettingCard({
  title,
  desc,
  icon: Icon,
  children,
}: {
  title: string;
  desc: string;
  icon: ComponentType<{ className?: string }>;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-white/5 bg-black/20 p-5">
      <div className="mb-5 flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-indigo-500/20 bg-indigo-500/10">
          <Icon className="h-4 w-4 text-indigo-300" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-neutral-100">{title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-neutral-500">{desc}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

export function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-white/5 bg-white/[0.025] px-4 py-3">
      <span>
        <span className="block text-sm text-neutral-200">{label}</span>
        <span className="mt-1 block text-xs text-neutral-500">{hint}</span>
      </span>
      <input type="checkbox" checked={checked} onChange={onChange} className="h-4 w-4 accent-indigo-500" />
    </label>
  );
}

export function TextField({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  disabled = false,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-neutral-400">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-neutral-100 outline-none transition-all placeholder:text-neutral-700 focus:border-indigo-500/50 focus:bg-white/[0.05] disabled:cursor-not-allowed disabled:text-neutral-500"
      />
    </label>
  );
}


export function modelSelectOptions(options: ModelOption[], emptyLabel: string): ThemedSelectOption[] {
  return options.length
    ? options.map((option) => ({
        value: option.key,
        label: modelOptionLabel(option),
        badge: option.vision ? (
          <span className="rounded-full bg-indigo-400/10 px-1.5 py-0.5 text-[9px] text-indigo-200">视觉</span>
        ) : undefined,
      }))
    : [{ value: "", label: emptyLabel, disabled: true }];
}
