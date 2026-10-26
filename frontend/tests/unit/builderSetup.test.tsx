import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import type { BuilderView, QuestionView } from '../../src/builder/types';
import { defaultText, Findings, QuestionCard, RequirementsPanel, SOURCE_TEXT } from '../../src/builder/MissionSetup';

const question = (over: Partial<QuestionView>): QuestionView => ({
  id: 'mission.type',
  section: 'mission',
  prompt: 'What is the primary purpose of the satellite?',
  help: 'Everything else follows from this.',
  kind: 'choice',
  key: 'mission.type',
  unit: null,
  min: null,
  max: null,
  advanced: false,
  options: [
    { value: 'earth_observation', label: 'Earth observation', explain: 'Take pictures of the Earth.' },
    { value: 'science', label: 'Science', explain: '' },
  ],
  default: 'science',
  default_why: 'A default for the test.',
  answer: null,
  ...over,
});

describe('V3 Builder: Mission Setup', () => {
  it('says in words what "I don\'t know" will take', () => {
    expect(defaultText(question({}))).toBe('Science');
    expect(defaultText(question({ kind: 'number', unit: 'm', default: 10 }))).toBe('10 m');
    expect(defaultText(question({ kind: 'bool', default: false }))).toBe('No');
    expect(defaultText(question({ kind: 'multi', default: ['science', 'earth_observation'] }))).toBe('Science, Earth observation');
    expect(defaultText(question({ default: null }))).toBe('no value (decided later)');
  });

  it('a choice answers with its value; "I don\'t know" asks for the default; the reason is one click away', () => {
    const onAnswer = vi.fn();
    const onUnknown = vi.fn();
    const { getByTestId, getByText } = render(<QuestionCard q={question({})} busy={false} onAnswer={onAnswer} onUnknown={onUnknown} />);
    fireEvent.click(getByTestId('opt-earth_observation'));
    expect(onAnswer).toHaveBeenCalledWith('earth_observation');
    fireEvent.click(getByTestId('dont-know'));
    expect(onUnknown).toHaveBeenCalledTimes(1);
    expect(getByText('Why this matters')).toBeTruthy();
    expect(getByText(/A default for the test\./)).toBeTruthy();
  });

  it('a multiple choice sends the boxes ticked; a number sends its preset', () => {
    const onAnswer = vi.fn();
    const multi = question({ id: 'imaging.bands', kind: 'multi', default: ['science'] });
    const { getByTestId, unmount } = render(<QuestionCard q={multi} busy={false} onAnswer={onAnswer} onUnknown={() => undefined} />);
    fireEvent.click(getByTestId('check-earth_observation'));
    fireEvent.click(getByTestId('multi-continue'));
    expect(onAnswer).toHaveBeenLastCalledWith(['science', 'earth_observation']);
    unmount();
    const num = question({ id: 'imaging.gsd_m', kind: 'number', unit: 'm', default: 10, options: [{ value: 3, label: 'About 3 m', explain: '' }] });
    const r = render(<QuestionCard q={num} busy={false} onAnswer={onAnswer} onUnknown={() => undefined} />);
    fireEvent.click(r.getByTestId('opt-3'));
    expect(onAnswer).toHaveBeenLastCalledWith(3);
  });

  it('the requirements say where each value came from and can be changed', () => {
    const view: BuilderView = {
      next: null,
      pending: [],
      completeness: { answered: 2, total: 4, complete: false },
      sections: { mission: 'Mission', payload: 'Payload' },
      requirements: [
        { key: 'mission.type', qid: 'mission.type', section: 'mission', prompt: 'Purpose', value: 'earth_observation', unit: null, source: 'statement', note: '', answer_why: 'from the words: photograph', display: 'Earth observation' },
        { key: 'imaging.gsd_m', qid: 'imaging.gsd_m', section: 'payload', prompt: 'Pixel size', value: 10, unit: 'm', source: 'default', note: '10 m suits land imaging (ASSUMED)', display: '10 m' },
      ],
    };
    const onEdit = vi.fn();
    const { getByText, getByTestId, getByRole } = render(<RequirementsPanel view={view} busy={false} onEdit={onEdit} />);
    expect(getByText(SOURCE_TEXT.statement)).toBeTruthy();
    expect(getByText(SOURCE_TEXT.default)).toBeTruthy();
    expect(getByText('10 m suits land imaging (ASSUMED)')).toBeTruthy();
    expect(getByRole('progressbar', { name: 'Questions answered' }).getAttribute('aria-valuenow')).toBe('2');
    fireEvent.click(getByTestId('edit-imaging.gsd_m'));
    expect(onEdit).toHaveBeenCalledWith('imaging.gsd_m');
  });

  it('shows what was read from the description', () => {
    const { getByTestId } = render(<Findings statement="I want to photograph California." findings={[{ qid: 'target.region', value: 'california', why: 'you named California' }]} />);
    expect(getByTestId('statement').textContent).toContain('you named California');
    expect(render(<Findings statement="" findings={[]} />).container.textContent).toBe('');
  });
});
