"use client";
import React, { useState } from 'react';
import { Plus, Trash2, ChevronDown, X, ArrowLeftRight, GitBranch } from 'lucide-react';
import ExpressionEngine from './ExpressionEngine';
import ExpressionModal from './ExpressionModal';

const DEFAULT_OPERATIONS_SCHEMA = [
  { name: "int", args: ["value"] },
  { name: "bool", args: ["value"] },
  { name: "float", args: ["value"] },
  { name: "upper", args: ["value"] },
  { name: "lower", args: ["value"] },
  { name: "capitalize", args: ["value"] },
  { name: "trim", args: ["value"] },
  { name: "length", args: ["value"] },
  { name: "split", args: ["value", "map_to", "delimiter"] },
  { name: "replace", args: ["value", "search", "replacement"] },
  { name: "substring", args: ["value", "start", "end"] },
  { name: "contains", args: ["value", "search"] },
  { name: "sum", args: ["arg1", "arg2"] },
  { name: "round", args: ["value", "precision"] },
  { name: "ceil", args: ["value"] },
  { name: "floor", args: ["value"] },
  { name: "toInt", args: ["value"] },
  { name: "first", args: ["value"] },
  { name: "last", args: ["value"] },
  { name: "join", args: ["value", "separator"] },
  { name: "flatten", args: ["value"] },
  { name: "now", args: [] },
  { name: "formatDate", args: ["value", "format_str"] },
  { name: "addDays", args: ["value", "days"] }
];

