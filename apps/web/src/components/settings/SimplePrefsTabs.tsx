/**
 * Settings simple preference tabs: general / network / security / data / notifiers.
 */
import type { ComponentType } from "react";
import { Bell, Monitor, Server, Shield, SlidersHorizontal, CheckCircle2 } from "lucide-react";
import { motion } from "motion/react";
import { API_BASE_URL } from "../../lib/api";
import { ProviderHealthPanel } from "../ProviderHealthPanel";
import { DataSourceConfigPanel } from "../DataSourceConfigPanel";
import { NotifierSettings } from "../NotifierSettings";
import { SettingCard, TextField, ToggleRow } from "./fields";
import type { SettingsState } from "./types";

export interface SimplePrefsTabsProps {
  activeTab: "general" | "network" | "security" | "data" | "notifiers";
  settings: SettingsState;
  updateSetting: <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => void;
}

export function SimplePrefsTabs({ activeTab, settings, updateSetting }: SimplePrefsTabsProps) {
  if (activeTab === "general") {
    return (
      <motion.div key="general" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="max-w-3xl space-y-5">
        <SettingCard title="工作台偏好" desc="控制默认标的、显示密度和自动刷新行为。" icon={SlidersHorizontal}>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <TextField label="默认研究标的" value={settings.defaultStock} onChange={(value) => updateSetting("defaultStock", value)} />
            <TextField label="界面语言" value={settings.language} onChange={(value) => updateSetting("language", value)} />
            <TextField label="信息密度" value={settings.density} onChange={(value) => updateSetting("density", value)} />
            <TextField label="首选数据源组合" value={settings.activeProvider} onChange={(value) => updateSetting("activeProvider", value)} />
          </div>
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <ToggleRow
              label="自动刷新行情沙盘"
              hint="切换标的后自动重算 K 线与资金信息。"
              checked={settings.autoRefresh}
              onChange={() => updateSetting("autoRefresh", !settings.autoRefresh)}
            />
            <ToggleRow
              label="桌面通知提示"
              hint="任务完成、数据源降级和分析失败时提醒。"
              checked={settings.pushNotice}
              onChange={() => updateSetting("pushNotice", !settings.pushNotice)}
            />
          </div>
        </SettingCard>
      </motion.div>
    );
  }

  if (activeTab === "network") {
    return (
      <motion.div key="network" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="max-w-3xl space-y-5">
        <SettingCard title="后端连接" desc="用于本地 FastAPI 服务、SSE 任务事件和 Provider 健康接口。" icon={Server}>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div className="md:col-span-3">
              <TextField label="当前运行时 API Base URL" value={API_BASE_URL} onChange={() => undefined} disabled />
              <p className="mt-2 text-xs text-neutral-500">该地址由运行时配置决定；保存本页网络参数不会热切换当前 API client。</p>
            </div>
            <TextField
              label="请求超时（秒）"
              type="number"
              value={settings.timeoutSeconds}
              onChange={(value) => updateSetting("timeoutSeconds", Number(value) || 1)}
            />
            <TextField
              label="重试次数"
              type="number"
              value={settings.retryCount}
              onChange={(value) => updateSetting("retryCount", Number(value) || 0)}
            />
            <TextField label="SSE 路径" value="/api/tasks/events" onChange={() => undefined} />
          </div>
          <div className="mt-4">
            <ToggleRow
              label="启用任务进度流"
              hint="报告生成和批量分析可实时显示 task_progress。"
              checked={settings.sseEnabled}
              onChange={() => updateSetting("sseEnabled", !settings.sseEnabled)}
            />
          </div>
        </SettingCard>
      </motion.div>
    );
  }

  if (activeTab === "security") {
    return (
      <motion.div key="security" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="max-w-3xl space-y-5">
        <SettingCard title="安全与审计" desc="降低误操作、明文泄露和无证据结论进入摘要的风险。" icon={Shield}>
          <div className="grid grid-cols-1 gap-3">
            <ToggleRow
              label="危险操作二次确认"
              hint="删除证据、清空缓存或取消任务前弹出确认。"
              checked={settings.confirmDangerousActions}
              onChange={() => updateSetting("confirmDangerousActions", !settings.confirmDangerousActions)}
            />
            <ToggleRow
              label="记录本地审计日志"
              hint="保留设置变更、任务运行和数据源降级摘要。"
              checked={settings.auditLog}
              onChange={() => updateSetting("auditLog", !settings.auditLog)}
            />
            <ToggleRow
              label="关键结论必须绑定 ref 引用"
              hint="无证据结论只能进入待核验观察，不能进入最终摘要。"
              checked={settings.maskKeys}
              onChange={() => updateSetting("maskKeys", !settings.maskKeys)}
            />
          </div>
        </SettingCard>
      </motion.div>
    );
  }

  if (activeTab === "data") {
    return (
      <motion.div key="data" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
        <ProviderHealthPanel />
        <DataSourceConfigPanel />
      </motion.div>
    );
  }

  return (
    <motion.div key="notifiers" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
      <NotifierSettings />
    </motion.div>
  );
}

/** Footer status chips under the settings content area. */
export function SettingsStatusBar({ settings }: { settings: SettingsState }) {
  const items: Array<[string, string, ComponentType<{ className?: string }>]> = [
    ["当前后端", settings.apiBaseUrl, Monitor],
    ["事件流", settings.sseEnabled ? "已启用" : "已关闭", Bell],
    ["配置状态", "本地已可编辑", CheckCircle2],
  ];
  return (
    <div className="mt-6 grid grid-cols-1 gap-3 md:grid-cols-3">
      {items.map(([label, value, Icon]) => (
        <div key={label} className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
          <Icon className="mb-2 h-4 w-4 text-indigo-300" />
          <p className="text-[10px] text-neutral-500">{label}</p>
          <p className="mt-1 truncate text-sm text-neutral-200">{value}</p>
        </div>
      ))}
    </div>
  );
}
