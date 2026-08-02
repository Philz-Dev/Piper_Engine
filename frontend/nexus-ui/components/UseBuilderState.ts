"use client";
import { useState, useEffect, useCallback } from 'react';
import yaml from 'js-yaml';
import { 
  INITIAL_DATA, 
  fetchEngineSchema, 
  AVAILABLE_APPS 
} from '@/components/Pipeline/PipelineUtils';

export const useBuilderState = (theme: 'dark' | 'light' | null | undefined) => {
  const isDark = theme !== 'light';
  
  const [pipelineData, setPipelineData] = useState(INITIAL_DATA);
  const [yamlString, setYamlString] = useState(yaml.dump(INITIAL_DATA));
  
  // Global Structural History
  const [historyPast, setHistoryPast] = useState<any[]>([]);
  const [historyFuture, setHistoryFuture] = useState<any[]>([]);

  // Configuration Modal Specific Undo/Redo Stacks
  const [configHistoryPast, setConfigHistoryPast] = useState<any[]>([]);
  const [configHistoryFuture, setConfigHistoryFuture] = useState<any[]>([]);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSidebarExpanded, setIsSidebarExpanded] = useState(true);
  const [activeRightTab, setActiveRightTab] = useState('yaml');
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeNodeSchema, setActiveNodeSchema] = useState<any>(null);
  const [aiInput, setAiInput] = useState('');
  const [isAiPanelVisible, setIsAiPanelVisible] = useState(false);
  const [isActionExpanded, setIsActionExpanded] = useState(true);
  
  const [insertTargetParentId, setInsertTargetParentId] = useState<string | 'root'>('root');
  const [insertMode, setInsertMode] = useState<'child' | 'sibling'>('child');
  
  // Terminal/Log State
  const [isTerminalOpen, setIsTerminalOpen] = useState(true);
  const [terminalHeight, setTerminalHeight] = useState(200);
  const [isResizingTerminal, setIsResizingTerminal] = useState(false);
  const [isTerminalMaximized, setIsTerminalMaximized] = useState(false);
  const [terminalFontSize, setTerminalFontSize] = useState(11);
  
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

  const findNode = useCallback((nodes: any[], id: string): any => {
    for (const node of nodes) {
      if (node.id === id) return node;
      if (Array.isArray(node.steps)) {
        const found = findNode(node.steps, id);
        if (found) return found;
      }
    }
    return null;
  }, []);

  useEffect(() => {
    if (selectedNodeId) {
      const node = findNode(pipelineData.pipeline, selectedNodeId);
      if (node) {
        setFieldMappings(prev => ({ ...prev, [selectedNodeId]: { ...(node.input || {}) } }));
        fetchEngineSchema(node.service).then(schema => {
          setActiveNodeSchema(schema);
          const localConfigs: Record<string, any> = {};
          Object.keys(schema).forEach(key => {
            localConfigs[key] = node[key] ?? schema[key].default ?? ""; 
          });
          localConfigs['condition'] = node.condition || "";
          setNodeConfigs(prev => ({ ...prev, [selectedNodeId]: localConfigs }));
        });
      }
    }
  }, [pipelineData, selectedNodeId, findNode]);

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

  const syncNodePropertiesBackToPipeline = useCallback((nodes: any[], targetId: string, configs: Record<string, any>, mappings: Record<string, any>): any[] => {
    return nodes.map(node => {
      if (node.id === targetId) {
        const newNode = { ...node };
        if (activeNodeSchema) {
          Object.keys(activeNodeSchema).forEach(key => { delete newNode[key]; });
        }
        delete newNode['condition'];
        Object.entries(configs).forEach(([key, val]) => {
          if (val !== undefined && val !== null && val !== "") newNode[key] = val;
        });
        if (mappings && Object.keys(mappings).length > 0) {
          newNode.input = { ...mappings };
        } else {
          delete newNode.input;
        }
        return newNode;
      }
      if (Array.isArray(node.steps)) return { ...node, steps: syncNodePropertiesBackToPipeline(node.steps, targetId, configs, mappings) };
      return node;
    });
  }, [activeNodeSchema]);

  const updateConfigState = (currentNodeId: string, nextConfigs: Record<string, any>, nextMappings: Record<string, any>) => {
    const currentConfigSnapshot = nodeConfigs[currentNodeId] || {};
    const currentMappingSnapshot = fieldMappings[currentNodeId] || {};
    setConfigHistoryPast(prev => [...prev, { nodeId: currentNodeId, configs: currentConfigSnapshot, mappings: currentMappingSnapshot }]);
    setConfigHistoryFuture([]);
    setHistoryPast(prev => [...prev, pipelineData]);
    setHistoryFuture([]);
  };

  const handleConfigChange = (field: string, value: any) => {
    if (!selectedNodeId) return;
    const nextConfigs = { ...(nodeConfigs[selectedNodeId] || {}), [field]: value };
    const currentMappings = fieldMappings[selectedNodeId] || {};
    updateConfigState(selectedNodeId, nextConfigs, currentMappings);
    setNodeConfigs(prev => ({ ...prev, [selectedNodeId]: nextConfigs }));
    const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, selectedNodeId, field, value, false);
    setPipelineData({ ...pipelineData, pipeline: updatedPipeline });
    setYamlString(yaml.dump({ ...pipelineData, pipeline: updatedPipeline }));
  };

  const handleInjectPath = (path: string[]) => {
    if (selectedNodeId && targetField) {
      const pathString = `{{${path.join('.')}}}`;
      const nodeMappings = fieldMappings[selectedNodeId] || {};
      const existingValue = nodeMappings[targetField] || "";
      const newValue = existingValue ? `${existingValue} ${pathString}` : pathString;
      const nextMappings = { ...nodeMappings, [targetField]: newValue };
      const currentConfigs = nodeConfigs[selectedNodeId] || {};
      updateConfigState(selectedNodeId, currentConfigs, nextMappings);
      setFieldMappings(prev => ({ ...prev, [selectedNodeId]: nextMappings }));
      const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, selectedNodeId, targetField, newValue, true);
      setPipelineData({ ...pipelineData, pipeline: updatedPipeline });
      setYamlString(yaml.dump({ ...pipelineData, pipeline: updatedPipeline }));
    }
  };

  const handleWrapFunction = (funcName: string, field: string, pathToWrap: string) => {
      if (!selectedNodeId) return;
      const currentMappings = fieldMappings[selectedNodeId] || {};
      const currentValue = currentMappings[field] || "";
      const inner = pathToWrap.slice(2, -2);
      const newPath = `{{${funcName}(${inner})}}`;
      const newValue = currentValue.replace(pathToWrap, newPath);
      const nextMappings = { ...currentMappings, [field]: newValue };
      const currentConfigs = nodeConfigs[selectedNodeId] || {};
      updateConfigState(selectedNodeId, currentConfigs, nextMappings);
      setFieldMappings(prev => ({ ...prev, [selectedNodeId]: nextMappings }));
      const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, selectedNodeId, field, newValue, true);
      setPipelineData({ ...pipelineData, pipeline: updatedPipeline });
      setYamlString(yaml.dump({ ...pipelineData, pipeline: updatedPipeline }));
  };

  const handleRemoveMapping = (nodeId: string, field: string, pathToRemove: string) => {
    if (!nodeId) return;
    const currentMappings = fieldMappings[nodeId] || {};
    const currentValue = currentMappings[field] || "";
    const newValue = currentValue.replace(pathToRemove, '').replace(/\s+/g, ' ').trim();
    const nextMappings = { ...currentMappings };
    if (newValue === "") delete nextMappings[field]; else nextMappings[field] = newValue;
    const currentConfigs = nodeConfigs[nodeId] || {};
    updateConfigState(nodeId, currentConfigs, nextMappings);
    setFieldMappings(prev => ({ ...prev, [nodeId]: nextMappings }));
    const updatedPipeline = updateNodeConfigInPipeline(pipelineData.pipeline, nodeId, field, newValue === "" ? undefined : newValue, true);
    setPipelineData({ ...pipelineData, pipeline: updatedPipeline });
    setYamlString(yaml.dump({ ...pipelineData, pipeline: updatedPipeline }));
  };

  const toggleFolder = (path: string) => {
      const next = new Set(expandedPaths);
      if (next.has(path)) next.delete(path); else next.add(path);
      setExpandedPaths(next);
  };

  const selectedNode = selectedNodeId ? findNode(pipelineData.pipeline, selectedNodeId) : null;
  
  const handleNodeSelect = (id: string) => { 
    setSelectedNodeId(id); 
    setTargetField(null); 
    setActiveConfigTab('config'); 
    setConfigHistoryPast([]);
    setConfigHistoryFuture([]);
  };
  
  const updatePipeline = (newData: any, skipHistoryClear = false) => {
    if (JSON.stringify(pipelineData) === JSON.stringify(newData)) return;
    setHistoryPast(prev => [...prev, pipelineData]);
    if (!skipHistoryClear) {
      setHistoryFuture([]);
    }
    setPipelineData(newData); 
    setYamlString(yaml.dump(newData)); 
  };

  const handleEditorChange = (value: string | undefined) => {
    setYamlString(value || '');
    if (!value || value.trim() === '') { updatePipeline({ trigger: [], pipeline: [] }); return; }
    try { 
      const parsed = yaml.load(value); 
      if (parsed && typeof parsed === 'object') updatePipeline(parsed); 
    } catch (e) {}
  };

  const handleConfigUndo = useCallback(() => {
    if (configHistoryPast.length === 0 || !selectedNodeId) return;
    const previousSnapshot = configHistoryPast[configHistoryPast.length - 1];
    if (previousSnapshot.nodeId !== selectedNodeId) return;

    const currentConfigs = nodeConfigs[selectedNodeId] || {};
    const currentMappings = fieldMappings[selectedNodeId] || {};

    setConfigHistoryPast(prev => prev.slice(0, prev.length - 1));
    setConfigHistoryFuture(prev => [{ nodeId: selectedNodeId, configs: currentConfigs, mappings: currentMappings }, ...prev]);
    setNodeConfigs(prev => ({ ...prev, [selectedNodeId]: previousSnapshot.configs }));
    setFieldMappings(prev => ({ ...prev, [selectedNodeId]: previousSnapshot.mappings }));

    const updatedPipeline = syncNodePropertiesBackToPipeline(pipelineData.pipeline, selectedNodeId, previousSnapshot.configs, previousSnapshot.mappings);
    const updatedState = { ...pipelineData, pipeline: updatedPipeline };
    setHistoryPast(prev => [...prev, pipelineData]);
    setPipelineData(updatedState);
    setYamlString(yaml.dump(updatedState));
  }, [configHistoryPast, selectedNodeId, nodeConfigs, fieldMappings, pipelineData, syncNodePropertiesBackToPipeline]);

  const handleConfigRedo = useCallback(() => {
    if (configHistoryFuture.length === 0 || !selectedNodeId) return;
    const nextSnapshot = configHistoryFuture[0];
    if (nextSnapshot.nodeId !== selectedNodeId) return;

    const currentConfigs = nodeConfigs[selectedNodeId] || {};
    const currentMappings = fieldMappings[selectedNodeId] || {};

    setConfigHistoryFuture(prev => prev.slice(1));
    setConfigHistoryPast(prev => [...prev, { nodeId: selectedNodeId, configs: currentConfigs, mappings: currentMappings }]);
    setNodeConfigs(prev => ({ ...prev, [selectedNodeId]: nextSnapshot.configs }));
    setFieldMappings(prev => ({ ...prev, [selectedNodeId]: nextSnapshot.mappings }));

    const updatedPipeline = syncNodePropertiesBackToPipeline(pipelineData.pipeline, selectedNodeId, nextSnapshot.configs, nextSnapshot.mappings);
    const updatedState = { ...pipelineData, pipeline: updatedPipeline };
    setHistoryPast(prev => [...prev, pipelineData]);
    setPipelineData(updatedState);
    setYamlString(yaml.dump(updatedState));
  }, [configHistoryFuture, selectedNodeId, nodeConfigs, fieldMappings, pipelineData, syncNodePropertiesBackToPipeline]);

  const handleUndo = useCallback(() => {
    if (historyPast.length === 0) return;
    const previousState = historyPast[historyPast.length - 1];
    setHistoryPast(prev => prev.slice(0, prev.length - 1));
    setHistoryFuture(prev => [pipelineData, ...prev]);
    setPipelineData(previousState);
    setYamlString(yaml.dump(previousState));
  }, [historyPast, pipelineData]);

  const handleRedo = useCallback(() => {
    if (historyFuture.length === 0) return;
    const nextState = historyFuture[0];
    setHistoryFuture(prev => prev.slice(1));
    setHistoryPast(prev => [...prev, pipelineData]);
    setPipelineData(nextState);
    setYamlString(yaml.dump(nextState));
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

  const deleteStepFromPipeline = (nodes: any[], targetId: string): any[] => {
    const filtered = nodes.filter(node => node.id !== targetId);
    return filtered.map(node => {
      if (Array.isArray(node.steps)) {
        return { ...node, steps: deleteStepFromPipeline(node.steps, targetId) };
      }
      return node;
    });
  };

  const addStep = (serviceName: string) => {
    const currentPipeline = Array.isArray(pipelineData.pipeline) ? pipelineData.pipeline : [];
    const newStep = { id: `step_${Date.now()}`, service: serviceName };
    
    if (insertTargetParentId === 'root') {
      updatePipeline({ ...pipelineData, pipeline: [...currentPipeline, newStep] });
    } else if (insertMode === 'sibling') {
      const updatedPipeline = appendStepAsSibling(currentPipeline, insertTargetParentId, newStep);
      updatePipeline({ ...pipelineData, pipeline: updatedPipeline });
    } else {
      const updatedPipeline = appendStepToParent(currentPipeline, insertTargetParentId, newStep);
      updatePipeline({ ...pipelineData, pipeline: updatedPipeline });
    }
    
    setIsModalOpen(false);
    setInsertTargetParentId('root');
    setInsertMode('child');
  };

  const handleNodeDelete = (id: string) => {
    const currentPipeline = Array.isArray(pipelineData.pipeline) ? pipelineData.pipeline : [];
    const updatedPipeline = deleteStepFromPipeline(currentPipeline, id);
    if (selectedNodeId === id) {
      setSelectedNodeId(null);
    }
    updatePipeline({ ...pipelineData, pipeline: updatedPipeline });
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

  return {
    isDark, pipelineData, yamlString, isModalOpen, setIsModalOpen, isSidebarExpanded, setIsSidebarExpanded,
    activeRightTab, setActiveRightTab, selectedNodeId, setSelectedNodeId, activeNodeSchema, aiInput, setAiInput,
    isAiPanelVisible, setIsAiPanelVisible, isActionExpanded, setIsActionExpanded, setInsertTargetParentId,
    setInsertMode, isTerminalOpen, setIsTerminalOpen, terminalHeight, startResizingTerminal, isTerminalMaximized,
    setIsTerminalMaximized, terminalFontSize, logs, fieldMappings, setFieldMappings, nodeConfigs, activeConfigTab,
    setActiveConfigTab, targetField, setTargetField, activePanel, setActivePanel, builderZoom, editorFontSize,
    viewMode, setViewMode, editorWidth, isResizing, editorLayout, cycleEditorLayout, handleConfigChange,
    handleInjectPath, handleWrapFunction, handleRemoveMapping, toggleFolder, selectedNode, handleNodeSelect,
    handleEditorChange, handleConfigUndo, handleConfigRedo, handleUndo, handleRedo, handleSave, addStep,
    handleNodeDelete, handleZoom, startResizing, insertMode, AVAILABLE_APPS
  };
};