const ConditionEditor = ({
  conditions = [],
  handleConfigChange,
  OPERATIONS_SCHEMA = DEFAULT_OPERATIONS_SCHEMA,
  SAMPLE_PAYLOAD = {},
  OPERATORS = []
}) => {
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
    const oldCond = newConditions[index];
    const type = getCondType(oldCond);
    if (key === 'type') {
      const operations = type === 'else' ? (oldCond.else?.operations || []) : (oldCond.operations || []);
      const currentVal = oldCond.if || oldCond.elif || "";
      const newCond = {};
      if (value === 'if') { newCond.if = currentVal; newCond.operations = operations; }
      else if (value === 'elif') { newCond.elif = currentVal; newCond.operations = operations; }
      else if (value === 'else') { newCond.else = { operations: operations }; }
      newConditions[index] = newCond;
    } else {
      newConditions[index] = { ...oldCond, [key]: value };
    }
    handleConfigChange('condition', newConditions);
  };

  const updateOperation = (condIdx, opIdx, key, value) => {
    const newConditions = [...conditions];
    const cond = newConditions[condIdx];
    const type = getCondType(cond);
    if (type === 'else') newConditions[condIdx].else.operations[opIdx] = { ...newConditions[condIdx].else.operations[opIdx], [key]: value };
    else newConditions[condIdx].operations[opIdx] = { ...newConditions[condIdx].operations[opIdx], [key]: value };
    handleConfigChange('condition', newConditions);
  };

  const addCondition = () => handleConfigChange('condition', [...conditions, { if: '', operations: [] }]);
  const removeCondition = (index) => handleConfigChange('condition', conditions.filter((_, i) => i !== index));
  
  const addOperation = (condIdx) => {
    const newConditions = [...conditions];
    const cond = newConditions[condIdx];
    const type = getCondType(cond);
    const initialAction = (OPERATIONS_SCHEMA && OPERATIONS_SCHEMA.length > 0) ? OPERATIONS_SCHEMA[0].name : 'execute';
    if (type === 'else') {
      const ops = cond.else?.operations || [];
      newConditions[condIdx].else.operations = [...ops, { action: initialAction }];
    } else {
      const ops = cond.operations || [];
      newConditions[condIdx].operations = [...ops, { action: initialAction }];
    }
    handleConfigChange('condition', newConditions);
  };

  const removeOperation = (condIdx, opIdx) => {
    const newConditions = [...conditions];
    const cond = newConditions[condIdx];
    const type = getCondType(cond);
    if (type === 'else') {
      newConditions[condIdx].else.operations = cond.else.operations.filter((_, i) => i !== opIdx);
    } else {
      newConditions[condIdx].operations = cond.operations.filter((_, i) => i !== opIdx);
    }
    handleConfigChange('condition', newConditions);
  };

  const DisplayBar = ({ value, onChange }) => {
    const rawMatches = value ? value.match(/\{\{.*?\}\}/g) || [] : [];
    const expressions = rawMatches.map(m => m.replace(/^\{\{|\}\}$/g, ''));
    
    const removeExpression = (e, idxToRemove) => {
      e.stopPropagation();
      const all = value.match(/\{\{.*?\}\}/g) || [];
      const updated = all.filter((_, i) => i !== idxToRemove).join(' ');
      onChange(updated);
    };

    return (
      <div className="flex items-center gap-2 border border-border bg-field-input rounded-md px-3 py-2 w-full min-h-[40px]">
        <button title="Add Expression" onClick={() => setModalTarget({ onChange, currentValue: value })} className="shrink-0 text-pipeline-selected hover:bg-border p-1 rounded"><Plus size={16}/></button>
        <div className="relative flex-1 min-w-0 flex items-center">
          <div className="absolute -left-2 z-10 text-muted/50"><ArrowLeftRight size={12} /></div>
          <div className="flex gap-2 text-xs font-mono overflow-x-auto whitespace-nowrap flex-nowrap scrollbar-hide py-1 px-2 w-full">
            {expressions.length > 0 ? expressions.map((expr, i) => (
              <button 
                key={i} 
                onClick={() => setModalTarget({ onChange, currentValue: value, editIndex: i, initialSource: expr })}
                className="group relative bg-black text-white px-2 py-1 rounded flex items-center gap-2 hover:bg-black/80 transition-colors shrink-0"
              >
                <span>{expr.replace(/^\$/, '')}</span>
                <div 
                  onClick={(e) => removeExpression(e, i)} 
                  className="hidden group-hover:flex items-center justify-center w-4 h-4 rounded-full bg-red-600 text-white hover:bg-red-700 border-none shrink-0"
                >
                  <X size={10} />
                </div>
              </button>
            )) : <span className="text-muted italic px-2">No expressions added</span>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex-1 flex flex-col p-6 overflow-hidden bg-surface">
      <ExpressionModal 
        isOpen={!!modalTarget} 
        onClose={() => setModalTarget(null)} 
        operationsSchema={OPERATIONS_SCHEMA} 
        SAMPLE_PAYLOAD={SAMPLE_PAYLOAD}
        initialSource={modalTarget?.initialSource}
        onSave={(val) => {
            const rawVal = val.replace(/^\{\{|\}\}$/g, '');
            if (modalTarget.editIndex !== undefined) {
                const all = modalTarget.currentValue.match(/\{\{.*?\}\}/g) || [];
                all[modalTarget.editIndex] = `{{${rawVal}}}`;
                modalTarget.onChange(all.join(' '));
            } else {
                modalTarget.onChange((modalTarget.currentValue || '') + (modalTarget.currentValue ? ' ' : '') + `{{${rawVal}}}`);
            }
        }} 
      />
      
      <div className="flex items-center gap-6 mb-6">
        <label className="text-xs font-bold uppercase tracking-wider text-pipeline-accent shrink-0">Node Conditions</label>
        <button onClick={addCondition} className="flex items-center gap-1.5 text-xs font-bold uppercase text-pipeline-selected hover:underline shrink-0"><Plus size={14} /> Add Rule</button>
      </div>

      <div className="flex-1 overflow-y-auto space-y-5 pr-2">
        {conditions.length === 0 ? (
           <div className="flex-1 flex flex-col items-center justify-center p-12 border-2 border-dashed border-border rounded-xl bg-field-input/50 h-full">
              <GitBranch size={40} className="text-muted mb-4 opacity-50" />
              <p className="text-sm font-bold text-pipeline-text-heading mb-1">No conditional rules defined</p>
              <p className="text-xs text-muted mb-6 max-w-[250px] text-center">
                 Rules determine how your workflow behaves. Click "Add Rule" to configure your first condition.
              </p>
              <button 
                onClick={addCondition} 
                className="px-4 py-2 flex items-center gap-2 text-xs font-bold uppercase text-white bg-pipeline-selected rounded-lg hover:opacity-90 transition-opacity"
              >
                <Plus size={14} /> Add Rule
              </button>
           </div>
        ) : (
          conditions.map((cond, idx) => {
            const type = getCondType(cond);
            const ops = type === 'else' ? (cond.else?.operations || []) : (cond.operations || []);
            const hasIfAbove = conditions.slice(0, idx).some(c => getCondType(c) === 'if');
            const hasElseAbove = conditions.slice(0, idx).some(c => getCondType(c) === 'else');
            
            return (
              <div key={idx} className="border border-border p-5 rounded-lg bg-field-input shadow-sm">
                <div className="flex items-center gap-3 mb-4">
                  <select 
                    value={type} 
                    onChange={(e) => updateCondition(idx, 'type', e.target.value)} 
                    className="bg-surface border border-border text-xs rounded-md px-3 py-2 font-bold uppercase cursor-pointer"
                  >
                    <option value="if">IF</option>
                    {hasIfAbove && !hasElseAbove && <option value="elif">ELIF</option>}
                    {hasIfAbove && !hasElseAbove && <option value="else">ELSE</option>}
                  </select>
                  {type !== 'else' && (
                    <div className="flex-1 flex gap-2 min-w-0">
                      <div className="flex-1 min-w-0">
                        <DisplayBar value={cond[type] || ''} onChange={(val) => updateCondition(idx, type, val)} />
                      </div>
                      <select 
                        onChange={(e) => updateCondition(idx, type, `${cond[type] || ''} ${e.target.value}`.trim())}
                        className="bg-surface border border-border text-xs rounded-md px-2 font-bold uppercase cursor-pointer shrink-0 w-24"
                      >
                        <option value="">Operator</option>
                        {OPERATORS?.map(op => <option key={op.value} value={op.value}>{op.label}</option>)}
                      </select>
                    </div>
                  )}
                  <button onClick={() => removeCondition(idx)} className="text-muted hover:text-red-500 shrink-0"><Trash2 size={16} /></button>
                </div>

                <div className="mt-4">
                  <div className="flex items-center justify-between">
                    <button onClick={() => setCollapsedConditions(prev => ({ ...prev, [idx]: !prev[idx] }))} className="flex items-center gap-2 text-xs font-bold uppercase text-muted tracking-wide">
                      Operations ({ops.length}) <ChevronDown size={14} />
                    </button>
                    {!collapsedConditions[idx] && (
                      <button onClick={() => addOperation(idx)} className="flex items-center gap-1 text-[10px] font-bold uppercase text-pipeline-selected hover:underline">
                        <Plus size={12} /> Add Operation
                      </button>
                    )}
                  </div>
                  {!collapsedConditions[idx] && (
                    <div className="space-y-4 mt-4">
                      {ops.map((op, opIdx) => (
                        <div key={opIdx} className="bg-surface p-4 rounded-lg border border-border space-y-3">
                          <div className="flex items-center gap-2">
                            <select className="flex-1 text-xs p-1.5 rounded-md font-bold uppercase bg-field-input border border-border" value={op.action || ''} onChange={(e) => updateOperation(idx, opIdx, 'action', e.target.value)}>
                              {(OPERATIONS_SCHEMA || []).map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                            </select>
                            <button onClick={() => removeOperation(idx, opIdx)} className="text-muted hover:text-red-500 p-1">
                              <Trash2 size={16} />
                            </button>
                          </div>
                          {(OPERATIONS_SCHEMA.find(s => s.name === op.action)?.args || []).map(argName => (
                            <div key={argName} className="flex gap-2 items-center">
                              <label className="text-[10px] w-16 uppercase text-muted shrink-0">{argName}</label>
                              <DisplayBar value={op[argName] || ''} onChange={(val) => updateOperation(idx, opIdx, argName, val)} />
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default ConditionEditor;