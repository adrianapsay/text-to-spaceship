import { Tooltip } from 'radix-ui';
import { type ReactNode, useEffect, useState, type ButtonHTMLAttributes } from 'react';
import type { Explainer } from '../lib/copy';
import { useApp } from '../store/store';

export function Panel(props: { title: ReactNode; caption?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; id?: string; flat?: boolean }) {
  const headingId = props.id ? `${props.id}-h` : undefined;
  return (
    <section className={`${props.flat ? 'panel-flat' : 'panel'} ${props.className ?? ''}`} aria-labelledby={headingId} id={props.id}>
      <div className="panel-head">
        <h2 id={headingId}>{props.title}</h2>
        {props.caption ? <span className="caption">{props.caption}</span> : null}
        {props.right ? <div className="right">{props.right}</div> : null}
      </div>
      <div className="panel-body">{props.children}</div>
    </section>
  );
}

export type BadgeTone = 'ok' | 'warn' | 'err' | 'accent' | 'neutral' | 'mock';

export function Badge(props: { tone?: BadgeTone; children: ReactNode; title?: string; dashed?: boolean }) {
  const tone = props.tone ?? 'neutral';
  return (
    <span className={`badge ${tone === 'mock' ? 'solid-mock' : tone} ${props.dashed ? 'dashed' : ''}`} title={props.title}>
      {props.children}
    </span>
  );
}

export function MockTag(props: { what?: string }) {
  const mode = useApp((s) => s.conn.mode);
  if (mode !== 'mock') return null;
  return (
    <Badge tone="mock" title={props.what ? `MOCK: ${props.what}` : 'MOCK data — not backend output'}>
      MOCK
    </Badge>
  );
}

export function Button(props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'default'; size?: 'small' | 'normal' }) {
  const { variant, size, className, ...rest } = props;
  return <button type="button" className={`btn ${variant === 'primary' ? 'primary' : ''} ${size === 'small' ? 'small' : ''} ${className ?? ''}`} {...rest} />;
}

export function Toggle(props: { pressed: boolean; onChange: (v: boolean) => void; children: ReactNode; title?: string; disabled?: boolean; shortcut?: string }) {
  return (
    <button
      type="button"
      className="btn small"
      aria-pressed={props.pressed}
      onClick={() => props.onChange(!props.pressed)}
      title={props.title ?? (props.shortcut ? `Shortcut: ${props.shortcut}` : undefined)}
      disabled={props.disabled}
    >
      {props.children}
    </button>
  );
}

export function EmptyState(props: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <strong>{props.title}</strong>
      {props.children}
      {props.action ? <div style={{ marginTop: 8 }}>{props.action}</div> : null}
    </div>
  );
}

/** Tooltip in the fixed order: plain sentence → "Technically:" → "Why it matters". Hover and focus. */
export function InfoTip(props: { tip: Explainer; label: string; extra?: ReactNode }) {
  const expert = useApp((s) => s.view.expert);
  return (
    <Tooltip.Root delayDuration={250}>
      <Tooltip.Trigger asChild>
        <button type="button" className="info-btn" aria-label={`About ${props.label}`}>
          ?
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={4} collisionPadding={8}>
          <p>{props.tip.plain}</p>
          <p>
            <strong>Technically:</strong> {props.tip.technical}
          </p>
          <p>
            <strong>Why it matters:</strong> {props.tip.why}
          </p>
          {expert && props.extra ? <p>{props.extra}</p> : null}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export function Tip(props: { content: ReactNode; children: ReactNode }) {
  return (
    <Tooltip.Root delayDuration={300}>
      <Tooltip.Trigger asChild>{props.children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={4} collisionPadding={8}>
          {props.content}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

/** Exact numeric entry that commits on Enter / blur, with validation. */
export function NumberField(props: {
  value: number | null;
  onCommit: (v: number) => void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  decimals?: number;
  unit?: string;
  disabled?: boolean;
  width?: number;
  id?: string;
}) {
  const fmtV = (v: number | null) => (v == null || !Number.isFinite(v) ? '' : props.decimals != null ? v.toFixed(props.decimals) : String(v));
  const [text, setText] = useState(fmtV(props.value));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setText(fmtV(props.value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.value, focused]);
  const commit = () => {
    const v = Number(text.replace(',', '.').replace('−', '-'));
    if (!Number.isFinite(v) || (props.min != null && v < props.min) || (props.max != null && v > props.max)) {
      setText(fmtV(props.value));
      return;
    }
    props.onCommit(v);
  };
  return (
    <span className="row" style={{ gap: 4 }}>
      <input
        id={props.id}
        type="number"
        aria-label={props.label}
        value={text}
        min={props.min}
        max={props.max}
        step={props.step ?? 'any'}
        disabled={props.disabled}
        style={{ width: props.width ?? 90 }}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          setFocused(false);
          commit();
        }}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setText(fmtV(props.value));
        }}
      />
      {props.unit ? <span className="muted">{props.unit}</span> : null}
    </span>
  );
}

export function KV(props: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {props.rows.map(([k, v], i) => (
        <div key={i} style={{ display: 'contents' }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Notice(props: { tone?: 'warn' | 'err' | 'ok' | 'info'; children: ReactNode; role?: 'status' | 'alert' | 'note' }) {
  return (
    <div className={`notice ${props.tone ?? 'warn'}`} role={props.role}>
      {props.children}
    </div>
  );
}
