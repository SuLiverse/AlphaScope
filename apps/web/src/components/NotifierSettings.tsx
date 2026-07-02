import { useCallback, useEffect, useState } from 'react';
import { Bell, Check, Loader2, Send, Trash2, Zap } from 'lucide-react';
import { fetchApi } from '../lib/api';
import { cn } from '../lib/utils';

type Channel = 'serverchan' | 'pushplus' | 'feishu' | 'telegram' | 'email';

interface ChannelInfo {
  channel: Channel;
  enabled: boolean;
  has_credentials: boolean;
  fields_configured: Record<string, boolean>;
  updated_at?: number;
}

// 每个渠道需要配置的字段(明文输入,保存时 POST,后端加密落库)
const CHANNEL_FIELDS: Record<Channel, { key: string; label: string; placeholder: string; type?: string }> = {
  serverchan: { key: 'sckey', label: 'SendKey', placeholder: 'SCT...' },
  pushplus: { key: 'token', label: 'Token', placeholder: 'pushplus token' },
  feishu: { key: 'webhook', label: 'Webhook URL', placeholder: 'https://open.feishu.cn/open-apis/bot/v2/hook/...' },
  telegram: { key: 'bot_token', label: 'Bot Token', placeholder: '123456:ABC-DEF...' },
  email: { key: 'smtp_host', label: 'SMTP 主机', placeholder: 'smtp.gmail.com' },
};

const CHANNEL_LABELS: Record<Channel, string> = {
  serverchan: 'Server酱',
  pushplus: 'PushPlus',
  feishu: '飞书机器人',
  telegram: 'Telegram',
  email: '邮件 (SMTP)',
};

// email 需要多字段,单独处理
const EMAIL_FIELDS = [
  { key: 'smtp_host', label: 'SMTP 主机', placeholder: 'smtp.gmail.com' },
  { key: 'smtp_port', label: '端口', placeholder: '587 或 465' },
  { key: 'username', label: '用户名', placeholder: 'user@example.com' },
  { key: 'password', label: '密码/授权码', placeholder: '••••••', type: 'password' },
  { key: 'from_addr', label: '发件地址', placeholder: 'from@example.com' },
  { key: 'to_addr', label: '收件地址', placeholder: 'to@example.com' },
];

