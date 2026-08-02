"use client";
import React from 'react';
import { GitBranch, AlertCircle, Plus, Trash2, ChevronDown, GripVertical } from 'lucide-react';

const FLOW_CONTROL_OPTIONS = [
  { name: 'break', label: 'Stop Pipeline', args: [] },
  { name: 'continue', label: 'Continue to Next Node', args: [] },
  { name: 'retry', label: 'Retry with Backoff', args: ['max_retries', 'delay_seconds'] },
  { name: 'goto', label: 'Go To Node', args: ['target'] },
  { name: "int", label: "Convert to Whole Number", args: ["value"] },
  { name: "bool", label: "Convert to True/False", args: ["value"] },
  { name: "float", label: "Convert to Decimal", args: ["value"] },
  { name: "upper", label: "Make Uppercase", args: ["value"] },
  { name: "lower", label: "Make Lowercase", args: ["value"] },
  { name: "capitalize", label: "Capitalize First Letter", args: ["value"] },
  { name: "trim", label: "Remove Extra Spaces", args: ["value"] },
  { name: "length", label: "Count Characters", args: ["value"] },
  { name: "split", label: "Split Text", args: ["value", "map_to", "delimiter"] },
  { name: "replace", label: "Replace Text", args: ["value", "search", "replacement"] },
  { name: "substring", label: "Get Part of Text", args: ["value", "start", "end"] },
  { name: "contains", label: "Check if Text Exists", args: ["value", "search"] },
  { name: "sum", label: "Add Numbers", args: ["arg1", "arg2"] },
  { name: "round", label: "Round Number", args: ["value", "precision"] },
  { name: "ceil", label: "Round Up", args: ["value"] },
  { name: "floor", label: "Round Down", args: ["value"] },
  { name: "toInt", label: "Make Integer", args: ["value"] },
  { name: "first", label: "Get First Item", args: ["value"] },
  { name: "last", label: "Get Last Item", args: ["value"] },
  { name: "join", label: "Combine Items", args: ["value", "separator"] },
  { name: "flatten", label: "Flatten List", args: ["value"] },
  { name: "now", label: "Get Current Time", args: [] },
  { name: "formatDate", label: "Format Date", args: ["value", "format_str"] },
  { name: "addDays", label: "Add Days to Date", args: ["value", "days"] }
];

const AVAILABLE_VARIABLES = [
  { label: "Trigger ID", value: "{{trigger.id}}" },
  { label: "User Email", value: "{{user.email}}" },
  { label: "Execution Time", value: "{{execution.time}}" },
  { label: "Payload Data", value: "{{payload.data}}" }
];

/**
 * VISUAL COMPONENT: Handles the display of a single operation.
 * Enterprise UI/UX: Enhanced spacing, focus rings, and visual feedback.
 */
