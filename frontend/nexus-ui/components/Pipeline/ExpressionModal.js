"use client";
import React, { useState, useMemo, useRef, useEffect } from 'react';
import { X, ChevronDown, Wand2, Settings2, Plus, Check, Undo2, Redo2, AlertCircle } from 'lucide-react';
import { ExpressionEngine } from './ExpressionEngine';

const ExpressionModal = ({ 
  isOpen, 
  onClose, 
  onSave, 
  operationsSchema, 
  SAMPLE_PAYLOAD,
  initialSource = ""
}) => {
  // Clean initial source if it already has wrappers to avoid double-wrapping
  const cleanedInitial = initialSource.replace(/^\{\{|\}\}$/g, '');
  const [source, setSource] = useState(cleanedInitial);
  const [history, setHistory] = useState([cleanedInitial]);
  const [pointer, setPointer] = useState(0);
  const [func, setFunc] = useState("");
  const [args, setArgs] = useState({});
  const [isVarDropdownOpen, setIsVarDropdownOpen] = useState(false);
  const [varSearchTerm, setVarSearchTerm] = useState("");
  const [editingIndex, setEditingIndex] = useState(null);
  const [error, setError] = useState(null);
  const dropdownRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      const cleaned = initialSource.replace(/^\{\{|\}\}$/g, '');
      setSource(cleaned);
      setHistory([cleaned]);
      setPointer(0);
      setEditingIndex(null);
      setArgs({});
      setError(null);
      setFunc("");
    }
  }, [isOpen, initialSource]);

  const updateSource = (newSource) => {
    const newHistory = history.slice(0, pointer + 1);
    setHistory([...newHistory, newSource]);
    setPointer(newHistory.length);
    setSource(newSource);
    setError(null);
  };

  const undo = () => { if (pointer > 0) { setPointer(pointer - 1); setSource(history[pointer - 1]); } };
  const redo = () => { if (pointer < history.length - 1) { setPointer(pointer + 1); setSource(history[pointer + 1]); } };

  const chain = useMemo(() => {
    try {
      const ast = ExpressionEngine.parse(source);
      const nodes = [];
      let current = ast;
      while (current?.type === 'CallExpression') {
        nodes.unshift(current);
        current = current.args[0];
      }
      return nodes;
    } catch { return []; }
  }, [source]);

  const handleEditNode = (node, index) => {
    setEditingIndex(index);
    setFunc(node.name);
    const newArgs = {};
    node.args.slice(1).forEach((arg, i) => {
      const argName = operationsSchema.find(s => s.name === node.name)?.args[i + 1];
      if (argName) newArgs[argName] = arg.value?.value || "";
    });
    setArgs(newArgs);
  };

  const removeNodeFromChain = (e, indexToRemove) => {
    e.stopPropagation();
    setEditingIndex(null);
    const newChain = chain.filter((_, i) => i !== indexToRemove);
    if (newChain.length === 0) {
      updateSource("");
      return;
    }
    let newAst = chain[0].args[0]; 
    newChain.forEach((node) => {
      newAst = { type: 'CallExpression', name: node.name, args: [newAst, ...node.args.slice(1)] };
    });
    updateSource(ExpressionEngine.compileToCLI(newAst));
  };

  const getPaths = (obj, p = '') => {
    let paths = [];
    Object.keys(obj || {}).forEach(k => {
      const path = p ? `${p}.${k}` : k;
      if (obj[k] !== null && typeof obj[k] === 'object') {
        paths.push(...getPaths(obj[k], path));
      } else {
        paths.push(path);
      }
    });
    return paths;
  };

  const variableOptions = useMemo(() => getPaths(SAMPLE_PAYLOAD), [SAMPLE_PAYLOAD]);
  const filteredVariables = useMemo(() => 
    variableOptions.filter(v => v.toLowerCase().includes(varSearchTerm.toLowerCase()))
  , [variableOptions, varSearchTerm]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsVarDropdownOpen(false);
      }
    };
    if (isVarDropdownOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isVarDropdownOpen]);

  if (!isOpen) return null;

  const handleAddOperation = () => {
    if (!source.trim()) {
      setError("Please define a source variable before adding operations.");
      return;
    }
    
    if (!func) {
      setEditingIndex(null);
      setError(null);
      return;
    }

    const schema = operationsSchema.find(s => s.name === func);
    const argNames = schema.args.slice(1);
    
    const argNodes = argNames.map(a => ({ 
      type: 'NamedArgument', 
      key: a, 
      value: { type: 'Literal', value: args[a] || '""' } 
    }));

    let newAst;
    if (editingIndex !== null) {
      const newChain = [...chain];
      newChain[editingIndex] = { ...newChain[editingIndex], name: func, args: [newChain[editingIndex].args[0], ...argNodes] };
      newAst = newChain[0].args[0];
      newChain.forEach(node => {
        newAst = { type: 'CallExpression', name: node.name, args: [newAst, ...argNodes] };
      });
      setEditingIndex(null);
    } else {
      let inputAst;
      try { inputAst = ExpressionEngine.parse(source); } catch { inputAst = { type: 'Literal', value: source || '""' }; }
      newAst = { type: 'CallExpression', name: func, args: [inputAst, ...argNodes] };
    }
    
    updateSource(ExpressionEngine.compileToCLI(newAst));
    setArgs({});
    setError(null);
  };

  const handleSave = () => {
    if (!source.trim()) {
      setError("Cannot save an empty pipeline.");
      return;
    }
    onSave(`{{${source}}}`);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-surface border border-border p-5 rounded-xl w-[640px] max-h-[90vh] flex flex-col shadow-2xl">
        <div className="flex justify-between items-center mb-5">
          <div className="flex items-center gap-3">
            <h3 className="font-bold text-sm uppercase tracking-wider text-pipeline-text-heading flex items-center gap-2">
              <Wand2 size={18} /> Pipeline Builder
            </h3>
            <div className="flex items-center gap-1 border-l border-border pl-3">
                <button onClick={undo} disabled={pointer === 0} className="p-2 text-muted hover:text-white disabled:opacity-20"><Undo2 size={16} /></button>
                <button onClick={redo} disabled={pointer === history.length - 1} className="p-2 text-muted hover:text-white disabled:opacity-20"><Redo2 size={16} /></button>
            </div>
          </div>
          <button onClick={onClose} className="text-muted hover:text-white transition-colors"><X size={20} /></button>
        </div>

        {error && (
        <div className="mb-5 p-3.5 bg-red-500/10 border border-red-500/50 rounded-lg text-red-500 text-sm flex items-center gap-2">
            <AlertCircle size={16} /> {error}
        </div>
        )}

        <div className="mb-5">
        <label className="text-[10px] font-bold uppercase text-muted mb-2.5 block">Active Pipeline</label>
        <div className="flex flex-wrap gap-2 p-3 bg-black/20 rounded-lg border border-border/50 min-h-[48px] items-center">
            {chain.length > 0 ? chain.map((node, i) => (
            <div key={i} className={`flex items-center gap-1.5 pl-4 pr-2 py-2 ${editingIndex === i ? 'bg-pipeline-selected ring-2 ring-white' : 'bg-pipeline-selected'} text-white text-xs font-bold rounded-full shadow-sm border border-white/10`}>
                <button onClick={() => handleEditNode(node, i)} className="hover:underline">{node.name}</button>
                <button onClick={(e) => removeNodeFromChain(e, i)} className="p-0.5 hover:bg-white/20 rounded-full"><X size={12} /></button>
            </div>
            )) : <span className="text-[11px] text-muted italic px-2">Click "Add Operation" to start...</span>}
        </div>
        </div>

        <div className="flex gap-2 mb-5">
            <input 
            placeholder="Source (e.g. $webhook.body.phone)" 
            className="flex-grow p-3.5 bg-field-input border border-border rounded-lg text-sm outline-none focus:ring-2 focus:ring-pipeline-selected/50" 
            value={source}
            onChange={(e) => updateSource(e.target.value)} 
            />
            <div className="relative" ref={dropdownRef}>
                <button onClick={() => setIsVarDropdownOpen(!isVarDropdownOpen)} className="px-4 text-sm bg-field-input border border-border rounded-lg h-[50px] flex items-center gap-2 hover:border-pipeline-selected transition-colors font-medium whitespace-nowrap">
                Variables <ChevronDown size={16} />
                </button>
                {isVarDropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-96 bg-surface border border-border rounded-xl shadow-2xl z-[101] p-4">
                    <input autoFocus placeholder="Search variables..." className="w-full mb-4 p-3 border border-border rounded-lg bg-field-input text-sm" value={varSearchTerm} onChange={(e) => setVarSearchTerm(e.target.value)} />
                    <div className="max-h-60 overflow-y-auto space-y-1.5">
                    {filteredVariables.map(v => (
                        <button key={v} className="block w-full text-left text-sm px-4 py-2.5 hover:bg-pipeline-selected hover:text-white rounded-lg transition-colors" onClick={() => { updateSource(`${source} $${v}`.trim()); setIsVarDropdownOpen(false); }}>{v}</button>
                    ))}
                    </div>
                </div>
                )}
            </div>
        </div>

        <div className="bg-black/10 p-4 rounded-lg border border-border/50 mb-5 flex-grow flex flex-col min-h-0">
        <div className="flex items-center gap-2 mb-4 text-[10px] font-bold text-muted uppercase shrink-0"><Settings2 size={14} /> Function Configuration</div>
        <select className="w-full mb-4 p-3 bg-field-input border border-border rounded text-sm font-medium" value={func} onChange={(e) => setFunc(e.target.value)}>
            <option value="">None</option>
            {operationsSchema.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        
        <div className="overflow-y-auto pr-2 flex-grow min-h-[60px]">
            {func && operationsSchema.find(s => s.name === func)?.args.slice(1).map(a => (
                <input key={a} placeholder={a} value={args[a] || ""} className="w-full mb-3 p-3 bg-field-input border border-border rounded text-sm" onChange={(e) => setArgs({...args, [a]: e.target.value})} />
            ))}
        </div>
        </div>
        
        <div className="flex gap-3">
            <button className={`flex-grow py-4 rounded-lg font-bold text-sm transition-all shadow-lg flex items-center justify-center gap-2 ${!source.trim() ? 'bg-gray-500 cursor-not-allowed opacity-50' : 'bg-pipeline-selected text-white hover:brightness-110'}`} onClick={handleAddOperation}>
                <Plus size={18} /> {func ? (editingIndex !== null ? 'Update Operation' : 'Add Operation') : 'Set Variable'}
            </button>
            <button className="flex-grow bg-white text-black py-4 rounded-lg font-bold text-sm hover:bg-gray-200 transition-all shadow-lg flex items-center justify-center gap-2" onClick={handleSave}>
                <Check size={18} /> Save Expression
            </button>
        </div>
      </div>
    </div>
  );
};

export default ExpressionModal;