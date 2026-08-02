"use client";
import React, { useState } from 'react';
import { Plus, Trash2, ArrowUpRight, Ban, GitCommit, ChevronDown, ChevronRight, ListFilter, RefreshCw } from 'lucide-react';
import { getDisplayService, getServiceColor, getServiceIcon } from './PipelineUtils';

// Helper to translate operators to plain language
const getFriendlyCondition = (ifString) => {
  if (!ifString || typeof ifString !== 'string') return ifString;
  
  const mapping = {
    '==': 'equals',
    '!=': 'does not equal',
    '>=': 'is greater than or equal to',
    '<=': 'is less than or equal to',
    '>': 'is greater than',
    '<': 'is less than',
    'contains': 'contains',
    'includes': 'includes',
    'matches': 'matches'
  };

  let translated = ifString;
  Object.entries(mapping).forEach(([syntax, friendly]) => {
    translated = translated.replace(new RegExp(`\\s*${syntax}\\s*`, 'g'), ` ${friendly} `);
  });
  return translated;
};

// Helper to translate technical actions to plain language
const getPlainLanguageAction = (action, target) => {
  if (action === 'continue') return null;
  switch (action) {
    case 'goto': return `go to ${target || 'step'}`;
    case 'break': return "stop the process";
    case 'execute': return "proceed";
    default: return action;
  }
};

// Helper component to render multi-condition blocks consistently across renderers
const ConditionsOverlay = ({ conditionData, onSelect, stepId }) => {
  const [isCollapsed, setIsCollapsed] = useState(false);

  if (!conditionData) return null;

  const conditions = Array.isArray(conditionData) ? conditionData.filter(Boolean) : [conditionData];
  const activeConditions = conditions.filter(c => c?.action !== 'continue');
  
  if (activeConditions.length === 0) return null;

  return (
    <div className="flex flex-col gap-1 items-center">
      {/* Header / Toggle Pill */}
      <div 
        onClick={(e) => { e.stopPropagation(); setIsCollapsed(!isCollapsed); }}
        className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full bg-zinc-500/10 text-zinc-500 border border-zinc-500/20 cursor-pointer hover:bg-zinc-500/20 transition-all"
      >
        {isCollapsed ? <ChevronRight size={10} /> : <ChevronDown size={10} />}
        <ListFilter size={10} />
        {activeConditions.length} Condition{activeConditions.length > 1 ? 's' : ''}
      </div>

      {/* Expanded View */}
      {!isCollapsed && activeConditions.map((cond, idx) => {
        const displayAction = getPlainLanguageAction(cond?.action, cond?.target);
        const displayIf = getFriendlyCondition(cond?.if);

        return (
          <div 
            key={idx} 
            onClick={(e) => { e.stopPropagation(); onSelect(stepId); }}
            className={`flex flex-wrap items-center gap-1.5 text-xs font-medium tracking-wide px-2.5 py-1 rounded-md border shadow-sm cursor-pointer hover:brightness-110 transition-all w-fit max-w-xs ${
              cond?.action === 'break' 
                ? 'bg-amber-500/20 text-amber-900 dark:text-amber-200 border-amber-500/50' 
                : cond?.action === 'goto'
                ? 'bg-indigo-500/20 text-indigo-900 dark:text-indigo-200 border-indigo-500/50'
                : 'bg-emerald-500/20 text-emerald-900 dark:text-emerald-300 border-emerald-500/50'
            }`}
          >
            <GitCommit size={12} className="shrink-0 stroke-[2.5] fill-current" />
            <span>If {displayIf}, then {displayAction}</span>
          </div>
        );
      })}
    </div>
  );
};

