// @vitest-environment happy-dom

import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useChartLifecycle } from './useChartLifecycle'

const mockInit = vi.fn()
const mockSetOption = vi.fn()
const mockResize = vi.fn()
const mockDispose = vi.fn()
let lastInstance: { setOption: typeof mockSetOption; resize: typeof mockResize; dispose: typeof mockDispose } | null = null

vi.mock('echarts', () => ({
  init: () => {
    const inst = { setOption: mockSetOption, resize: mockResize, dispose: mockDispose }
    lastInstance = inst
    mockInit(inst)
    return inst
  },
}))

afterEach(() => {
  mockInit.mockClear()
  mockSetOption.mockClear()
  mockResize.mockClear()
  mockDispose.mockClear()
  lastInstance = null
})

function mountProbe(optionFactory: () => Record<string, unknown>, watchSources?: () => unknown) {
  const Probe = defineComponent({
    setup() {
      const el = ref<HTMLElement | null>(null)
      const lifecycle = useChartLifecycle(el, optionFactory, watchSources)
      return () => h('div', { ref: (node) => { el.value = node as HTMLElement | null } }, [h('span')])
    },
  })
  const wrapper = mount(Probe)
  return { wrapper, element: wrapper.element as HTMLElement }
}

describe('useChartLifecycle', () => {
  it('init + sets the initial option on mount', () => {
    mountProbe(() => ({ initial: true }))
    expect(mockInit).toHaveBeenCalledTimes(1)
    expect(mockSetOption).toHaveBeenCalledTimes(1)
    expect(mockSetOption.mock.calls[0]?.[0]).toEqual({ initial: true })
  })

  it('redraws when the watch source emits', async () => {
    const watchSource = ref(0)
    const Probe = defineComponent({
      setup() {
        const el = ref<HTMLElement | null>(null)
        useChartLifecycle(el, () => ({ value: watchSource.value }), () => watchSource.value)
        return () => h('div', { ref: (node) => { el.value = node as HTMLElement | null } })
      },
    })
    const wrapper = mount(Probe)
    expect(mockSetOption).toHaveBeenCalledTimes(1)
    watchSource.value = 1
    await nextTick()
    expect(mockSetOption).toHaveBeenCalledTimes(2)
    expect(mockSetOption.mock.calls[1]?.[0]).toEqual({ value: 1 })
    wrapper.unmount()
  })

  it('disposes the echarts instance on unmount', async () => {
    const wrapper = mountProbe(() => ({}))
    expect(mockDispose).not.toHaveBeenCalled()
    wrapper.wrapper.unmount()
    await nextTick()
    expect(mockDispose).toHaveBeenCalledTimes(1)
  })

  it('resize() forwards to the echarts resize handler', () => {
    let exposed: { resize: () => void } | null = null
    const el = ref<HTMLElement | null>(null)
    const Probe = defineComponent({
      setup() {
        const lifecycle = useChartLifecycle(el, () => ({}))
        exposed = lifecycle
        return () => h('div', { ref: (node) => { el.value = node as HTMLElement | null } })
      },
    })
    const wrapper = mount(Probe)
    expect(exposed).not.toBeNull()
    exposed?.resize()
    expect(mockResize).toHaveBeenCalled()
    wrapper.unmount()
  })
})