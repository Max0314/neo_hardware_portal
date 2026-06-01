import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import * as XLSX from 'xlsx';
import {
  loadReplacementGroups,
  REPLACEMENT_GROUPS_STORAGE_KEY,
  type ReplacementGroup,
  type ReplacementItem,
} from '@/utils/replacementPairsStorage';
import {
  fetchReplacementGroupsRemote,
  getReplacementUnlockToken,
  migrateReplacementGroupsRemote,
  saveReplacementGroupsRemote,
  setReplacementPairsPassword,
  unlockReplacementPairs,
} from '@/utils/replacementPairsApi';
import { fetchMaterialLibraries, extractMaterialCodesFromLibs } from '@/utils/materialDb';

function promptPassword(message: string): Promise<string | null> {
  return new Promise((resolve) => {
    const pwd = window.prompt(message);
    resolve(pwd);
  });
}

export function ReplacementPairsPage() {
  const [groups, setGroups] = useState<ReplacementGroup[]>([]);
  const [passwordConfigured, setPasswordConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [itemLines, setItemLines] = useState<{ code: string; name: string }[]>([
    { code: '', name: '' },
    { code: '', name: '' },
  ]);
  const [remarkInput, setRemarkInput] = useState('');
  const [materialCodes, setMaterialCodes] = useState<string[]>([]);
  const [codeToName, setCodeToName] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editItemLines, setEditItemLines] = useState<{ code: string; name: string }[]>([]);
  const [editRemarkInput, setEditRemarkInput] = useState('');

  const persistGroups = useCallback(async (nextGroups: ReplacementGroup[]) => {
    await saveReplacementGroupsRemote(nextGroups);
    setGroups(nextGroups);
  }, []);

  const ensureUnlocked = useCallback(async (): Promise<void> => {
    if (getReplacementUnlockToken()) return;
    if (!passwordConfigured) {
      const pwd = await promptPassword('首次使用请设置「替换对管理」访问密码（服务端仅存哈希）：');
      if (!pwd) throw new Error('cancelled');
      await setReplacementPairsPassword(pwd);
      setPasswordConfigured(true);
      await unlockReplacementPairs(pwd);
      return;
    }
    const pwd = await promptPassword('添加/编辑/删除/导入替换组需要验证管理密码：');
    if (!pwd) throw new Error('cancelled');
    await unlockReplacementPairs(pwd);
  }, [passwordConfigured]);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const remote = await fetchReplacementGroupsRemote();
      setGroups(remote.groups);
      setPasswordConfigured(remote.passwordConfigured);

      if (!remote.groups.length) {
        const local = loadReplacementGroups();
        if (local.length && window.confirm(`检测到浏览器本地有 ${local.length} 组替换对，是否迁移到服务器？迁移前需设置管理密码。`)) {
          const pwd = await promptPassword('请设置替换对管理密码：');
          if (pwd) {
            await migrateReplacementGroupsRemote(local, pwd);
            window.localStorage.removeItem(REPLACEMENT_GROUPS_STORAGE_KEY);
            const again = await fetchReplacementGroupsRemote();
            setGroups(again.groups);
            setPasswordConfigured(true);
          }
        }
      }
    } catch (e: unknown) {
      console.error(e);
      alert(`加载替换对失败：${(e as Error)?.message || String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    void (async () => {
      try {
        const libs = await fetchMaterialLibraries();
        const { codes, codeToName: codeToNameMap } = extractMaterialCodesFromLibs(libs);
        setMaterialCodes(codes);
        setCodeToName(codeToNameMap);
      } catch {
        setMaterialCodes([]);
        setCodeToName({});
      }
    })();
  }, [reload]);

  const addItemLine = () => setItemLines((prev) => [...prev, { code: '', name: '' }]);
  const setItemLine = (index: number, field: 'code' | 'name', value: string) => {
    setItemLines((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };
  const removeItemLine = (index: number) => {
    if (itemLines.length <= 1) return;
    setItemLines((prev) => prev.filter((_, i) => i !== index));
  };

  const addEditItemLine = () => setEditItemLines((prev) => [...prev, { code: '', name: '' }]);
  const setEditItemLine = (index: number, field: 'code' | 'name', value: string) => {
    setEditItemLines((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };
  const removeEditItemLine = (index: number) => {
    if (editItemLines.length <= 1) return;
    setEditItemLines((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const items = itemLines
      .map((it) => ({ code: it.code.trim(), name: it.name.trim() || undefined }))
      .filter((it) => it.code.length > 0);
    if (items.length < 2) {
      alert('请至少填写两行物料（代码必填），组内物料互为可替换关系。');
      return;
    }
    try {
      await ensureUnlocked();
      const now = new Date().toISOString();
      const newGroup: ReplacementGroup = {
        id: crypto.randomUUID?.() || String(Date.now()),
        materialItems: items,
        remark: remarkInput.trim() || undefined,
        createdAt: now,
        updatedAt: now,
      };
      await persistGroups([...groups, newGroup]);
      setItemLines([{ code: '', name: '' }, { code: '', name: '' }]);
      setRemarkInput('');
    } catch (err: unknown) {
      if ((err as Error)?.message !== 'cancelled') {
        alert(`添加失败：${(err as Error)?.message || String(err)}`);
      }
    }
  };

  const startEdit = (g: ReplacementGroup) => {
    setEditingId(g.id);
    setEditItemLines(
      g.materialItems.length
        ? g.materialItems.map((it) => ({ code: it.code, name: it.name ?? '' }))
        : [{ code: '', name: '' }, { code: '', name: '' }]
    );
    setEditRemarkInput(g.remark ?? '');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditItemLines([]);
    setEditRemarkInput('');
  };

  const saveEdit = async () => {
    if (!editingId) return;
    const items = editItemLines
      .map((it) => ({ code: it.code.trim(), name: it.name.trim() || undefined }))
      .filter((it) => it.code.length > 0);
    if (items.length < 2) {
      alert('至少保留两行物料代码。');
      return;
    }
    try {
      await ensureUnlocked();
      const next = groups.map((g) =>
        g.id === editingId
          ? {
              ...g,
              materialItems: items,
              remark: editRemarkInput.trim() || undefined,
              updatedAt: new Date().toISOString(),
            }
          : g
      );
      await persistGroups(next);
      cancelEdit();
    } catch (err: unknown) {
      if ((err as Error)?.message !== 'cancelled') {
        alert(`保存失败：${(err as Error)?.message || String(err)}`);
      }
    }
  };

  const handleRemove = async (id: string) => {
    if (!window.confirm('确定删除该替换组？')) return;
    try {
      await ensureUnlocked();
      await persistGroups(groups.filter((g) => g.id !== id));
    } catch (err: unknown) {
      if ((err as Error)?.message !== 'cancelled') {
        alert(`删除失败：${(err as Error)?.message || String(err)}`);
      }
    }
  };

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleExportExcel = () => {
    const header = ['物料代码', '物料名称', '备注'];
    const rows = groups.map((g) => [
      g.materialItems.map((it) => it.code).join('\n'),
      g.materialItems.map((it) => it.name ?? '').join('\n'),
      g.remark ?? '',
    ]);
    const aoa = [header, ...rows];
    const ws = XLSX.utils.aoa_to_sheet(aoa);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, '替换对');
    XLSX.writeFile(wb, `替换对_${new Date().toISOString().slice(0, 10)}.xlsx`);
  };

  const handleImportExcel = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (ev) => {
      try {
        const data = new Uint8Array(ev.target?.result as ArrayBuffer);
        const wb = XLSX.read(data, { type: 'array' });
        const sheet = wb.Sheets[wb.SheetNames[0]];
        const aoa = XLSX.utils.sheet_to_json<string[]>(sheet, { header: 1, defval: '' });
        if (!aoa.length) {
          e.target.value = '';
          return;
        }
        let startRow = 0;
        const first = aoa[0] || [];
        const firstCell = (first[0] != null ? String(first[0]).trim() : '').toLowerCase();
        if (firstCell === '物料代码' || firstCell === '物料名称' || firstCell === '备注' || firstCell.includes('物料')) {
          startRow = 1;
        }
        const imported: ReplacementGroup[] = [];
        const now = new Date().toISOString();
        for (let i = startRow; i < aoa.length; i++) {
          const row = aoa[i] || [];
          const codesStr = row[0] != null ? String(row[0]).trim() : '';
          const namesStr = row[1] != null ? String(row[1]).trim() : '';
          const remark = row[2] != null ? String(row[2]).trim() : '';
          const codes = codesStr.split(/\n/).map((s) => s.trim()).filter(Boolean);
          const names = namesStr.split(/\n/).map((s) => s.trim());
          const items: ReplacementItem[] = codes.map((code, idx) => ({
            code,
            name: names[idx] || undefined,
          }));
          if (items.length >= 2) {
            imported.push({
              id: crypto.randomUUID?.() || `${Date.now()}-${i}`,
              materialItems: items,
              remark: remark || undefined,
              createdAt: now,
              updatedAt: now,
            });
          }
        }
        if (!imported.length) {
          alert('未解析到有效替换组（每组至少两行物料代码）。');
          return;
        }
        await ensureUnlocked();
        await persistGroups([...groups, ...imported]);
        alert(`已导入 ${imported.length} 个替换组。`);
      } catch (err: unknown) {
        if ((err as Error)?.message !== 'cancelled') {
          alert(`导入失败：${(err as Error)?.message || String(err)}`);
        }
      }
      e.target.value = '';
    };
    reader.readAsArrayBuffer(file);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <span className="text-blue-600">替换对管理</span>
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              替换对为多物料之间的替换关系。添加、编辑、删除、导入须先验证<strong>替换对管理密码</strong>（服务端仅存哈希，参考物料库管理办法）。
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap justify-end">
            <button
              type="button"
              onClick={handleExportExcel}
              disabled={groups.length === 0}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              导出 Excel
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls"
              className="hidden"
              onChange={handleImportExcel}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-4 py-2 text-sm font-medium text-green-700 bg-white border border-green-300 rounded-lg hover:bg-green-50"
            >
              导入 Excel
            </button>
            <Link
              to="/"
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              返回 NEO
            </Link>
            <a
              href="/neo/systm_tool/物料数据库.html"
              className="px-4 py-2 text-sm font-medium text-blue-700 bg-white border border-blue-300 rounded-lg hover:bg-blue-50 no-underline"
            >
              物料数据库
            </a>
          </div>
        </div>

        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          <div className="p-4 border-b border-gray-200">
            {loading ? (
              <p className="text-sm text-gray-500">正在加载…</p>
            ) : (
              <form onSubmit={handleAdd} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-2">
                    替换组（每行一个物料：代码 + 名称，组内物料互为可替换）
                  </label>
                  <div className="space-y-2">
                    {itemLines.map((line, index) => (
                      <div key={index} className="flex items-center gap-2">
                        <input
                          type="text"
                          value={line.code}
                          onChange={(e) => setItemLine(index, 'code', e.target.value)}
                          list="material-codes-datalist"
                          placeholder="物料代码"
                          className="w-40 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        />
                        <input
                          type="text"
                          value={line.name}
                          onChange={(e) => setItemLine(index, 'name', e.target.value)}
                          placeholder="物料名称"
                          className="flex-1 min-w-0 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        />
                        <button
                          type="button"
                          onClick={() => removeItemLine(index)}
                          disabled={itemLines.length <= 1}
                          className="px-2 py-1.5 text-sm text-red-600 hover:text-red-800 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          删除
                        </button>
                      </div>
                    ))}
                  </div>
                  <button
                    type="button"
                    onClick={addItemLine}
                    className="mt-2 px-3 py-1.5 text-sm text-blue-600 hover:text-blue-800 border border-blue-300 rounded-lg"
                  >
                    添加一行
                  </button>
                  {materialCodes.length > 0 && (
                    <datalist id="material-codes-datalist">
                      {materialCodes.map((c) => (
                        <option key={c} value={c} label={codeToName[c]} />
                      ))}
                    </datalist>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">备注（可选）</label>
                  <input
                    type="text"
                    value={remarkInput}
                    onChange={(e) => setRemarkInput(e.target.value)}
                    placeholder="例如：电容 100nF 替代组"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  />
                </div>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
                >
                  添加替换组
                </button>
              </form>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase">替换组（物料代码 / 物料名称）</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-600 uppercase min-w-[200px]">备注</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-600 uppercase w-28">操作</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {!loading && groups.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-8 text-center text-gray-500 text-sm">
                      暂无替换组。请在上方添加：一组内多个物料代码互为可替换，用于 BOM 替换对检查。
                    </td>
                  </tr>
                ) : (
                  groups.map((g) => (
                    <tr key={g.id} className="hover:bg-gray-50">
                      {editingId === g.id ? (
                        <>
                          <td className="px-4 py-3 align-top">
                            <div className="space-y-1.5">
                              {editItemLines.map((line, idx) => (
                                <div key={idx} className="flex items-center gap-1">
                                  <input
                                    type="text"
                                    value={line.code}
                                    onChange={(e) => setEditItemLine(idx, 'code', e.target.value)}
                                    list="material-codes-datalist-edit"
                                    placeholder="物料代码"
                                    className="w-32 min-w-0 px-2 py-1.5 border border-gray-300 rounded text-sm"
                                  />
                                  <input
                                    type="text"
                                    value={line.name}
                                    onChange={(e) => setEditItemLine(idx, 'name', e.target.value)}
                                    placeholder="物料名称"
                                    className="flex-1 min-w-0 px-2 py-1.5 border border-gray-300 rounded text-sm"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => removeEditItemLine(idx)}
                                    disabled={editItemLines.length <= 1}
                                    className="text-red-600 hover:text-red-800 text-xs disabled:opacity-40"
                                  >
                                    删
                                  </button>
                                </div>
                              ))}
                              <button
                                type="button"
                                onClick={addEditItemLine}
                                className="text-blue-600 hover:text-blue-800 text-xs"
                              >
                                + 添加一行
                              </button>
                            </div>
                          </td>
                          <td className="px-4 py-3 align-top">
                            <input
                              type="text"
                              value={editRemarkInput}
                              onChange={(e) => setEditRemarkInput(e.target.value)}
                              placeholder="备注"
                              className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm"
                            />
                          </td>
                          <td className="px-4 py-3 text-right space-x-2 align-top">
                            <button type="button" onClick={saveEdit} className="text-blue-600 hover:text-blue-800 text-sm font-medium">
                              保存
                            </button>
                            <button type="button" onClick={cancelEdit} className="text-gray-500 hover:text-gray-700 text-sm font-medium">
                              取消
                            </button>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="px-4 py-3 text-sm text-gray-900 whitespace-pre-line">
                            {(g.materialItems ?? []).map((it) => (it.name ? `${it.code} ${it.name}` : it.code)).join('\n')}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-600">{g.remark || '—'}</td>
                          <td className="px-4 py-3 text-right space-x-2">
                            <button type="button" onClick={() => startEdit(g)} className="text-blue-600 hover:text-blue-800 text-sm font-medium">
                              编辑
                            </button>
                            <button type="button" onClick={() => handleRemove(g.id)} className="text-red-600 hover:text-red-800 text-sm font-medium">
                              删除
                            </button>
                          </td>
                        </>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
