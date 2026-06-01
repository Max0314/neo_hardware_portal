import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { trackNeoPoints } from '@/utils/neoPoints';

type CompareMode = 'full' | 'refdes' | 'coordPackage';

const FULL_FILE = 'bom对比.HTML';
const REFDES_FILE = '位号对比.html';
/** 部署用 ASCII 文件名（vite/Docker 构建时由中文源文件复制生成） */
const COORD_PACKAGE_FILE = 'coord-bom-package.html';

const MODE_META: Record<
  CompareMode,
  { label: string; icon: string; iframeTitle: string; toolDesc: string }
> = {
  full: {
    label: '全部对比',
    icon: 'fa-layer-group',
    iframeTitle: 'BOM 全部对比',
    toolDesc: 'Excel BOM 全量对比（列映射与差异报表）',
  },
  refdes: {
    label: '仅位号对比',
    icon: 'fa-hashtag',
    iframeTitle: 'BOM 位号对比',
    toolDesc: 'BOM 位号对比（简化版）',
  },
  coordPackage: {
    label: '坐标与封装',
    icon: 'fa-crosshairs',
    iframeTitle: '坐标文件与 BOM 封装对比',
    toolDesc: '坐标文件 + BOM：位号存在性、封装模糊匹配（贴片 R/C）、物料库替代组展示',
  },
};

function modeToFile(mode: CompareMode): string {
  if (mode === 'full') return FULL_FILE;
  if (mode === 'refdes') return REFDES_FILE;
  return COORD_PACKAGE_FILE;
}

function bomToolUrl(filename: string): string {
  const base = import.meta.env.BASE_URL || '/';
  return `${base}bom_tool/${encodeURIComponent(filename)}`;
}

export const BomComparePage: React.FC = () => {
  const [mode, setMode] = useState<CompareMode>('full');

  const iframeSrc = useMemo(() => bomToolUrl(modeToFile(mode)), [mode]);
  const meta = MODE_META[mode];

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.data?.type === 'neo_compare_tool_done') {
        trackNeoPoints('compare_tool');
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  return (
    <div
      className="h-screen w-screen flex flex-col overflow-hidden text-slate-800"
      style={{
        fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
        background: 'linear-gradient(165deg, #e8f2f8 0%, #f4f6fb 42%, #eef3f9 100%)',
      }}
    >
      <header className="flex-shrink-0 flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 border-b border-slate-200/80 bg-white/90 backdrop-blur-md shadow-sm">
        <div className="flex items-center gap-4 min-w-0 flex-1">
          <Link
            to="/"
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100/90 transition-colors border border-transparent hover:border-slate-200 shrink-0"
          >
            <i className="fas fa-arrow-left" aria-hidden />
            <span>返回主页</span>
          </Link>
          <div className="h-8 w-px bg-slate-200 hidden sm:block shrink-0" aria-hidden />
          <div className="min-w-0 flex-1">
            <h1 className="text-lg sm:text-xl font-semibold tracking-tight text-slate-900 truncate">
              <i className="fas fa-table-list mr-2 text-sky-700" aria-hidden />
              BOM 对比
            </h1>
            <p className="text-xs text-slate-500 truncate hidden lg:block">
              Excel 双文件：全量对比、仅位号、或坐标文件与 BOM 封装对照；本地解析
            </p>
          </div>
        </div>

        <div
          className="flex flex-wrap items-center justify-end gap-1 p-1 rounded-2xl bg-slate-100/90 border border-slate-200/80 shadow-inner shrink-0 max-w-full"
          role="group"
          aria-label="对比模式"
        >
          {(Object.keys(MODE_META) as CompareMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`px-3 py-2 rounded-xl text-sm font-semibold transition-all whitespace-nowrap ${
                mode === m
                  ? 'bg-white text-sky-800 shadow-sm border border-sky-200/80'
                  : 'text-slate-600 hover:text-slate-900 hover:bg-white/60'
              }`}
            >
              <i className={`fas ${MODE_META[m].icon} mr-1.5 opacity-80`} aria-hidden />
              {MODE_META[m].label}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 min-h-0 p-3 sm:p-4">
        <div className="h-full rounded-2xl border border-slate-200/90 bg-white/70 shadow-sm shadow-slate-200/40 overflow-hidden flex flex-col">
          <div className="flex-shrink-0 px-4 py-2 border-b border-slate-100 bg-gradient-to-r from-sky-50/60 to-white flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">
              当前工具：
            </span>
            <span className="text-xs font-semibold text-sky-900">{meta.toolDesc}</span>
          </div>
          <iframe
            key={iframeSrc}
            title={meta.iframeTitle}
            src={iframeSrc}
            className="flex-1 w-full min-h-0 border-0 bg-white"
            sandbox="allow-scripts allow-same-origin allow-downloads allow-modals allow-popups allow-popups-to-escape-sandbox allow-forms"
          />
        </div>
      </div>
    </div>
  );
};
