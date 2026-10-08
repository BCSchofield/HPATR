import { atom, read, update } from 'claude-code'
import type { ElementTable, EngineInterface, Register } from 'claude-code'

import type { Segment, Snapshot } from '../types'

const PANE = 'context-bar'
const snapshot = atom({ plugin: 'context-bar', key: 'snapshot' } as const, null)
const isOn = atom({ plugin: 'context-bar', key: 'isOn' } as const, true)

// Surfaces that draw no band above the prompt get the bar in a pane instead.
const BANDLESS = new Set(['vscode', 'mobile'])

const ACCENT = '#D97757'

/** 788000 -> 788k, 3400 -> 3.4k, 1000000 -> 1M */
export function fmt(n: number): string {
  if (n >= 1e6) return `${+(n / 1e6).toFixed(1)}M`
  if (n >= 1e4) return `${Math.round(n / 1e3)}k`
  if (n >= 1e3) return `${+(n / 1e3).toFixed(1)}k`
  return String(n)
}

function pct(tokens: number, max: number): string {
  const p = (tokens / max) * 100
  return p < 1 ? `${p.toFixed(1)}%` : `${Math.round(p)}%`
}

function badgeColor(percent: number): string {
  if (percent >= 80) return '#e5534b'
  if (percent >= 50) return '#d6a243'
  return '#7fb069'
}

/**
 * Cells per segment across `width`. Every non-empty category gets at least one
 * cell so a small one still shows as a sliver; free space takes what is left.
 */
export function cells(segments: Segment[], max: number, width: number): number[] {
  const n = segments.map(s =>
    s.kind === 'free' ? 0 : Math.max(1, Math.round((s.tokens / max) * width)),
  )
  const free = segments.findIndex(s => s.kind === 'free')
  const taken = n.reduce((a, b) => a + b, 0)
  if (free >= 0) n[free] = Math.max(0, width - taken)
  let over = n.reduce((a, b) => a + b, 0) - width
  while (over > 0) {
    const big = n.indexOf(Math.max(...n))
    n[big] = (n[big] ?? 0) - 1
    over -= 1
  }
  return n
}

/** Re-reads the breakdown /context shows. `summary` is estimated locally: no API calls. */
async function measure($: EngineInterface): Promise<void> {
  try {
    const { context } = await $.session.usage({ breakdown: 'summary' })
    const b = context.breakdown
    if (!b || !b.rawMaxTokens) return
    const rank = { used: 0, free: 1, buffer: 2 } as const
    const segments: Segment[] = b.categories
      .filter(c => c.kind !== 'deferred' && c.tokens > 0)
      .map(c => ({ name: c.name.toLowerCase(), tokens: c.tokens, color: c.color,
                   kind: c.kind as Segment['kind'] }))
      .sort((x, y) => rank[x.kind] - rank[y.kind])
    const snap: Snapshot = {
      segments,
      total: b.totalTokens,
      max: b.rawMaxTokens,
      compactAt: b.isAutoCompactEnabled ? (b.autoCompactThreshold ?? null) : null,
      percent: b.percentage,
    }
    await update($, snapshot, () => snap)
  } catch {
    // No session bound yet (startup) — the next measurement fills it in.
  }
}

/** Opens the pane where the surface has no band, closes it when toggled off. */
async function syncPane($: EngineInterface): Promise<void> {
  const surfaces = await $.session.surfaces()
  const wantPane = (await read($, isOn)) && surfaces.some(s => BANDLESS.has(s))
  if (wantPane) await $.ui.open({ id: PANE, title: 'Context' })
  else await $.ui.close({ id: PANE })
}

function draw(ui: ElementTable, snap: Snapshot, columns: number, framed: boolean) {
  const { Box, Text } = ui
  // A rounded frame plus one cell of padding each side costs four columns.
  const width = Math.max(10, columns - (framed ? 4 : 0))
  const n = cells(snap.segments, snap.max, width)
  const head = `${fmt(snap.total)} of ${fmt(snap.max)}` +
    (snap.compactAt ? ` · compacts at ${fmt(snap.compactAt)}` : '')

  return (
    <Box flexDirection="column" width={columns}
         borderStyle={framed ? 'round' : undefined} borderDimColor paddingX={framed ? 1 : 0}>
      <Box flexDirection="row" justifyContent="space-between">
        <Box flexDirection="row">
          <Text color={ACCENT}>◆ </Text>
          <Text bold>context</Text>
        </Box>
        <Box flexDirection="row">
          <Text dimColor>{head} </Text>
          <Text color="#000000" backgroundColor={badgeColor(snap.percent)}>
            {` ${snap.percent}% `}
          </Text>
        </Box>
      </Box>
      <Box flexDirection="row">
        {snap.segments.map((s, i) => {
          const count = n[i] ?? 0
          return count > 0 && (
            <Text color={s.color} dimColor={s.kind !== 'used'}>
              {(s.kind === 'buffer' ? '▒' : s.kind === 'free' ? '░' : '█').repeat(count)}
            </Text>
          )
        })}
      </Box>
      <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
        {snap.segments.map(s => (
          <Box flexDirection="row">
            <Text color={s.color} dimColor={s.kind !== 'used'}>▌</Text>
            <Text> {s.name} {fmt(s.tokens)}</Text>
            {s.kind === 'used' && <Text dimColor> {pct(s.tokens, snap.max)}</Text>}
          </Box>
        ))}
      </Box>
    </Box>
  )
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'context-bar',
      description: 'Toggle the context-window bar above the prompt',
    })
    const result = await next(e)
    const stored = await $.store.get('isOn')
    await update($, isOn, () => stored !== false)
    await measure($)
    await syncPane($)
    return result
  })

  // A surface attaching later (the editor's webview) may be one with no band.
  on('session.attach', async ($, e, next) => {
    const result = await next(e)
    await syncPane($)
    return result
  })

  on('session.measure', async ($, e, next) => {
    if (e.changed.includes('context') && (await read($, isOn))) await measure($)
    return next(e)
  })

  on('command.run', { command: 'context-bar' }, async $ => {
    const nowOn = await update($, isOn, v => !v)
    await $.store.set('isOn', nowOn)
    if (nowOn) await measure($)
    await syncPane($)
    return { text: nowOn ? 'Context bar on.' : 'Context bar off.' }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || !(await read($, isOn))) return next(e)
    const snap = await read($, snapshot)
    if (!snap) return next(e)
    return draw($.ui.resolve(e), snap, e.props.bodyColumns, true)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Text } = $.ui.resolve(e)
    const snap = await read($, snapshot)
    if (!snap) return <Text dimColor>Measuring the context window…</Text>
    return draw($.ui.resolve(e), snap, e.props.bodyColumns, false)
  })
}
