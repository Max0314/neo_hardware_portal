import React, { useState, useEffect } from 'react';
import {
  SCHEMATIC_DISPOSITION_LABELS,
  type SchematicCheckDisposition,
  type SchematicCheckDispositionRecord,
  type SchematicReviewCheckItem,
  getCheckCardClassName,
  isWarningLikeStatus,
  requiresUserDisposition,
} from '@/utils/schematicReview';

interface SchematicReviewCheckCardProps {
  check: SchematicReviewCheckItem;
  dispositionRecord?: SchematicCheckDispositionRecord;
  onDispositionChange: (
    checkId: string,
    disposition: SchematicCheckDisposition,
    note?: string
  ) => void;
  compact?: boolean;
  readOnly?: boolean;
}

export const SchematicReviewCheckCard: React.FC<SchematicReviewCheckCardProps> = ({
  check,
  dispositionRecord,
  onDispositionChange,
  compact = false,
  readOnly = false,
}) => {
  const [noteDraft, setNoteDraft] = useState(dispositionRecord?.note || '');
  const [showIgnoreNote, setShowIgnoreNote] = useState(
    dispositionRecord?.disposition === 'ignored'
  );

  useEffect(() => {
    setNoteDraft(dispositionRecord?.note || '');
    setShowIgnoreNote(dispositionRecord?.disposition === 'ignored');
  }, [check.checkId, dispositionRecord?.disposition, dispositionRecord?.note]);

  const needsAction = requiresUserDisposition(check.status);
  const isRed = isWarningLikeStatus(check.status);

  const applyDisposition = (disposition: SchematicCheckDisposition) => {
    if (disposition === 'ignored') {
      setShowIgnoreNote(true);
      if (dispositionRecord?.disposition === 'ignored' && noteDraft.trim()) {
        onDispositionChange(check.checkId, 'ignored', noteDraft.trim());
      }
      return;
    }
    setShowIgnoreNote(false);
    onDispositionChange(check.checkId, disposition);
  };

  const confirmIgnore = () => {
    const note = noteDraft.trim();
    if (!note) {
      alert('选择「忽略并备注」时请填写备注说明');
      return;
    }
    onDispositionChange(check.checkId, 'ignored', note);
  };

  return (
    <div
      className={`rounded-lg border-l-4 p-2.5 ${getCheckCardClassName(check.status)} ${
        compact ? 'text-[11px]' : ''
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
            isRed
              ? 'bg-red-600 text-white'
              : check.status.toUpperCase() === 'INFO'
                ? 'bg-sky-600 text-white'
                : 'bg-green-600 text-white'
          }`}
        >
          {check.status}
        </span>
        {needsAction && dispositionRecord && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/80 border border-current/20">
            处置：{SCHEMATIC_DISPOSITION_LABELS[dispositionRecord.disposition]}
            {dispositionRecord.note ? ` · ${dispositionRecord.note}` : ''}
          </span>
        )}
        {needsAction && !dispositionRecord && (
          <span className="text-[10px] text-red-700 font-medium">待人工处置</span>
        )}
      </div>
      <div className="font-medium mt-1">{check.title}</div>
      {check.description && (
        <div className={`mt-0.5 ${isRed ? 'text-red-800/90' : 'text-gray-600'}`}>
          {check.description}
        </div>
      )}

      {needsAction && !readOnly && (
        <div
          className={`mt-2 pt-2 border-t ${
            isRed ? 'border-red-200' : 'border-sky-200'
          }`}
        >
          <div className="text-[10px] font-semibold mb-1.5 opacity-80">人工处置</div>
          <div className="flex flex-wrap gap-1.5">
            {(['pending', 'fixed', 'ignored'] as SchematicCheckDisposition[]).map((d) => {
              const active = dispositionRecord?.disposition === d;
              return (
                <button
                  key={d}
                  type="button"
                  onClick={() => applyDisposition(d)}
                  className={`px-2 py-1 rounded text-[10px] font-medium border transition ${
                    active
                      ? isRed
                        ? 'bg-red-600 text-white border-red-700'
                        : 'bg-sky-600 text-white border-sky-700'
                      : 'bg-white/90 hover:bg-white border-gray-300 text-gray-700'
                  }`}
                >
                  {SCHEMATIC_DISPOSITION_LABELS[d]}
                </button>
              );
            })}
          </div>
          {(showIgnoreNote || dispositionRecord?.disposition === 'ignored') && (
            <div className="mt-2 space-y-1">
              <textarea
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                placeholder="请填写忽略原因或备注（必填）"
                className="w-full min-h-[52px] p-2 rounded border border-gray-300 text-[11px] bg-white"
              />
              <button
                type="button"
                onClick={confirmIgnore}
                className="px-2 py-1 rounded bg-gray-800 text-white text-[10px] hover:bg-gray-900"
              >
                确认忽略并备注
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
