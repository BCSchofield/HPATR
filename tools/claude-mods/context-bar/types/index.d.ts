/** One coloured run of the bar: a /context category, the free space or the compaction buffer. */
export type Segment = {
  name: string
  tokens: number
  color: string
  kind: 'used' | 'free' | 'buffer'
}

/** The window as last measured, in the order the bar draws it. */
export type Snapshot = {
  segments: Segment[]
  total: number
  max: number
  compactAt: number | null
  percent: number
}

declare module 'claude-code' {
  interface PluginState {
    'context-bar': { snapshot: Snapshot | null; isOn: boolean }
  }
}
