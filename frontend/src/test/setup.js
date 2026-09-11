/**
 * vitest 全局夹具
 *
 * jsdom 没有实现 ResizeObserver；Chart.jsx 用它来跟随容器尺寸变化。
 * 这里给一个最小实现，让图表组件能在测试里正常挂载与卸载。
 */
import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = globalThis.ResizeObserver || ResizeObserverStub

// localStorage / location 在 jsdom 下有实现，但测试间会互相污染，逐例清干净
afterEach(() => {
  cleanup()
  localStorage.clear()
  vi.restoreAllMocks()
})
