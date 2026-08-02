"use client";
import React, { useState, useEffect, useCallback, useRef } from 'react';
import Editor from '@monaco-editor/react';
import yaml from 'js-yaml';
import { X, ChevronLeft, ChevronRight, ChevronDown, Terminal, Maximize2, Minimize2, Folder, FileText, Search, Sparkles, Plus, Trash2, Database, Code, Settings } from 'lucide-react';

// Imported Sidebar
import { Sidebar } from './ProjectSidebar';

import { INITIAL_DATA, SAMPLE_PAYLOAD, AVAILABLE_FUNCTIONS, AVAILABLE_APPS, fetchEngineSchema, getDisplayService, getServiceColor, getServiceIcon } from '@/components/Pipeline/PipelineUtils';
import ConfigurationModal from '@/components/Pipeline/ConfigurationModal';
import { VisualBuilder } from '@/components/Pipeline/VisualBuilder';
import { FloatingActionBar } from '@/components/Pipeline/FloatingActionBar';
import { AppSelectionModal } from '@/components/Pipeline/AppSelectionModal';

interface BuilderPageProps {
  theme?: 'dark' | 'light' | null;
  systemState?: any[];
  fetchSystemState?: () => Promise<void>;
  getScriptContent?: (clientName: string, filePath: string, isAbsolute?: boolean) => Promise<any>;
  fileTree?: any[];
  getFileTree?: () => Promise<any[]>;
  onSelectFile?: (filePath: string) => void;
}

