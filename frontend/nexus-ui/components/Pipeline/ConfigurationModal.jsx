"use client";
import React from 'react';
import { X, Zap, Trash2, Undo2, Redo2, Settings2 } from 'lucide-react';
import ConditionEditor from './ConditionEditor';
import PolicyEditor from './PolicyEditor'; // Imported the isolated sub-component

const ConfigurationModal = ({
  selectedNodeId,
  selectedNode,
  onClose,
  activeConfigTab,
  setActiveConfigTab,
  activeNodeSchema,
  nodeConfigs,
  handleConfigChange,
  fieldMappings,
  setFieldMappings,
  targetField,
  setTargetField,
  renderTree,
  handleWrapFunction,
  handleRemoveMapping,
  AVAILABLE_FUNCTIONS,
  getServiceColor,
  getServiceIcon,
  getDisplayService,
  SAMPLE_PAYLOAD,
  onUndo,
  onRedo,
  canUndo = false,
  canRedo = false
}) => {

  const OPERATORS = [
    { label: 'Equal to', value: '==' },
    { label: 'Not equal to', value: '!=' },
    { label: 'Greater than', value: '>' },
    { label: 'Less than', value: '<' },
    { label: 'Greater than or equal to', value: '>=' },
    { label: 'Less than or equal to', value: '<=' },
    { label: 'Contains', value: 'contains' },
    { label: 'Includes', value: 'includes' },
    { label: 'Matches (Regex)', value: 'matches' },
    { label: 'OR', value: 'or' }
  ];

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-modal-overlay backdrop-blur-sm p-4">
      <div className="w-[850px] border rounded-[1rem] shadow-2xl flex flex-col h-[85vh] overflow-hidden bg-surface border-border">
        
        {/* Top Header Row */}
        <div className="h-16 px-6 border-b flex items-center justify-between bg-surface border-border flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className={`w-7 h-7 flex items-center justify-center border rounded-md bg-pipeline-btn border-border ${getServiceColor(selectedNode?.service)}`}>
              {getServiceIcon(selectedNode?.service)}
            </div>
            <h2 className="text-base font-bold uppercase tracking-wider text-pipeline-text-heading">{getDisplayService(selectedNode?.service)}</h2>
            <span className="text-sm font-mono text-muted">ID: {selectedNodeId}</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center border rounded-lg overflow-hidden border-border">
              <button onClick={onUndo} disabled={!canUndo} className="p-2 border-r border-border text-slate-500 hover:text-slate-800 disabled:opacity-30 transition-colors" title="Undo"><Undo2 size={16} /></button>
              <button onClick={onRedo} disabled={!canRedo} className="p-2 text-slate-500 hover:text-slate-800 disabled:opacity-30 transition-colors" title="Redo"><Redo2 size={16} /></button>
            </div>
            <button onClick={onClose} className="text-muted hover:text-pipeline-text-heading transition-colors"><X size={20} /></button>
          </div>
        </div>

        {/* Tab Selection Row */}
        <div className="flex border-b border-border bg-editor-sub flex-shrink-0">
          <button onClick={() => setActiveConfigTab('config')} className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeConfigTab === 'config' ? 'text-pipeline-selected border-pipeline-selected' : 'text-muted border-transparent hover:text-pipeline-text-heading'}`}>Configuration</button>
          <button onClick={() => setActiveConfigTab('policy')} className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeConfigTab === 'policy' ? 'text-pipeline-selected border-pipeline-selected' : 'text-muted border-transparent hover:text-pipeline-text-heading'}`}>Runtime Policy</button>
          <button onClick={() => setActiveConfigTab('mapping')} className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeConfigTab === 'mapping' ? 'text-pipeline-selected border-pipeline-selected' : 'text-muted border-transparent hover:text-pipeline-text-heading'}`}>Node Data Mapping</button>
          <button onClick={() => setActiveConfigTab('conditions')} className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${activeConfigTab === 'conditions' ? 'text-pipeline-selected border-pipeline-selected' : 'text-muted border-transparent hover:text-pipeline-text-heading'}`}>Conditions</button>
        </div>

        {/* Tab Panel View Container */}
        <div className="flex-1 flex overflow-hidden">
          {activeConfigTab === 'mapping' ? (
            <>
              <div className="w-1/2 border-r flex flex-col border-border bg-editor-sub">
                <div className="px-4 py-3 border-b flex items-center justify-between text-sm uppercase tracking-widest font-bold border-border-light text-muted">
                  <span>{targetField ? "Select field(s) to map" : "Source Payload"}</span>
                </div>
                <div className="flex-1 overflow-y-auto py-2">
                  {renderTree(SAMPLE_PAYLOAD)}
                </div>
              </div>
              <div className="w-1/2 p-6 flex flex-col overflow-auto bg-surface">
                <div className="flex items-center gap-2 mb-4 text-muted">
                  <Zap size={16} />
                  <h3 className="text-sm font-bold uppercase tracking-wider">Map Fields</h3>
                </div>
                {activeNodeSchema ? (
                  <div className="space-y-4">
                    {Object.keys(activeNodeSchema).map((field) => {
                      const nodeInput = selectedNode?.input || {};
                      const val = fieldMappings[selectedNodeId]?.[field] || nodeInput[field] || "";
                      const isFocused = targetField === field;
                      const paths = val ? val.split(' ').filter(p => p.startsWith('{{') && p.endsWith('}}')) : [];
                      
                      return (
                        <div key={field} className="flex flex-col gap-1">
                          <label className="text-[10px] uppercase tracking-widest font-bold text-muted">{field}</label>
                          <div 
                            onClick={() => setTargetField(field)}
                            className={`w-full p-3 rounded-lg border cursor-pointer transition-all min-w-0 bg-builder-pure ${isFocused ? 'border-pipeline-selected ring-1 ring-pipeline-selected' : 'border-border hover:border-border-hover'}`}
                          >
                            {paths.length > 0 ? (
                              <div className="flex flex-col gap-2">
                                {paths.map((p, idx) => (
                                  <div key={idx} className="flex flex-wrap items-center gap-2 px-2 py-1.5 rounded border bg-pipeline-token-bg border-border-light">
                                      <span className="font-mono text-xs text-pipeline-selected break-all flex-1 min-w-0">{p}</span>
                                      <div className="flex items-center gap-1 flex-shrink-0">
                                        <div className="relative group/fx">
                                          <button className="text-[10px] px-2 py-1 rounded bg-pipeline-btn text-pipeline-btn-text hover:bg-border-hover">fx</button>
                                          <div className="hidden group-hover/fx:block absolute right-0 top-full border rounded shadow-xl z-50 p-1 w-24 bg-surface border-border">
                                              {AVAILABLE_FUNCTIONS.map(f => (
                                                <button key={f} onClick={(e) => { e.stopPropagation(); handleWrapFunction(f, field, p); }} className="block w-full text-left text-xs px-2 py-1 hover:bg-pipeline-selected hover:text-white rounded text-pipeline-text">{f}()</button>
                                              ))}
                                          </div>
                                        </div>
                                        <button onClick={(e) => { e.stopPropagation(); handleRemoveMapping(selectedNodeId, field, p); }} className="text-muted hover:text-log-error transition-colors p-1"><Trash2 size={12} /></button>
                                      </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="font-mono text-sm text-muted">
                                  {isFocused ? "Select path from left..." : "Not mapped"}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : <div className="italic text-sm text-muted">Loading schema...</div>}
              </div>
            </>
          ) : activeConfigTab === 'conditions' ? (
            <ConditionEditor 
              conditions={Array.isArray(nodeConfigs?.[selectedNodeId]?.condition) ? nodeConfigs[selectedNodeId].condition : []}
              handleConfigChange={handleConfigChange}
              SAMPLE_PAYLOAD={SAMPLE_PAYLOAD}
              OPERATORS={OPERATORS}
            />
          ) : activeConfigTab === 'policy' ? (
            <PolicyEditor 
              operations={Array.isArray(nodeConfigs?.[selectedNodeId]?.operations) ? nodeConfigs[selectedNodeId].operations : []}
              handleConfigChange={handleConfigChange}
            />
          ) : (
            <div className="flex-1 p-6 overflow-y-auto bg-surface">
              <div className="flex items-center gap-2 mb-6">
                  <Settings2 className="text-pipeline-selected" size={20} />
                  <h3 className="text-sm font-bold uppercase tracking-wider text-pipeline-text-heading">Service Configuration</h3>
              </div>
              {activeNodeSchema && Object.keys(activeNodeSchema).length > 0 ? (
                <div className="space-y-6">
                    {Object.entries(activeNodeSchema).map(([key, config]) => {
                        const val = nodeConfigs?.[selectedNodeId]?.[key] ?? '';
                        return (
                          <div key={key} className="flex flex-col gap-2">
                              <label className="text-xs uppercase text-pipeline-text">{config.label || key}</label>
                              {config.type === 'select' ? (
                                  <select 
                                    key={key} 
                                    value={val}
                                    onChange={(e) => handleConfigChange(key, e.target.value)}
                                    className="border p-2 rounded w-full bg-field-input border-border text-pipeline-text-heading"
                                  >
                                    {config.options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                                  </select>
                              ) : (
                                  <input 
                                    key={key}
                                    type={config.type}
                                    value={val}
                                    onChange={(e) => handleConfigChange(key, e.target.value)}
                                    className="border p-2 rounded w-full bg-field-input border-border text-pipeline-text-heading"
                                  />
                              )}
                          </div>
                        );
                    })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-muted border border-dashed border-border rounded-lg">
                    <Settings2 size={32} className="mb-2 opacity-50" />
                    <p className="text-sm">No configuration options available for this node.</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ConfigurationModal;