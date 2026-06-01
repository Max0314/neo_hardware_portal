/**
 * SOP 列表存储：将AI工作室中的事件流构建为 SOP 后命名并保存，默认展示在主页
 */

const SOP_LIST_KEY = 'sop_list';
const EVENT_FLOWS_KEY = 'event_flows';

/** 同页监听：localStorage 的 storage 事件不会在写入的标签页触发 */
export const SOP_LIST_CHANGED_EVENT = 'neo-sop-list-changed';

export interface SavedSOP {
  id: string;
  name: string;
  eventFlowId: string;
  eventFlowName: string;
  createdAt: string;
}

export interface EventFlowForSOP {
  id: string;
  name: string;
  steps: unknown[];
}

export function getSOPList(): SavedSOP[] {
  try {
    const raw = localStorage.getItem(SOP_LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function addSOP(sop: Omit<SavedSOP, 'id' | 'createdAt'>): SavedSOP {
  const list = getSOPList();
  const id = `sop_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  const createdAt = new Date().toISOString();
  const newSOP: SavedSOP = { ...sop, id, createdAt };
  list.unshift(newSOP);
  localStorage.setItem(SOP_LIST_KEY, JSON.stringify(list));
  window.dispatchEvent(new CustomEvent(SOP_LIST_CHANGED_EVENT));
  return newSOP;
}

export function removeSOP(id: string): boolean {
  try {
    const list = getSOPList().filter((s) => s.id !== id);
    localStorage.setItem(SOP_LIST_KEY, JSON.stringify(list));
    window.dispatchEvent(new CustomEvent(SOP_LIST_CHANGED_EVENT));
    return true;
  } catch {
    return false;
  }
}

export function getEventFlows(): EventFlowForSOP[] {
  try {
    const raw = localStorage.getItem(EVENT_FLOWS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function getSOPById(id: string): SavedSOP | undefined {
  return getSOPList().find((s) => s.id === id);
}