const OperationCard = ({ index, op, onRemove, onUpdate }) => {
  const currentOption = FLOW_CONTROL_OPTIONS.find(opt => opt.name === op.action);

  return (
    <div className="group relative p-5 border border-border rounded-xl bg-builder-pure shadow-sm hover:shadow-md transition-all duration-200">
      <div className="flex justify-between items-center mb-4">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-pipeline-selected/10 rounded-md">
            <AlertCircle size={14} className="text-pipeline-selected" />
          </div>
          <label className="text-[11px] uppercase tracking-wider font-semibold text-muted">
            Step {index + 1}
          </label>
        </div>
        <button 
          onClick={onRemove} 
          className="text-muted hover:text-red-500 transition-colors p-1.5 hover:bg-red-50 rounded-md opacity-0 group-hover:opacity-100"
          title="Remove step"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="space-y-3">
        <select 
          value={op.action}
          onChange={(e) => onUpdate('action', e.target.value)}
          className="w-full bg-field-input border border-border rounded-lg p-2.5 text-sm text-pipeline-text-heading cursor-pointer focus:ring-2 focus:ring-pipeline-selected focus:border-transparent outline-none transition-all"
        >
          {FLOW_CONTROL_OPTIONS.map((opt) => (
            <option key={opt.name} value={opt.name}>{opt.label}</option>
          ))}
        </select>

        {currentOption?.args.map((arg) => {
          const label = arg.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
          return (
            <div key={arg} className="space-y-1.5">
              <label className="text-[10px] font-bold text-muted uppercase tracking-wider">{label}</label>
              <div className="flex gap-2 items-center">
                <div className="relative flex-1">
                  <input 
                    type="text"
                    placeholder={label}
                    value={op[arg] || ''}
                    onChange={(e) => onUpdate(arg, e.target.value)}
                    className="w-full bg-field-input border border-border rounded-lg p-2.5 text-sm text-pipeline-text-heading focus:ring-2 focus:ring-pipeline-selected focus:border-transparent outline-none transition-all"
                  />
                </div>
                <div className="relative">
                  <select 
                    className="appearance-none bg-surface border border-border text-xs rounded-lg p-2.5 pl-3 pr-8 cursor-pointer hover:border-pipeline-selected hover:bg-slate-50 text-muted focus:ring-2 focus:ring-pipeline-selected outline-none transition-all"
                    onChange={(e) => {
                        if (e.target.value) {
                            onUpdate(arg, (op[arg] || '') + e.target.value);
                            e.target.value = ""; 
                        }
                    }}
                  >
                    <option value="">Insert Variable</option>
                    {AVAILABLE_VARIABLES.map(v => (
                        <option key={v.value} value={v.value}>{v.label} ({v.value})</option>
                    ))}
                  </select>
                  <ChevronDown size={12} className="absolute right-2.5 top-3.5 text-muted pointer-events-none" />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/**
 * LOGIC COMPONENT: Handles the list state and updating the parent config.
 */
const PolicyEditor = ({
    operations = [],
    handleConfigChange
}) => {

  const updateOperation = (index, key, value) => {
    const newOperations = [...operations];
    newOperations[index] = key === 'action' 
      ? { action: value } 
      : { ...newOperations[index], [key]: value };
      
    handleConfigChange('operations', newOperations);
  };

  const addOperation = () => handleConfigChange('operations', [...operations, { action: 'continue' }]);
  
  const removeOperation = (index) => handleConfigChange('operations', operations.filter((_, i) => i !== index));

  return (
    <div className="flex-1 p-8 overflow-y-auto bg-surface">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-2 bg-pipeline-selected/10 rounded-lg">
            <GitBranch className="text-pipeline-selected" size={24} />
        </div>
        <div>
            <h3 className="text-base font-bold text-pipeline-text-heading">Runtime Execution Policy</h3>
            <p className="text-xs text-muted">Configure flow control and logic sequences.</p>
        </div>
      </div>

      <div className="space-y-4">
        {operations.length === 0 ? (
            <div className="p-12 border-2 border-dashed border-border rounded-xl text-center flex flex-col items-center justify-center bg-builder-pure/50 transition-all hover:bg-builder-pure">
                <div className="p-4 bg-surface rounded-full mb-4">
                    <GitBranch size={32} className="text-muted opacity-50" />
                </div>
                <p className="text-sm font-semibold text-pipeline-text-heading">No operations defined</p>
                <p className="text-xs text-muted mt-1 max-w-[200px]">Define your first automation step to get started.</p>
            </div>
        ) : (
            operations.map((op, index) => (
            <OperationCard 
                key={index}
                index={index}
                op={op}
                onRemove={() => removeOperation(index)}
                onUpdate={(key, val) => updateOperation(index, key, val)}
            />
            ))
        )}

        <button 
          onClick={addOperation}
          className="w-full py-3 px-4 border border-dashed border-border rounded-xl text-sm font-medium text-muted hover:text-pipeline-selected hover:border-pipeline-selected hover:bg-pipeline-selected/5 flex items-center justify-center gap-2 transition-all duration-200"
        >
          <Plus size={16} /> Add Operation
        </button>
      </div>
    </div>
  );
};

export default PolicyEditor;