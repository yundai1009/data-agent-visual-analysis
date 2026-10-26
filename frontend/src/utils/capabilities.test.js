/* 阶段七十四 · C：产品模式（基础版 / 专业版）能力表单测。
 *
 * 这些断言锁的不是"功能有没有"，而是**规则本身**：
 *   1. 默认模式不能静默改变现有界面（否则老用户一升级就发现功能没了）；
 *   2. 基础版对 0 基础用户收起模型选择/模板/定时等术语，但对比分析入口保留（阶段七十六按用户要求加回侧栏）；
 *   3. 管理后台是权限门槛，不能跟着模式一起被过滤掉；
 *   4. 能力表里没写的能力一律不给（防止"以为有其实没有"）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  模式, 默认模式, 能力表, 取模式, 设模式, 有能力, 过滤侧栏项,
} from './capabilities';

const 全部项 = [
  { to: '/data', label: '数据管理' },
  { to: '/analysis', label: '智能分析' },
  { to: '/compare', label: '对比分析' },
  { to: '/report', label: '报表历史' },
  { to: '/dashboard', label: '图表看板' },
  { to: '/account', label: '账号设置' },
];

describe('capabilities 产品模式能力表（阶段七十四 C）', () => {
  beforeEach(() => {
    localStorage.clear();
    // 每个用例都以干净的 URL 开始：?mode= 的优先级高于 localStorage，
    // 不清掉会串味。
    window.history.replaceState({}, '', '/');
  });

  afterEach(() => {
    window.history.replaceState({}, '', '/');
  });

  it('默认是基础版：新用户第一眼只有上传 → 分析 → 看报表三步', () => {
    expect(默认模式).toBe(模式.基础版);
    expect(取模式()).toBe(模式.基础版);
    // 基础版保留对比能力本身，只是侧栏那个术语入口收起来
    expect(有能力('对比分析入口')).toBe(true);
    expect(有能力('模型选择')).toBe(false);
  });

  it('URL ?mode=pro 打开专业版，优先于 localStorage', () => {
    设模式(模式.基础版);
    window.history.replaceState({}, '', '/?mode=pro');
    expect(取模式()).toBe(模式.专业版);
  });

  it('URL 参数非法时回落 localStorage，再回落默认值', () => {
    window.history.replaceState({}, '', '/?mode=鬼知道');
    expect(取模式()).toBe(默认模式);
    设模式(模式.基础版);
    window.history.replaceState({}, '', '/?mode=鬼知道');
    expect(取模式()).toBe(模式.基础版);
  });

  it('设模式拒绝非法值，不写脏数据进 localStorage', () => {
    expect(设模式('basic')).toBe(true);
    expect(localStorage.getItem('daa_mode')).toBe('basic');
    expect(设模式('乱写')).toBe(false);
    expect(localStorage.getItem('daa_mode')).toBe('basic');
  });

  it('基础版侧栏六项全在，含对比分析（阶段七十六按用户要求加回）', () => {
    const 基础 = 过滤侧栏项(全部项, 模式.基础版).map((i) => i.to);
    expect(基础).toEqual(['/data', '/analysis', '/compare', '/report', '/dashboard', '/account']);
  });

  it('专业版侧栏六项全在（含对比分析）', () => {
    const 专业 = 过滤侧栏项(全部项, 模式.专业版).map((i) => i.to);
    expect(专业).toEqual(['/data', '/analysis', '/compare', '/report', '/dashboard', '/account']);
  });

  it('基础版关掉模型选择/模板/定时，但**不关**对比能力本身', () => {
    // 阶段七十六：入口已加回侧栏，同时数据管理页的「对比这几份」保留，两条路并存。
    expect(有能力('模型选择', 模式.基础版)).toBe(false);
    expect(有能力('模板', 模式.基础版)).toBe(false);
    expect(有能力('定时任务', 模式.基础版)).toBe(false);
    expect(有能力('对比分析入口', 模式.基础版)).toBe(true);
  });

  it('能力表里没写的能力一律返回 false（防止"以为有其实没有"）', () => {
    expect(有能力('时光机')).toBe(false);
  });
});
