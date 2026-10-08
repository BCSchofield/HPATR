import type { ContextCategory, On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'

import type { Segment } from '../types'
import { cells, fmt } from '../hooks/register'

const row = (name: string, tokens: number, kind: ContextCategory['kind'],
             color = 'promptBorder'): ContextCategory =>
  ({ name, tokens, color, kind, isDeferred: kind === 'deferred' })

// What /context would report: 212k of a 1M window, compaction at 950k.
const CATEGORIES = [
  row('System prompt', 3_400, 'used'),
  row('System tools', 12_000, 'used', 'inactive'),
  row('Messages', 186_000, 'used', 'permission'),
  row('MCP tools (deferred)', 9_000, 'deferred'),
  row('Free space', 748_600, 'free'),
  row('Autocompact buffer', 50_000, 'buffer', 'inactive'),
]

const BAND_PROPS = {
  hasSurvey: false, isWorking: false, maxRows: 20, bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 20 }, view: {},
}

/** Stands in for the engine: the breakdown, the surfaces, panes, the store. */
function engine(on: On, surfaces: ('terminal' | 'vscode')[] = ['terminal']) {
  mock.store(on)
  on('session.usage', () => ({
    value: {
      startedAt: 0, rateLimits: [],
      context: {
        window: 1_000_000, tokens: 212_000, percent: 21,
        breakdown: {
          categories: CATEGORIES, totalTokens: 212_000, maxTokens: 1_000_000,
          rawMaxTokens: 1_000_000, autocompactSource: 'model-default', percentage: 21,
          gridRows: [], model: 'test', memoryFiles: [], mcpTools: [], agents: [],
          autoCompactThreshold: 950_000, isAutoCompactEnabled: true, apiUsage: null,
        },
      },
    },
  }))
  on('session.surfaces', () => ({ value: surfaces }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('ui.close', () => ({ value: undefined }))
  on('session.measure', (_$, e) => ({ changed: e.changed }))
}

const measured = ($: any) =>
  $.session.measure({ context: { window: 1_000_000 }, rateLimits: [], changed: ['context'] })

test('token counts read like /context', () => {
  expect(fmt(1_000_000)).toBe('1M')
  expect(fmt(950_000)).toBe('950k')
  expect(fmt(3_400)).toBe('3.4k')
  expect(fmt(812)).toBe('812')
})

test('the bar fills its width exactly, small categories still visible', () => {
  const segs: Segment[] = [
    { name: 'a', tokens: 100, color: 'x', kind: 'used' },
    { name: 'b', tokens: 600_000, color: 'x', kind: 'used' },
    { name: 'free', tokens: 399_900, color: 'x', kind: 'free' },
  ]
  const n = cells(segs, 1_000_000, 76)
  expect(n.reduce((a, b) => a + b, 0)).toBe(76)
  expect(n[0]).toBe(1)
})

test('band shows the header, bar and legend on terminal and desktop', async ($, on) => {
  engine(on)
  await measured($)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'context-bar', surface, component: 'AbovePrompt', props: BAND_PROPS,
    })
    expect(await ui.find({ type: 'Text', text: 'context' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '212k of 1M · compacts at 950k' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '21%' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'messages 186k' })).toBeDefined()
    // Deferred tool schemas sit outside the window, as on /context's grid.
    expect(await ui.find({ type: 'Text', text: /deferred/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('the pane draws the same bar in the VS Code / Cursor extension', async ($, on) => {
  engine(on, ['vscode'])
  await measured($)
  const ui = await $.ui.mount({
    plugin: 'context-bar', surface: 'vscode', component: 'Pane', requestId: 'context-bar',
    props: { title: 'Context', isFocused: false, bodyColumns: 60, placement: 'inline',
             scroll: { offset: 0, bodyRows: 10 }, view: {} },
  })
  expect(await ui.find({ type: 'Text', text: '21%' })).toBeDefined()
  await ui.unmount()
})

test('/context-bar toggles the band off, leaving whatever sits beneath', async ($, on) => {
  engine(on)
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine band</Text>
  })
  await measured($)
  const r = await $.command.run({
    command: 'context-bar', args: '', origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 80 },
  })
  expect(r.text).toBe('Context bar off.')
  const ui = await $.ui.mount({
    plugin: 'context-bar', surface: 'terminal', component: 'AbovePrompt', props: BAND_PROPS,
  })
  expect(await ui.find({ type: 'Text', text: 'engine band' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: '21%' })).toBeUndefined()
  await ui.unmount()
})
