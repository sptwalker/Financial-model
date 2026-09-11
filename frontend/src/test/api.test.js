/**
 * api.js 契约测试
 *
 * 这些函数是前端与后端的唯一接缝：URL 拼错、鉴权头漏挂、401 不回登录页，
 * 都不会被类型系统挡住（本项目是 JS，无 TS）。因此按契约逐条锁死。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import MockAdapter from 'axios-mock-adapter'

import api, {
  devLogin, getGrid, gridPeriods, listScenarios, listLogs, listArchives,
  putCells, recalc, previewRecalc, releaseVersion, unreleaseVersion,
  renameArchive, deleteArchive, updateUserRole, updateUserStatus,
  importActuals, importRebuild, fmt,
} from '../api'

let mock

beforeEach(() => {
  mock = new MockAdapter(api)
})

describe('请求拦截器', () => {
  it('有 token 时挂 Bearer 头', async () => {
    localStorage.setItem('token', 'tok-123')
    mock.onGet('/scenarios').reply((cfg) => {
      expect(cfg.headers.Authorization).toBe('Bearer tok-123')
      return [200, []]
    })
    await listScenarios()
  })

  it('无 token 时不挂 Authorization 头', async () => {
    mock.onGet('/scenarios').reply((cfg) => {
      expect(cfg.headers.Authorization).toBeUndefined()
      return [200, []]
    })
    await listScenarios()
  })
})

describe('响应拦截器', () => {
  it('401 清除本地凭据并跳登录页', async () => {
    localStorage.setItem('token', 'stale')
    localStorage.setItem('user', '{"id":1}')
    // jsdom 下赋值 location.href 会告警，用桩替换
    delete window.location
    window.location = { pathname: '/', href: '/' }
    mock.onGet('/scenarios').reply(401)

    await expect(listScenarios()).rejects.toThrow()

    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
    expect(window.location.href).toBe('/login')
  })

  it('非 401 错误不清凭据', async () => {
    localStorage.setItem('token', 'keep')
    mock.onGet('/scenarios').reply(500)
    await expect(listScenarios()).rejects.toThrow()
    expect(localStorage.getItem('token')).toBe('keep')
  })
})

describe('URL 契约', () => {
  it('getGrid 不带版本号时不拼 query', async () => {
    mock.onGet('/scenarios/7/grid').reply(200, { cells: {} })
    await getGrid(7)
    expect(mock.history.get[0].url).toBe('/scenarios/7/grid')
  })

  it('getGrid 带版本号时拼 version_no', async () => {
    mock.onGet('/scenarios/7/grid?version_no=3').reply(200, { cells: {} })
    await getGrid(7, 3)
    expect(mock.history.get[0].url).toBe('/scenarios/7/grid?version_no=3')
  })

  it('listLogs 只带上显式传入的过滤条件', async () => {
    mock.onGet(/\/users\/logs/).reply(200, [])
    await listLogs({ limit: 20, offset: 40, action: 'login' })
    const url = mock.history.get[0].url
    expect(url).toContain('limit=20')
    expect(url).toContain('offset=40')
    expect(url).toContain('action=login')
    expect(url).not.toContain('user_id')
  })

  it('listLogs 带 userId=0 时仍要拼上（0 是合法 id，不能当假值丢掉）', async () => {
    mock.onGet(/\/users\/logs/).reply(200, [])
    await listLogs({ userId: 0 })
    expect(mock.history.get[0].url).toContain('user_id=0')
  })

  it('存档接口路径正确', async () => {
    mock.onGet('/scenarios/archives').reply(200, { archives: [] })
    expect(await listArchives()).toEqual([])

    mock.onPatch('/scenarios/archives/5').reply(200, {})
    await renameArchive(5, 'Q3 定稿')

    mock.onDelete('/scenarios/archives/5').reply(200, {})
    await deleteArchive(5)
  })

  it('版本发布/撤回路径正确', async () => {
    mock.onPost('/scenarios/1/versions/2/release').reply(200, {})
    await releaseVersion(1, 2)
    mock.onPost('/scenarios/1/versions/2/unrelease').reply(200, {})
    await unreleaseVersion(1, 2)
    expect(mock.history.post.map((r) => r.url)).toEqual([
      '/scenarios/1/versions/2/release',
      '/scenarios/1/versions/2/unrelease',
    ])
  })

  it('角色/状态更新走 PATCH 且带 body', async () => {
    mock.onPatch('/users/9/role').reply((cfg) => {
      expect(JSON.parse(cfg.data)).toEqual({ role: 'admin' })
      return [200, {}]
    })
    await updateUserRole(9, 'admin')

    mock.onPatch('/users/9/status').reply((cfg) => {
      expect(JSON.parse(cfg.data)).toEqual({ status: 'disabled' })
      return [200, {}]
    })
    await updateUserStatus(9, 'disabled')
  })

  it('putCells / recalc / previewRecalc 走正确方法与路径', async () => {
    mock.onPut('/scenarios/1/cells').reply(200, {})
    await putCells(1, [{ row_key: 'qty.online', period: '2026-08', value: '5' }])

    mock.onPost('/scenarios/1/recalc').reply(200, {})
    await recalc(1)

    mock.onPost('/scenarios/1/recalc/preview').reply(200, {})
    await previewRecalc(1)
  })
})

describe('文件上传', () => {
  it('importActuals 以 multipart 提交且字段名为 file', async () => {
    mock.onPost('/forecast/actuals/import').reply((cfg) => {
      expect(cfg.data).toBeInstanceOf(FormData)
      expect(cfg.data.get('file')).toBeInstanceOf(File)
      return [200, { imported: 1 }]
    })
    await importActuals(new File(['a'], 'a.xlsx'))
  })

  it('importRebuild 同时带主表与报表两个字段', async () => {
    mock.onPost('/imports/rebuild').reply((cfg) => {
      expect(cfg.data.get('file_main_xls')).toBeInstanceOf(File)
      expect(cfg.data.get('file_report_xlsx')).toBeInstanceOf(File)
      return [200, {}]
    })
    await importRebuild({ main: new File(['a'], 'a.xls'), report: new File(['b'], 'b.xlsx') })
  })
})

describe('devLogin', () => {
  it('成功后落盘 token 与 user', async () => {
    mock.onPost('/auth/dev-login').reply(200, {
      access_token: 'tok', user: { id: 1, role: 'admin', name: '刘丹' },
    })
    const user = await devLogin()
    expect(user.role).toBe('admin')
    expect(localStorage.getItem('token')).toBe('tok')
    expect(JSON.parse(localStorage.getItem('user')).name).toBe('刘丹')
  })
})

describe('gridPeriods', () => {
  it('取各行月份并集并排序（部分行稀疏，如年度目标只有 12 月）', () => {
    const grid = {
      cells: {
        'qty.online': { '2026-09': {}, '2026-08': {} },
        'qty.annual': { '2027-12': {} },
      },
    }
    expect(gridPeriods(grid)).toEqual(['2026-08', '2026-09', '2027-12'])
  })

  it('空网格返回空数组', () => {
    expect(gridPeriods(null)).toEqual([])
    expect(gridPeriods({})).toEqual([])
    expect(gridPeriods({ cells: {} })).toEqual([])
  })
})

describe('fmt', () => {
  it('null / undefined / NaN 统一显示占位符', () => {
    expect(fmt(null)).toBe('—')
    expect(fmt(undefined)).toBe('—')
    expect(fmt(NaN)).toBe('—')
  })

  it('按位数格式化并带千分位', () => {
    expect(fmt(1234567)).toBe('1,234,567')
    expect(fmt(174.160574, 2)).toBe('174.16')
  })

  it('0 是有效值，不能被当成空值', () => {
    expect(fmt(0)).toBe('0')
  })

  it('数字字符串也能格式化（后端 Decimal 序列化为字符串）', () => {
    expect(fmt('859.8066', 2)).toBe('859.81')
  })
})
