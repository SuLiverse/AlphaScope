import type { ModelOption } from "../../lib/aiModelRouting";
import type { ThemedSelectOption } from "../ThemedSelect";
import { modelOptionLabel } from "./helpers";

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