export const TreeRenderer = ({ step, sequenceMap, onAdd, onAddSibling, onDelete, onReplace, onSelect, selectedId, theme }) => {
  const isDark = theme === 'dark';
  
  return (
    <div className="flex flex-col w-full relative">
      <div 
        onClick={(e) => { e.stopPropagation(); onSelect(step.id); }} 
        className={`flex items-center group py-2 relative cursor-pointer px-2 rounded-lg transition-colors ${selectedId === step.id ? 'bg-pipeline-selected/10' : ''}`}
      >
        <button 
          onClick={(e) => { e.stopPropagation(); onAdd(step.id); }} 
          className={`absolute -left-[30px] opacity-0 group-hover:opacity-100 transition-opacity rounded-full p-1 bg-pipeline-btn text-pipeline-btn-text hover:bg-pipeline-btn-hover`}
          title="Add Child Node"
        >
          <Plus size={12} />
        </button>

        <div className={`w-8 h-8 flex items-center justify-center border rounded-xl transition-all shadow-lg bg-pipeline-node ${getServiceColor(step.service)} ${selectedId === step.id ? 'ring-2 ring-pipeline-selected' : ''}`}>
          {getServiceIcon(step.service)}
        </div>
        
        <div className="flex flex-col ml-3 justify-center">
          <span className={`text-sm font-semibold tracking-tight text-pipeline-text flex items-center gap-1.5`}>
            {getDisplayService(step.service)}
          </span>
        </div>

        <div className="absolute right-2 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
          <button 
            onClick={(e) => { e.stopPropagation(); onAddSibling(step.id); }}
            className="p-1 rounded bg-pipeline-btn text-pipeline-btn-text hover:bg-pipeline-btn-hover text-xs font-semibold px-1.5"
            title="Add Sibling Node"
          >
            + Sibling
          </button>
          <button 
            onClick={(e) => { e.stopPropagation(); onReplace(step.id); }}
            className="p-1 rounded text-blue-500 hover:bg-blue-500/10"
            title="Replace Node"
          >
            <RefreshCw size={12} />
          </button>
          <button 
            onClick={(e) => { e.stopPropagation(); onDelete(step.id); }}
            className="p-1 rounded text-red-500 hover:bg-red-500/10"
            title="Delete Node"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>
      
      {step.steps && Array.isArray(step.steps) && step.steps.length > 0 && (
        <div className="ml-4 pl-4 border-l transition-colors border-pipeline-line group-hover:border-pipeline-line-hover">
          {step.steps.filter(Boolean).map((child) => (
            <TreeRenderer 
              key={child.id} 
              step={child} 
              sequenceMap={sequenceMap}
              onAdd={onAdd} 
              onAddSibling={onAddSibling}
              onDelete={onDelete}
              onReplace={onReplace}
              onSelect={onSelect} 
              selectedId={selectedId} 
              theme={theme}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const GraphRenderer = ({ step, sequenceMap, index = 0, onAdd, onAddSibling, onDelete, onReplace, onSelect, selectedId, theme, layoutMode }) => {
  const isDark = theme === 'dark';
  const isHorizontal = false;

  const isArray = Array.isArray(step.condition);
  const executeConditions = step.condition 
    ? (isArray ? step.condition.filter(c => c?.action === 'execute') : (step.condition?.action === 'execute' ? step.condition : null))
    : null;
    
  const otherConditions = step.condition
    ? (isArray ? step.condition.filter(c => c?.action !== 'execute') : (step.condition?.action !== 'execute' ? step.condition : null))
    : null;

  const getActionStyles = (action) => {
    switch (action) {
      case 'break': return 'bg-amber-500/20 text-amber-900 dark:text-amber-200 border-amber-500/50';
      case 'goto': return 'bg-indigo-500/20 text-indigo-900 dark:text-indigo-200 border-indigo-500/50';
      default: return 'bg-emerald-500/20 text-emerald-900 dark:text-emerald-300 border-emerald-500/50';
    }
  };

  const getActionIcon = (action) => {
    switch (action) {
      case 'break': return <Ban size={12} className="shrink-0 stroke-[2.5] fill-current" />;
      case 'goto': return <ArrowUpRight size={12} className="shrink-0 stroke-[2.5] fill-current" />;
      default: return <GitCommit size={12} className="shrink-0 stroke-[2.5] fill-current" />;
    }
  };

  if (isHorizontal) return null; 

  const showAction = step.action && step.action !== 'continue';

  return (
    <div className="flex flex-col items-center min-w-max">
      {executeConditions && (
        <div className="flex flex-col items-center">
          <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
          <ConditionsOverlay conditionData={executeConditions} onSelect={onSelect} stepId={step.id} />
          <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
        </div>
      )}

      <div className="relative group">
        <div className="absolute -left-12 top-1/2 -translate-y-1/2 flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-all z-20">
            <button 
              onClick={(e) => { e.stopPropagation(); onReplace(step.id); }}
              className="p-1 rounded-md bg-zinc-900 border border-white/10 text-blue-400 hover:text-blue-500 shadow-md"
              title="Replace Node"
            >
              <RefreshCw size={12} />
            </button>
            <button 
              onClick={(e) => { e.stopPropagation(); onDelete(step.id); }}
              className="p-1 rounded-md bg-zinc-900 border border-white/10 text-red-400 hover:text-red-500 shadow-md"
              title="Delete Node"
            >
              <Trash2 size={12} />
            </button>
        </div>
        <div 
          onClick={(e) => { e.stopPropagation(); onSelect(step.id); }}
          className={`w-14 h-14 flex items-center justify-center backdrop-blur border-2 border-foreground/10 rounded-2xl shadow-lg hover:shadow-xl transition-all cursor-pointer bg-pipeline-node/80 ${getServiceColor(step.service)} ${selectedId === step.id ? 'ring-2 ring-pipeline-selected' : ''}`}
        >
          {getServiceIcon(step.service)}
        </div>
        <button 
          onClick={(e) => { e.stopPropagation(); onAdd(step.id); }} 
          className={`absolute -bottom-3 left-[35%] -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity rounded-full p-1 z-10 bg-pipeline-btn text-pipeline-btn-text hover:bg-pipeline-btn-hover`}
          title="Add Child Branch"
        >
          <Plus size={12} />
        </button>
        <button 
          onClick={(e) => { e.stopPropagation(); onAddSibling(step.id); }} 
          className={`absolute -bottom-3 left-[65%] -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity rounded-full p-1 z-10 bg-blue-600 text-white hover:bg-blue-500`}
          title="Add Next Sibling Step"
        >
          <Plus size={12} className="rotate-45" />
        </button>
      </div>

      <div className="mt-2 text-center flex flex-col items-center gap-0.5">
          <p className="text-sm font-semibold text-pipeline-text-heading">{getDisplayService(step.service)}</p>
          <div className="flex items-center gap-1.5 opacity-60">
            <span className="text-[11px] font-bold bg-zinc-500/10 px-1 rounded">#{sequenceMap[step.id]}</span>
            <span className="text-[11px] font-mono truncate max-w-[60px]">{step.id}</span>
          </div>
      </div>
      
      {(showAction || step.value || otherConditions) && (
        <div className="flex flex-col items-center">
            <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
            <div className="flex flex-col items-center">
                {otherConditions && <ConditionsOverlay conditionData={otherConditions} onSelect={onSelect} stepId={step.id} />}
                {showAction && (
                    <span 
                      onClick={(e) => { e.stopPropagation(); onSelect(step.id); }}
                      className={`flex flex-wrap items-center gap-1.5 text-xs font-medium tracking-wide px-2.5 py-1 rounded-md border shadow-sm cursor-pointer hover:brightness-110 transition-all w-fit max-w-xs ${getActionStyles(step.action)}`}
                    >
                        {getActionIcon(step.action)}
                        {getPlainLanguageAction(step.action, step.target)}
                    </span>
                )}
                {step.value && (
                    <span 
                      onClick={(e) => { e.stopPropagation(); onSelect(step.id); }}
                      className="text-[11px] font-mono font-bold bg-zinc-500/10 text-zinc-600 dark:text-zinc-400 px-1.5 rounded border border-zinc-500/20 cursor-pointer hover:brightness-110 transition-all"
                    >
                        {step.value}
                    </span>
                )}
            </div>
            {step.steps && Array.isArray(step.steps) && step.steps.length > 0 && (
                <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
            )}
        </div>
      )}
      
      {step.steps && Array.isArray(step.steps) && step.steps.length > 0 && (
        <div className="flex flex-col items-center w-full">
          {(!showAction && !step.value && !otherConditions) && (
             <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
          )}
          <div className="flex flex-row gap-12 items-stretch">
              {step.steps.map((child, i) => (
                  <div key={child.id} className="flex flex-col items-center">
                      <div className="flex w-[calc(100%+3rem)] -mx-[1.5rem]">
                          <div className={`flex-1 ${i !== 0 ? 'border-t border-pipeline-line' : ''}`} />
                          <div className={`flex-1 ${i !== step.steps.length - 1 ? 'border-t border-pipeline-line' : ''}`} />
                      </div>
                      <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
                      <GraphRenderer 
                        step={child}
                        sequenceMap={sequenceMap}
                        index={i}
                        onAdd={onAdd} 
                        onAddSibling={onAddSibling}
                        onDelete={onDelete}
                        onReplace={onReplace}
                        onSelect={onSelect} 
                        selectedId={selectedId} 
                        theme={theme}
                        layoutMode={layoutMode}
                      />
                      <div className="relative group/line flex-grow flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
                      <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
                      <div className="flex w-[calc(100%+3rem)] -mx-[1.5rem]">
                          <div className={`flex-1 ${i !== 0 ? 'border-t border-pipeline-line' : ''}`} />
                          <div className={`flex-1 ${i !== step.steps.length - 1 ? 'border-t border-pipeline-line' : ''}`} />
                      </div>
                  </div>
              ))}
          </div>
          <div className="relative group/line h-4 flex items-center justify-center"><div className="w-0.5 h-full bg-pipeline-line" /></div>
        </div>
      )}
    </div>
  );
};