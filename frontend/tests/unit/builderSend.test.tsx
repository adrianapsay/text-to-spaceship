import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { WsClient } from '../../src/api/ws';
import type { SocketLike, Transport } from '../../src/api/transport';
import type { Analysis, Pick, ProjectInfo, SentRecord } from '../../src/builder/analysisTypes';
import { SendSection } from '../../src/builder/SendView';

function fakeTransport() {
  const sockets: SocketLike[] = [];
  const transport = {
    openSocket: () => {
      const s = { readyState: 0, send: vi.fn(), close: vi.fn(), onopen: null, onmessage: null, onerror: null, onclose: null } as unknown as SocketLike;
      sockets.push(s);
      return s;
    },
  } as unknown as Transport;
  return { transport, sockets };
}

describe('V3: the page follows a project switch', () => {
  it('a close with 4001 reloads instead of reconnecting; other closes reconnect', () => {
    vi.useFakeTimers();
    const { transport, sockets } = fakeTransport();
    const states: string[] = [];
    const switched = vi.fn();
    const ws = new WsClient({
      transport,
      onEnvelope: () => undefined,
      onState: (s) => states.push(s),
      onNewConnection: () => undefined,
      getContext: () => ({ epoch: null, revs: { epoch: 0, parts_rev: 0, constraint_rev: 0, mass_rev: 0, weights_rev: 0 }, appliedClientSeq: 0 }),
      wantCandidates: () => false,
      onProjectSwitched: switched,
    });
    ws.connect();
    sockets[0].onclose?.({ code: 1006 });
    expect(states).toContain('reconnecting');
    vi.advanceTimersByTime(300);
    expect(sockets).toHaveLength(2);
    sockets[1].onclose?.({ code: 4001, reason: 'project switched' });
    expect(switched).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(10_000);
    expect(sockets).toHaveLength(2);                              // no reconnect onto the old project's state
    vi.useRealTimers();
  });
});

const item = (id: string, name: string, qty = 1) => ({
  id, name, qty, category: 'x', mass_kg: 0.5, dims_mm: [90, 90, 10], power_w: { typical: null }, price: { value: null, currency: null, kind: 'quote', note: '' }, cad: 'unknown',
});
const pick = (slot: string, place: Pick['place'], items: ReturnType<typeof item>[]): Pick => ({ slot, label: slot, items, status: 'recommended', why: '', need: '', alternatives: [], flags: [], place });

function analysis(size = 6): Analysis {
  return {
    size_u: size, size_label: `${size}U`,
    slots: [{ id: 'obc', label: 'Computer', place: 'internal' }, { id: 'solar', label: 'Solar panels', place: 'external' }],
    picks: { obc: pick('obc', 'internal', [item('kryten', 'KRYTEN-M3')]), solar: pick('solar', 'external', [item('photon', 'PHOTON-SIDE', 5)]) },
    checks: [{ rule: 'packing_model', status: 'assumptions', status_text: 'Compatible with assumptions or modifications', title: 'Camera: optimiser packing model', detail: 'Stage 1 only', items: [], fix: '', source: '' }],
    geometry: { kryten: { origin: 'manufacturer', origin_text: 'Manufacturer CAD', ok: true, extents_mm: [95.89, 90.17, 5.51] } },
  } as unknown as Analysis;
}

const sent: SentRecord = {
  design_id: 'D-20261026-abcdef', design_name: 'California imager', design_version: 7, sent_at: '2026-10-26T01:00:00', size: '6U',
  parts: [], not_packed: [], warnings: ['Camera: Stage 1 only'], unenforced: ['External hardware is not packed'],
};

describe('V3 Builder: Send to Optimization', () => {
  it('shows what is packed and what is not, sends, and switches projects', () => {
    const onSend = vi.fn();
    const onSwitch = vi.fn();
    const projects: { projects: ProjectInfo[]; current: string } = {
      current: 'builder-california-imager',
      projects: [
        { name: 'default', parts: 19, form_factor: '3U', current: false, modified: 0, builder: null },
        { name: 'builder-california-imager', parts: 12, form_factor: '6U', current: true, modified: 0, builder: sent },
      ],
    };
    const { getByTestId, getByText } = render(
      <SendSection a={analysis()} stale={false} busy={false} projects={projects} sentBy={[]} onSend={onSend} onSwitch={onSwitch} />,
    );
    expect(getByText('Manufacturer CAD')).toBeTruthy();
    expect(getByTestId('send').textContent).toContain('PHOTON-SIDE ×5');
    fireEvent.click(getByTestId('send-button'));
    expect(onSend).toHaveBeenCalledTimes(1);
    fireEvent.click(getByTestId('switch-default'));
    expect(onSwitch).toHaveBeenCalledWith('default');
    expect(getByTestId('sent-details').textContent).toContain('External hardware is not packed');
  });

  it('refuses sizes the optimiser does not pack, and waits for a current analysis', () => {
    const r1 = render(<SendSection a={analysis(2)} stale={false} busy={false} projects={null} sentBy={[]} onSend={() => undefined} onSwitch={() => undefined} />);
    expect((r1.getByTestId('send-button') as HTMLButtonElement).disabled).toBe(true);
    expect(r1.getByTestId('send').textContent).toContain('packs 3U, 6U and 12U');
    r1.unmount();
    const r2 = render(<SendSection a={analysis(6)} stale busy={false} projects={null} sentBy={[]} onSend={() => undefined} onSwitch={() => undefined} />);
    expect((r2.getByTestId('send-button') as HTMLButtonElement).disabled).toBe(true);
  });
});
