"use client";
import React, { useState } from 'react';
import { Plus, Trash2, ChevronDown, X } from 'lucide-react';
import { ExpressionEngine } from './ExpressionEngine';
import { ExpressionModal } from './ExpressionModal';

const DEFAULT_OPERATIONS_SCHEMA = [
  { name: "replace", args: ["search", "replacement"] },
  { name: "trim", args: [] },
  { name: "upper", args: [] },
  { name: "append", args: ["text"] },
  { name: "slice", args: ["start", "end"] }
];

const ConditionEditor = ({ conditions = [], handleConfigChange, OPERATIONS_SCHEMA = DEFAULT_OPERATIONS_SCHEMA }) => {
  const [collapsedConditions, setCollapsedConditions] = useState({});
  const [modalTarget, setModalTarget] = useState(null);

  const getCondType = (cond) => {
    if (!cond || typeof cond !== 'object') return 'if';
    if (cond.hasOwnProperty('if')) return 'if';
    if (cond.hasOwnProperty('elif')) return 'elif';
    if (cond.hasOwnProperty('else')) return 'else';
    return 'if';
  };

  const updateCondition = (index, key, value) => {
    const newConditions = [...conditions];
    newConditions[index] = { ...newConditions[index], [key]: value };
    handleConfigChange('condition', newConditions);
  };

  const addCondition = () => handleConfigChange('condition', [...conditions, { if: '', operations: [] }]);
  
  return (
    <div className="flex-1 flex flex-col p-6 overflow-hidden bg-surface">
      <ExpressionModal isOpen={!!modalTarget} onClose={() => setModalTarget(null)} operationsSchema={OPERATIONS_SCHEMA} onSave={(val) => modalTarget.onChange(val)} />
      
      <div className="flex items-center gap-6 mb-6">
        <label className="text-xs font-bold uppercase tracking-wider text-pipeline-accent">Node Conditions</label>
        <button onClick={addCondition} className="text-xs font-bold uppercase text-pipeline-selected hover:underline"><Plus size={14} /> Add Rule</button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-5">
        {conditions.map((cond, idx) => {
          const type = getCondType(cond);
          return (
            <div key={idx} className="border border-border p-4 rounded-lg bg-field-input">
              <input value={cond[type] || ''} onChange={(e) => updateCondition(idx, type, e.target.value)} className="w-full p-2 bg-surface border border-border rounded mb-2 font-mono text-xs" />
              <button onClick={() => setModalTarget({ onChange: (val) => updateCondition(idx, type, val) })} className="text-[10px] uppercase text-pipeline-selected font-bold">+ Pipe Function</button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default ConditionEditor;