export function NotifierSettings() {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [drafts, setDrafts] = useState<Record<Channel, Record<string, string>>>({
    serverchan: {},
    pushplus: {},
    feishu: {},
    telegram: {},
    email: {},
  });
  const [testing, setTesting] = useState<string | null>(null);
  const [testMsg, setTestMsg] = useState<Record<string, string>>({});
  const [dispatching, setDispatching] = useState(false);
  const [dispatchMsg, setDispatchMsg] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchApi<{ channels: ChannelInfo[] }>('/api/notifiers');
      setChannels(res?.channels || []);
    } catch {
      setChannels([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveChannel = async (ch: Channel, enabled: boolean) => {
    const config = drafts[ch] || {};
    try {
      await fetchApi(`/api/notifiers/${ch}`, {
        method: 'POST',
        body: JSON.stringify({ enabled, config }),
      });
      setDrafts((prev) => ({ ...prev, [ch]: {} }));
      setTestMsg((prev) => ({ ...prev, [ch]: '已保存' }));
      await load();
    } catch (e) {
      setTestMsg((prev) => ({ ...prev, [ch]: e instanceof Error ? e.message : '保存失败' }));
    }
  };

  const testChannel = async (ch: Channel) => {
    setTesting(ch);
    setTestMsg((prev) => ({ ...prev, [ch]: '' }));
    try {
      const res = await fetchApi<{ ok: boolean; message: string }>(
        `/api/notifiers/${ch}/test`,
        { method: 'POST' },
      );
      setTestMsg((prev) => ({
        ...prev,
        [ch]: res?.ok ? '✓ 测试消息已发送' : `✗ ${res?.message || '发送失败'}`,
      }));
    } catch (e) {
      setTestMsg((prev) => ({ ...prev, [ch]: e instanceof Error ? e.message : '测试失败' }));
    } finally {
      setTesting(null);
    }
  };

  const dispatchAlerts = async () => {
    setDispatching(true);
    setDispatchMsg('');
    try {
      const res = await fetchApi<{
        results: { ok: boolean; channel?: string; message?: string }[];
        alert_count: number;
        sent?: boolean;
        reason?: string;
        all_succeeded?: boolean;
      }>('/api/notifiers/dispatch-alerts', { method: 'POST' });
      if (res?.sent === false) {
        setDispatchMsg(res.reason || '无未确认告警');
        return;
      }
      const results = res?.results || [];
      const okCount = results.filter((r) => r.ok).length;
      if (results.length === 0) {
        setDispatchMsg('没有已启用的渠道,无法推送');
        return;
      }
      // 全部成功 vs 部分失败: 后端仅全部成功才标读, 部分失败需提示用户重试
      const failed = results.filter((r) => !r.ok);
      if (failed.length === 0) {
        setDispatchMsg(`✓ 已推送 ${res?.alert_count ?? 0} 条告警到全部 ${okCount} 个渠道(已标记已读)`);
      } else {
        const failedDetail = failed
          .map((r) => `${r.channel || '?'}: ${r.message || '失败'}`)
          .join('; ');
        setDispatchMsg(
          `⚠ ${okCount}/${results.length} 个渠道成功, ${failed.length} 个失败(告警未标记已读, 可重试): ${failedDetail}`,
        );
      }
    } catch (e) {
      setDispatchMsg(`✗ ${e instanceof Error ? e.message : '推送失败'}`);
    } finally {
      setDispatching(false);
    }
  };

  const clearChannel = async (ch: Channel) => {
    if (!window.confirm(`确认清除 ${CHANNEL_LABELS[ch]} 的已存凭证?此操作不可撤销。`)) {
      return;
    }
    try {
      await fetchApi(`/api/notifiers/${ch}`, { method: 'DELETE' });
      setTestMsg((prev) => ({ ...prev, [ch]: '已清除凭证' }));
      await load();
    } catch (e) {
      setTestMsg((prev) => ({
        ...prev,
        [ch]: `✗ 清除失败: ${e instanceof Error ? e.message : '未知错误'}`,
      }));
    }
  };

  const renderFields = (ch: Channel) => {
    if (ch === 'email') {
      return EMAIL_FIELDS.map((f) => (
        <input
          key={f.key}
          type={f.type || 'text'}
          value={drafts.email[f.key] || ''}
          onChange={(e) => setDrafts((prev) => ({ ...prev, email: { ...prev.email, [f.key]: e.target.value } }))}
          placeholder={f.placeholder}
          className="h-9 w-full rounded-lg border border-white/10 bg-black/35 px-3 text-xs text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-indigo-400/50"
        />
      ));
    }
    const f = CHANNEL_FIELDS[ch];
    return (
      <input
        type="text"
        value={drafts[ch][f.key] || ''}
        onChange={(e) => setDrafts((prev) => ({ ...prev, [ch]: { ...prev[ch], [f.key]: e.target.value } }))}
        placeholder={f.placeholder}
        className="h-9 w-full rounded-lg border border-white/10 bg-black/35 px-3 text-xs text-neutral-200 outline-none placeholder:text-neutral-600 focus:border-indigo-400/50"
      />
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold text-neutral-100">
            <Bell className="h-4 w-4 text-indigo-400" />
            通知推送渠道
          </h3>
          <p className="mt-1 text-[11px] text-neutral-500">
            配置告警/简报推送渠道。凭证加密落库(AES-GCM),不回传明文。
          </p>
        </div>
        <button
          type="button"
          onClick={dispatchAlerts}
          disabled={dispatching}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/15 px-3 text-xs text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40"
          title="把当前所有未确认告警打包推送到已启用渠道"
        >
          {dispatching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          推送当前告警
        </button>
      </div>

      {dispatchMsg && (
        <p
          className={cn(
            'text-xs',
            dispatchMsg.startsWith('✓')
              ? 'text-emerald-300'
              : dispatchMsg.startsWith('⚠')
                ? 'text-amber-300'
                : dispatchMsg.startsWith('✗')
                  ? 'text-rose-400'
                  : 'text-neutral-400',
          )}
        >
          {dispatchMsg}
        </p>
      )}

      {loading ? (
        <p className="text-xs text-neutral-500">加载中…</p>
      ) : (
        (['serverchan', 'pushplus', 'feishu', 'telegram', 'email'] as Channel[]).map((ch) => {
          const info = channels.find((c) => c.channel === ch);
          const enabled = info?.enabled ?? false;
          const configured = info?.has_credentials ?? false;
          return (
            <div key={ch} className="rounded-xl border border-white/5 bg-white/[0.02] p-4">
              <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-neutral-200">{CHANNEL_LABELS[ch]}</span>
                  {configured && (
                    <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">
                      已配置
                    </span>
                  )}
                  {enabled && (
                    <span className="rounded bg-indigo-500/10 px-1.5 py-0.5 text-[10px] text-indigo-300">
                      启用中
                    </span>
                  )}
                </div>
                <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-neutral-400">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => void saveChannel(ch, e.target.checked)}
                    className="h-3.5 w-3.5 accent-indigo-500"
                  />
                  启用
                </label>
              </div>
              <div className={cn('grid gap-2', ch === 'email' ? 'sm:grid-cols-2' : 'grid-cols-1')}>
                {renderFields(ch)}
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void saveChannel(ch, enabled)}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2.5 text-[11px] text-neutral-300 hover:bg-white/[0.08]"
                >
                  <Check className="h-3.5 w-3.5" />
                  保存
                </button>
                <button
                  type="button"
                  onClick={() => void testChannel(ch)}
                  disabled={testing === ch || !configured}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-indigo-500/30 bg-indigo-500/15 px-2.5 text-[11px] text-indigo-200 hover:bg-indigo-500/25 disabled:opacity-40"
                >
                  {testing === ch ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                  测试
                </button>
                {configured && (
                  <button
                    type="button"
                    onClick={() => void clearChannel(ch)}
                    className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2.5 text-[11px] text-neutral-500 hover:bg-rose-500/10 hover:text-rose-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    清除
                  </button>
                )}
                {testMsg[ch] && (
                  <span
                    className={cn(
                      'text-[11px]',
                      testMsg[ch].startsWith('✓') || testMsg[ch].startsWith('已')
                        ? 'text-emerald-300'
                        : testMsg[ch].startsWith('✗')
                          ? 'text-rose-400'
                          : 'text-neutral-400',
                    )}
                  >
                    {testMsg[ch]}
                  </span>
                )}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}

export default NotifierSettings;