const BuilderPage = ({ theme = 'dark', systemState = [], fetchSystemState, getScriptContent, fileTree: initialFileTree = [],
  getFileTree,
  onSelectFile: externalOnSelectFile }: BuilderPageProps) => {
  const isDark = theme !== 'light';
  
  const [fileTree, setFileTree] = useState<any[]>(initialFileTree);
  const [pipelineData, setPipelineData] = useState(INITIAL_DATA);
  const [yamlString, setYamlString] = useState(yaml.dump(INITIAL_DATA, { skipInvalid: true }));
  const isInternalStateChangeRef = useRef(false);
  const [historyPast, setHistoryPast] = useState<any[]>([]);
  const [historyFuture, setHistoryFuture] = useState<any[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedApp, setSelectedApp] = useState<any>(null); 
  const [searchQuery, setSearchQuery] = useState(''); 
  const [isSidebarExpanded, setIsSidebarExpanded] = useState(true);
  const [activeRightTab, setActiveRightTab] = useState('yaml');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeNodeSchema, setActiveNodeSchema] = useState<any>(null);
  const [aiInput, setAiInput] = useState('');
  const [isAiPanelVisible, setIsAiPanelVisible] = useState(false);
  const [isActionExpanded, setIsActionExpanded] = useState(true);
  const [insertTargetParentId, setInsertTargetParentId] = useState<string | 'root'>('root');
  const [insertMode, setInsertMode] = useState<'child' | 'sibling' | 'replace'>('child');
  const [isTerminalOpen, setIsTerminalOpen] = useState(true);
  const [terminalHeight, setTerminalHeight] = useState(200);
  const [isResizingTerminal, setIsResizingTerminal] = useState(false);
  const [isTerminalMaximized, setIsTerminalMaximized] = useState(false);
  const [terminalFontSize, setTerminalFontSize] = useState(11);
  const [selectedFileName, setSelectedFileName] = useState<string>('pipeline.yaml');
  const [logs] = useState([
      "[INFO] Initializing Piper Engine v4.57.0...",
      "[WARN] Connection to engine lost... attempting retry...",
      "[ERROR] YAML parse error: line 15, column 3",
      "[INFO] Re-parsed INITIAL_DATA successfully.",
      "[EXEC] step_16843058123: Running 'Google' module...",
      "[EXEC] step_16843058123: Running 'Google' module...",
      "[EXEC] step_16843058123: Running 'Google' module..."
  ]);
  const [fieldMappings, setFieldMappings] = useState<Record<string, any>>({});
  const [nodeConfigs, setNodeConfigs] = useState<Record<string, any>>({}); 
  const [activeConfigTab, setActiveConfigTab] = useState('mapping');
  const [targetField, setTargetField] = useState<string | null>(null);
  const [expandedPaths, setExpandedPaths] = useState(new Set(['root']));
  const [activePanel, setActivePanel] = useState('builder');
  const [builderZoom, setBuilderZoom] = useState(1);
  const [editorFontSize, setEditorFontSize] = useState(12);
  const [viewMode, setViewMode] = useState('tree');
  const [editorWidth, setEditorWidth] = useState(typeof window !== 'undefined' ? window.innerWidth / 2 : 400);
  const [isResizing, setIsResizing] = useState(false);
  const [editorLayout, setEditorLayout] = useState<'both' | 'visual' | 'monaco'>('both');

  const appCategories = ['All', 'Triggers', 'Iterators', 'Aggregators', 'Search', 'Bin', 'External App', 'External App API', 'Image'];

  const cycleEditorLayout = () => {
    setEditorLayout((prev) => {
      if (prev === 'both') return 'monaco';
      if (prev === 'monaco') return 'visual';
      return 'both';
    });
  };

  const startResizingTerminal = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizingTerminal(true);
  }, []);

  useEffect(() => {
    if (fetchSystemState) {
      fetchSystemState();
    }
  }, [fetchSystemState]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizingTerminal) return;
      const newHeight = window.innerHeight - e.clientY;
      if (newHeight > 100 && newHeight < window.innerHeight - 100) {
        setTerminalHeight(newHeight);
      }
    };
    const stopResizing = () => setIsResizingTerminal(false);

    if (isResizingTerminal) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', stopResizing);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', stopResizing);
    };
  }, [isResizingTerminal]);

  useEffect(() => {
    if (!selectedNodeId) return;

    let isCancelled = false;
    const node = findNode(pipelineData.pipeline, selectedNodeId) || findNode(pipelineData.trigger, selectedNodeId);

    if (node && node.service) {
      setFieldMappings(prev => ({ ...prev, [selectedNodeId]: { ...(node.input || {}) } }));
      
      fetchEngineSchema(node.service)
        .then(schema => {
          if (!isCancelled) {
            setActiveNodeSchema(schema);
            const localConfigs: Record<string, any> = {};
            Object.keys(schema).forEach(key => {
              localConfigs[key] = node[key] ?? schema[key].default ?? ""; 
            });
            
            localConfigs['condition'] = node.condition || {}; 
            localConfigs['executionMode'] = node.executionMode || '';
            localConfigs['action'] = node.action || '';
            localConfigs['target'] = node.target || '';
            localConfigs["operations"] = node.operations || [];
            
            setNodeConfigs(prev => ({
              ...prev,
              [selectedNodeId]: {
                  ...prev[selectedNodeId],
                  ...localConfigs
              }
          }));
          }
        }).catch((err) => {
          if (!isCancelled) {
             console.error("Failed to fetch node schema:", err);
          }
        });
    }

    return () => {
      isCancelled = true;
    };
  }, [pipelineData, selectedNodeId]);

  const loadFileTree = useCallback(async () => {
    if (getFileTree) {
      try {
        const tree = await getFileTree();
        if (tree) setFileTree(tree);
      } catch (err) {
        console.error("Failed to fetch file tree:", err);
      }
    }
  }, [getFileTree]);

  useEffect(() => {
    if (fetchSystemState) {
      fetchSystemState();
    }
    loadFileTree();
  }, [fetchSystemState, loadFileTree]);

  // Handler when a file is selected from the Workspace Explorer
  const handleSelectFile = async (filePath: string) => {
    console.log("[DEBUG] Selected file from explorer:", filePath);
    const fileName = filePath.split('/').pop() || filePath;
    setSelectedFileName(fileName);

    if (externalOnSelectFile) {
      externalOnSelectFile(filePath);
      return;
    }

    try {
      if (getScriptContent) {
        // Fetch content using absolute path from the workspace root
        const fileContent = await getScriptContent('', filePath, true);
        if (fileContent) {
          setYamlString(fileContent);
          const parsed = yaml.load(fileContent);
          if (parsed && typeof parsed === 'object' && parsed !== null) {
            updatePipeline(parsed);
          }
        }
      }
    } catch (err) {
      console.error("Failed to fetch file content from explorer:", err);
    }
  };


  // Handles fetching and loading automation YAML content via the engine connection
  const handleSelectAutomation = async (clientName: string, automation: any) => {
    console.log(`Selected automation for ${clientName}:`, automation);
    console.log("[DEBUG] Automation file_path received:", automation?.file_path);
    
    const autoName = typeof automation === 'object' && automation !== null
      ? (automation.name || automation.file_path?.split('/').pop() || 'pipeline.yaml')
      : (automation || 'pipeline.yaml');
    setSelectedFileName(autoName);

    try {
      if (getScriptContent && automation?.file_path) {
        console.log("[DEBUG] Fetching automation with absolute path:", automation.file_path);
        const fileContent = await getScriptContent(clientName, automation.file_path);
        
        console.log("[DEBUG] Data received for automation:", fileContent);

        if (fileContent) {
          setYamlString(fileContent);
          const parsed = yaml.load(fileContent);
          if (parsed && typeof parsed === 'object' && parsed !== null) {
            updatePipeline(parsed);
          }
        }
      } else if (automation?.pipeline || automation?.trigger) {
        console.log("[DEBUG] Using inline automation payload directly.");
        updatePipeline(automation);
      }
    } catch (err) {
      console.error("Failed to fetch automation content:", err);
    }
  };

  // Handles fetching and loading custom script content via the engine connection
  const handleSelectScript = async (clientName: string, script: any) => {
    console.log(`Selected script for ${clientName}:`, script);
    
    const scriptName = typeof script === 'object' && script !== null 
      ? (script.name || script.file_path?.split('/').pop()) 
      : script;
    if (scriptName) {
      setSelectedFileName(scriptName);
    }

    try {
      if (getScriptContent) {
        const sName = typeof script === 'object' && script !== null 
          ? (script.name || script.file_path) 
          : script;
          
        // Construct absolute path to the client's script file
        const scriptPath = typeof script === 'object' && script !== null && script.file_path 
          ? script.file_path 
          : `/app/templates/${clientName}/scripts/${sName}.py`;
        
        console.log("[DEBUG] Constructed absolute script path:", script);
        const scriptContent = await getScriptContent(clientName, script, true);
        
        console.log("[DEBUG] Data received for script:", scriptContent);

        if (scriptContent) {
          setYamlString(scriptContent);
          setActiveRightTab('yaml'); 
        }
      }
    } catch (err) {
      console.error("Failed to fetch script content:", err);
    }
  };

  const updateNodeConfigInPipeline = (nodes: any[], targetId: string, key: string, value: any, isMapping = false): any[] => {
    return nodes.map(node => {
      if (node.id === targetId) {
        const newNode = { ...node };
        if (isMapping) {
          const input = { ...(newNode.input || {}) };
          if (value === undefined || value === null || value === "") delete input[key];
          else input[key] = value;
          if (Object.keys(input).length > 0) newNode.input = input; else delete newNode.input;
        } else {
          if (value === undefined || value === null || value === "") delete newNode[key];
          else newNode[key] = value;
        }
        return newNode;
      }
      if (Array.isArray(node.steps)) return { ...node, steps: updateNodeConfigInPipeline(node.steps, targetId, key, value, isMapping) };
      return node;
    });
  };

  const findNode = (nodes: any[], id: string): any => {
      if (!Array.isArray(nodes)) return null;
      for (const node of nodes) {
        if (node.id === id) return node;
        if (Array.isArray(node.steps)) {
          const found = findNode(node.steps, id);
          if (found) return found;
        }
      }
      return null;
  };

  const handleConfigChange = (field: string, value: any) => {
    if (!selectedNodeId) return;
    setNodeConfigs(prev => ({ ...prev, [selectedNodeId]: { ...(prev[selectedNodeId] || {}), [field]: value } }));
    
    const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, selectedNodeId, field, value, false);
    const updatedTrigger = updateNodeConfigInPipeline(pipelineData.trigger, selectedNodeId, field, value, false);
    
    updatePipeline({ ...pipelineData, pipeline: updatedPipeline, trigger: updatedTrigger });
  };

  const handleInjectPath = (path: string[]) => {
    if (selectedNodeId && targetField) {
      const pathString = `{{${path.join('.')}}}`;
      setFieldMappings(prev => {
        const nodeMappings = prev[selectedNodeId] || {};
        const existingValue = nodeMappings[targetField] || "";
        const newValue = existingValue ? `${existingValue} ${pathString}` : pathString;
        const newMappings = { ...prev, [selectedNodeId]: { ...nodeMappings, [targetField]: newValue } };
        
        const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, selectedNodeId, targetField, newValue, true);
        const updatedTrigger = updateNodeConfigInPipeline(pipelineData.trigger, selectedNodeId, targetField, newValue, true);
        updatePipeline({ ...pipelineData, pipeline: updatedPipeline, trigger: updatedTrigger });
        return newMappings;
      });
    }
  };

  const handleWrapFunction = (funcName: string, field: string, pathToWrap: string) => {
      if (!selectedNodeId) return;
      const currentMappings = fieldMappings[selectedNodeId] || {};
      const currentValue = currentMappings[field] || "";
      const inner = pathToWrap.slice(2, -2);
      const newPath = `{{${funcName}(${inner})}}`;
      const newValue = currentValue.replace(pathToWrap, newPath);
      
      const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, selectedNodeId, field, newValue, true);
      const updatedTrigger = updateNodeConfigInPipeline(pipelineData.trigger, selectedNodeId, field, newValue, true);
      updatePipeline({ ...pipelineData, pipeline: updatedPipeline, trigger: updatedTrigger });
  };

  const handleRemoveMapping = (nodeId: string, field: string, pathToRemove: string) => {
    setFieldMappings(prev => {
        const nodeMappings = { ...(prev[nodeId] || {}) };
        const currentValue = nodeMappings[field] || "";
        const newValue = currentValue.replace(pathToRemove, '').replace(/\s+/g, ' ').trim();
        if (newValue === "") delete nodeMappings[field]; else nodeMappings[field] = newValue;
        return { ...prev, [nodeId]: nodeMappings };
    });
    const currentNodeMappings = fieldMappings[nodeId] || {};
    const fullValue = currentNodeMappings[field] || "";
    const updatedValue = fullValue.replace(pathToRemove, '').replace(/\s+/g, ' ').trim();
    
    const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, nodeId, field, updatedValue === "" ? undefined : updatedValue, true);
    const updatedTrigger = updateNodeConfigInPipeline(pipelineData.trigger, nodeId, field, updatedValue === "" ? undefined : updatedValue, true);
    updatePipeline({ ...pipelineData, pipeline: updatedPipeline, trigger: updatedTrigger });
  };

  const toggleFolder = (path: string) => {
      const next = new Set(expandedPaths);
      if (next.has(path)) next.delete(path); else next.add(path);
      setExpandedPaths(next);
  };

  const renderTree = (data: any, path = 'root', depth = 0): React.ReactNode[] => {
      return Object.keys(data).map((key) => {
          const currentPath = `${path}.${key}`;
          const value = data[key];
          const isObject = typeof value === 'object' && value !== null;
          const isExpanded = expandedPaths.has(currentPath);
          return (
              <div key={currentPath}>
                  <button 
                      onClick={() => isObject ? toggleFolder(currentPath) : handleInjectPath(currentPath.replace('root.', '').split('.'))}
                      className={`flex items-center gap-1.5 text-base w-full py-1 pr-4 hover:bg-blue-500/10 transition-colors ${targetField ? 'cursor-crosshair' : 'cursor-pointer'} ${isDark ? 'text-zinc-400' : 'text-zinc-700'}`}
                      style={{ paddingLeft: `${depth * 12 + 16}px` }}
                  >
                      {isObject && (
                          <span className="transition-transform duration-200">
                              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </span>
                      )}
                      {!isObject && <span className="w-3" />}
                      {isObject ? <Folder size={15} className="text-blue-400/70" /> : <FileText size={15} className={isDark ? 'text-zinc-600' : 'text-zinc-500'} />}
                      <span className="truncate">{key}</span>
                  </button>
                  {isObject && isExpanded && (<div>{renderTree(value, currentPath, depth + 1)}</div>)}
              </div>
          );
      });
  };

  const selectedNode = selectedNodeId ? (findNode(pipelineData.pipeline, selectedNodeId) || findNode(pipelineData.trigger, selectedNodeId)) : null;
  const handleNodeSelect = (id: string) => { setSelectedNodeId(id); setTargetField(null); setActiveConfigTab('config'); };
  
  const updatePipeline = (newData: any, skipHistoryClear = false) => {
    setHistoryPast(prev => [...prev, pipelineData]);
    if (!skipHistoryClear) {
      setHistoryFuture([]);
    }
    
    const cleanNulls = (obj: any): any => {
      if (Array.isArray(obj)) {
        return obj.filter(item => item !== null && item !== undefined).map(cleanNulls);
      } else if (obj !== null && typeof obj === 'object') {
        return Object.fromEntries(
          Object.entries(obj)
            .filter(([_, v]) => v !== null && v !== undefined)
            .map(([k, v]) => [k, cleanNulls(v)])
        );
      }
      return obj;
    };

    const sanitizedData = cleanNulls(newData);
    setPipelineData(sanitizedData); 

    isInternalStateChangeRef.current = true;
    setYamlString(yaml.dump(sanitizedData, { skipInvalid: true, styles: { '!!null': 'empty' } })); 
  };

  const handleEditorChange = (value: string | undefined) => {
    const nextValue = value || '';
    setYamlString(nextValue);
    
    if (!nextValue || nextValue.trim() === '') { 
      setHistoryPast(prev => [...prev, pipelineData]);
      setPipelineData({version: '1.0', trigger: [], pipeline: [] }); 
      return; 
    }

    try { 
      const parsed = yaml.load(nextValue); 
      if (parsed && typeof parsed === 'object' && parsed !== null) {
        if (Array.isArray((parsed as any).pipeline)) {
          (parsed as any).pipeline = (parsed as any).pipeline.filter((n: any) => n !== null);
        }
        if (Array.isArray((parsed as any).trigger)) {
          (parsed as any).trigger = (parsed as any).trigger.filter((t: any) => t !== null);
        }
        
        setHistoryPast(prev => [...prev, pipelineData]);
        setHistoryFuture([]);
        setPipelineData(parsed);
      }
    } catch (e) {}
  };

  useEffect(() => {
    if (isInternalStateChangeRef.current) {
      isInternalStateChangeRef.current = false;
    }
  }, [yamlString]);

  const handleUndo = useCallback(() => {
    if (historyPast.length === 0) return;
    const previousState = historyPast[historyPast.length - 1];
    setHistoryPast(prev => prev.slice(0, prev.length - 1));
    setHistoryFuture(prev => [pipelineData, ...prev]);
    setPipelineData(previousState);
    isInternalStateChangeRef.current = true;
    setYamlString(yaml.dump(previousState, { skipInvalid: true }));
  }, [historyPast, pipelineData]);

  const handleRedo = useCallback(() => {
    if (historyFuture.length === 0) return;
    const nextState = historyFuture[0];
    setHistoryFuture(prev => prev.slice(1));
    setHistoryPast(prev => [...prev, pipelineData]);
    setPipelineData(nextState);
    isInternalStateChangeRef.current = true;
    setYamlString(yaml.dump(nextState, { skipInvalid: true }));
  }, [historyFuture, pipelineData]);

  const handleSave = () => {
    console.log('Pipeline payload written to database structure:', pipelineData);
  };

  const appendStepToParent = (nodes: any[], parentId: string, newStep: any): any[] => {
    return nodes.map(node => {
      if (node.id === parentId) {
        const currentSteps = Array.isArray(node.steps) ? node.steps : [];
        return { ...node, steps: [...currentSteps, newStep] };
      }
      if (Array.isArray(node.steps)) {
        return { ...node, steps: appendStepToParent(node.steps, parentId, newStep) };
      }
      return node;
    });
  };

  const appendStepAsSibling = (nodes: any[], targetSiblingId: string, newStep: any): any[] => {
    const index = nodes.findIndex(node => node.id === targetSiblingId);
    if (index !== -1) {
      const updatedNodes = [...nodes];
      updatedNodes.splice(index + 1, 0, newStep);
      return updatedNodes;
    }
    return nodes.map(node => {
      if (Array.isArray(node.steps)) {
        return { ...node, steps: appendStepAsSibling(node.steps, targetSiblingId, newStep) };
      }
      return node;
    });
  };

  const replaceStepInPipeline = (nodes: any[], targetId: string, newStep: any): any[] => {
    return nodes.map(node => {
      if (node.id === targetId) return { ...newStep, steps: node.steps };
      if (Array.isArray(node.steps)) return { ...node, steps: replaceStepInPipeline(node.steps, targetId, newStep) };
      return node;
    });
  };

  const deleteStepFromPipeline = (nodes: any[], targetId: string): any[] => {
    const filtered = nodes.filter(node => node.id !== targetId);
    return filtered.map(node => {
      if (Array.isArray(node.steps)) {
        return { ...node, steps: deleteStepFromPipeline(node.steps, targetId) };
      }
      return node;
    });
  };

  const addStep = (serviceName: string, category: string) => {
    const newStep = { id: `step_${Date.now()}`, service: serviceName };
    let newData = { ...pipelineData };
    const isTrigger = category === 'Triggers';
    const targetArray = isTrigger ? [...(pipelineData.trigger || [])] : [...(pipelineData.pipeline || [])];
    const targetExists = findNode(targetArray, insertTargetParentId);

    if (insertTargetParentId === 'root' || !targetExists) {
        if (isTrigger) newData.trigger = [...targetArray, newStep];
        else newData.pipeline = [...targetArray, newStep];
    } else {
        if (insertMode === 'sibling') {
            if (isTrigger) newData.trigger = appendStepAsSibling(targetArray, insertTargetParentId, newStep);
            else newData.pipeline = appendStepAsSibling(targetArray, insertTargetParentId, newStep);
        } else if (insertMode === 'replace') {
            if (isTrigger) newData.trigger = replaceStepInPipeline(targetArray, insertTargetParentId, newStep);
            else newData.pipeline = replaceStepInPipeline(targetArray, insertTargetParentId, newStep);
        } else {
            if (isTrigger) newData.trigger = appendStepToParent(targetArray, insertTargetParentId, newStep);
            else newData.pipeline = appendStepToParent(targetArray, insertTargetParentId, newStep);
        }
    }
    updatePipeline(newData);
    setIsModalOpen(false);
    setSelectedApp(null); 
    setInsertTargetParentId('root');
    setInsertMode('child');
    setSearchQuery('');
  };

  const handleNodeDelete = (id: string) => {
    const currentPipeline = Array.isArray(pipelineData.pipeline) ? pipelineData.pipeline : [];
    const currentTrigger = Array.isArray(pipelineData.trigger) ? pipelineData.trigger : [];
    const updatedPipeline = deleteStepFromPipeline(currentPipeline, id);
    const updatedTrigger = deleteStepFromPipeline(currentTrigger, id);
    if (selectedNodeId === id) { setSelectedNodeId(null); }
    updatePipeline({ ...pipelineData, pipeline: updatedPipeline, trigger: updatedTrigger });
  };

  const handleZoom = (direction: 'in' | 'out') => {
    if (activePanel === 'builder') setBuilderZoom(prev => direction === 'in' ? Math.min(2, prev + 0.1) : Math.max(0.5, prev - 0.1));
    else if (activePanel === 'terminal') setTerminalFontSize(prev => direction === 'in' ? Math.min(30, prev + 1) : Math.max(8, prev - 1));
    else setEditorFontSize(prev => direction === 'in' ? Math.min(30, prev + 1) : Math.max(8, prev - 1));
  };

  const startResizing = useCallback(() => setIsResizing(true), []);
  const stopResizing = useCallback(() => setIsResizing(false), []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;
      const newWidth = window.innerWidth - e.clientX;
      if (newWidth > 200 && newWidth < 1000) setEditorWidth(newWidth);
    };
    if (isResizing) { window.addEventListener('mousemove', handleMouseMove); window.addEventListener('mouseup', stopResizing); }
    return () => { window.removeEventListener('mousemove', handleMouseMove); window.removeEventListener('mouseup', stopResizing); };
  }, [isResizing, stopResizing]);

  return (
    <div className={`flex flex-col h-screen w-full transition-colors ${isDark ? 'bg-[#050505] text-white' : 'bg-white text-black'}`}>
      {selectedNodeId && (
        <ConfigurationModal 
          selectedNodeId={selectedNodeId}
          selectedNode={selectedNode}
          onClose={() => { setSelectedNodeId(null); setTargetField(null); }}
          activeConfigTab={activeConfigTab}
          setActiveConfigTab={setActiveConfigTab}
          activeNodeSchema={activeNodeSchema}
          nodeConfigs={nodeConfigs}
          handleConfigChange={handleConfigChange}
          fieldMappings={fieldMappings}
          setFieldMappings={setFieldMappings}
          targetField={targetField}
          setTargetField={setTargetField}
          renderTree={renderTree}
          handleWrapFunction={handleWrapFunction}
          handleRemoveMapping={handleRemoveMapping}
          AVAILABLE_FUNCTIONS={AVAILABLE_FUNCTIONS}
          getServiceColor={getServiceColor}
          getServiceIcon={getServiceIcon}
          getDisplayService={getDisplayService}
          SAMPLE_PAYLOAD={SAMPLE_PAYLOAD}
          theme={theme}
          onUndo={handleUndo}
          onRedo={handleRedo}
          canUndo={historyPast.length > 0}
          canRedo={historyFuture.length > 0}
        />
      )}

      <AppSelectionModal 
        isOpen={isModalOpen}
        isDark={isDark}
        onClose={() => { 
          setIsModalOpen(false); 
          setInsertTargetParentId('root'); 
          setInsertMode('child'); 
        }}
        onAddStep={addStep}
        appCategories={appCategories}
      />
      <div className="flex flex-1 overflow-hidden relative">
        
        {/* REFINED SIDEBAR IMPLEMENTATION */}
        <Sidebar 
          isSidebarExpanded={isSidebarExpanded} 
          setIsSidebarExpanded={setIsSidebarExpanded} 
          isDark={isDark}
          clients={systemState || []}
          onSelectAutomation={handleSelectAutomation}
          onSelectScript={handleSelectScript}
          fileTree={fileTree}
          onSelectFile={handleSelectFile}
        />

        <VisualBuilder 
          isSidebarExpanded={isSidebarExpanded}
          setIsSidebarExpanded={setIsSidebarExpanded}
          isDark={isDark}
          setIsModalOpen={setIsModalOpen}
          setInsertTargetParentId={setInsertTargetParentId}
          setInsertMode={setInsertMode}
          setActivePanel={setActivePanel}
          setSelectedNodeId={setSelectedNodeId}
          builderZoom={builderZoom}
          viewMode={viewMode}
          editorLayout={editorLayout}
          pipelineData={pipelineData}
          selectedNodeId={selectedNodeId}
          handleNodeDelete={handleNodeDelete}
          handleNodeSelect={handleNodeSelect}
          getServiceColor={getServiceColor}
          getServiceIcon={getServiceIcon}
          getDisplayService={getDisplayService}
          nodeConfigs={nodeConfigs}
        />

        {editorLayout === 'both' && (
          <div onClick={(e) => e.stopPropagation()} className={`w-1 cursor-col-resize flex-shrink-0 transition-colors ${isResizing ? 'bg-blue-500' : isDark ? 'bg-white/5 hover:bg-white/10' : 'bg-gray-200 hover:bg-gray-300'}`} onMouseDown={startResizing} />
        )}

        {editorLayout !== 'visual' && (
          <section 
            onClick={() => setActivePanel('editor')}
            style={{ width: editorLayout === 'monaco' ? '100%' : editorWidth }} 
            className={`border-l min-w-0 transition-colors ${activePanel === 'editor' ? 'ring-1 ring-blue-500/50' : ''} flex flex-col ${isDark ? 'bg-[#080808] border-white/5' : 'bg-white border-gray-200'}`}
          >
            <div className="h-10 w-full border-b border-white/5 flex items-center px-4 justify-between flex-shrink-0">
                <div className="flex items-center gap-6 h-full">
                  {editorLayout === 'monaco' && (
                    <button onClick={() => setIsSidebarExpanded(!isSidebarExpanded)} className="text-zinc-500 hover:text-black dark:hover:text-white mr-1">
                      {isSidebarExpanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
                    </button>
                  )}
                  <button onClick={() => setActiveRightTab('yaml')} className={`text-xs font-medium h-full flex items-center border-b-2 transition-colors ${activeRightTab === 'yaml' ? 'text-blue-500 border-blue-500' : 'text-zinc-500 border-transparent hover:text-zinc-300'}`}>{selectedFileName}</button>
                  <button onClick={() => setIsTerminalOpen(!isTerminalOpen)} className={`text-xs font-medium h-full flex items-center border-b-2 transition-colors ${isTerminalOpen ? 'text-blue-500 border-blue-500' : 'text-zinc-500 border-transparent hover:text-zinc-300'}`}>Terminal</button>
                </div>
            </div>

            <div className="flex-1 overflow-hidden flex flex-col">
                <Editor 
                  height={isTerminalOpen ? `calc(100% - ${terminalHeight}px)` : "100%"} 
                  theme={isDark ? "vs-dark" : "light"} 
                  language="yaml" 
                  value={yamlString} 
                  onChange={handleEditorChange}
                  options={{ fontSize: editorFontSize }}
                />
                
                {isTerminalOpen && (
                  <div 
                    onClick={(e) => { e.stopPropagation(); setActivePanel('terminal'); }}
                    className={`border-t flex flex-col ${isDark ? 'bg-[#0d0d0d] border-white/5' : 'bg-zinc-50 border-gray-200'}`}
                    style={{ height: isTerminalMaximized ? 'calc(100vh - 40px)' : terminalHeight }}
                  >
                    <div onMouseDown={startResizingTerminal} className="h-1 w-full cursor-row-resize hover:bg-blue-500/50 transition-colors" />
                    <div className={`h-8 flex items-center justify-between px-4 ${isDark ? 'bg-[#151515]' : 'bg-zinc-100'}`}>
                      <div className="flex items-center gap-2 text-[10px] uppercase font-bold tracking-wider text-zinc-500">
                          <Terminal size={12} /> Log/Terminal
                      </div>
                      <div className="flex items-center gap-2">
                        <button onClick={() => setIsTerminalMaximized(!isTerminalMaximized)} className="text-zinc-500 hover:text-black dark:hover:text-white">
                          {isTerminalMaximized ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                        </button>
                        <button onClick={() => { setIsTerminalOpen(false); }} className="text-zinc-500 hover:text-black dark:hover:text-white"><X size={12} /></button>
                      </div>
                    </div>
                    <div className="flex-1 p-3 overflow-y-auto font-mono leading-relaxed select-text cursor-text" style={{ fontSize: `${terminalFontSize}px` }}>
                      {logs.map((log, idx) => (
                        <div key={idx} className={`mb-0.5 ${log.includes('[ERROR]') ? 'text-red-500' : log.includes('[WARN]') ? 'text-amber-500' : log.includes('[INFO]') ? 'text-emerald-500' : isDark ? 'text-zinc-300' : 'text-zinc-700'}`}>
                           {log}
                        </div>
                      ))}
                      <div className="flex items-center gap-1 text-zinc-500">
                          <span>$</span>
                          <div className="w-2 h-4 bg-zinc-500 animate-pulse" />
                      </div>
                    </div>
                  </div>
                )}
            </div>
          </section>
        )}

        <FloatingActionBar 
          isActionExpanded={isActionExpanded}
          setIsActionExpanded={setIsActionExpanded}
          isDark={isDark}
          aiInput={aiInput}
          setAiInput={setAiInput}
          isAiPanelVisible={isAiPanelVisible}
          setIsAiPanelVisible={setIsAiPanelVisible}
          cycleEditorLayout={cycleEditorLayout}
          editorLayout={editorLayout}
          setViewMode={setViewMode}
          viewMode={viewMode}
          handleZoom={handleZoom}
          activePanel={activePanel}
          builderZoom={builderZoom}
          terminalFontSize={terminalFontSize}
          editorFontSize={editorFontSize}
          setIsTerminalOpen={setIsTerminalOpen}
          onUndo={handleUndo}
          onRedo={handleRedo}
          onSave={handleSave}
          canUndo={historyPast.length > 0}
          canRedo={historyFuture.length > 0}
        />
      </div>
    </div>
  );
};

export default BuilderPage;