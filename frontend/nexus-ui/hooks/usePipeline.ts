import { useState, useRef, useCallback } from 'react';
import yaml from 'js-yaml';
import { INITIAL_DATA } from '@/components/Pipeline/PipelineUtils';

export const usePipeline = () => {
  const [pipelineData, setPipelineData] = useState(INITIAL_DATA);
  const [yamlString, setYamlString] = useState(yaml.dump(INITIAL_DATA, { skipInvalid: true }));
  const [historyPast, setHistoryPast] = useState<any[]>([]);
  const [historyFuture, setHistoryFuture] = useState<any[]>([]);
  const isInternalStateChangeRef = useRef(false);

  const updatePipeline = (newData: any, skipHistoryClear = false) => {
    setHistoryPast(prev => [...prev, pipelineData]);
    if (!skipHistoryClear) setHistoryFuture([]);
    
    const cleanNulls = (obj: any): any => {
      if (Array.isArray(obj)) return obj.filter(item => item !== null && item !== undefined).map(cleanNulls);
      else if (obj !== null && typeof obj === 'object') {
        return Object.fromEntries(Object.entries(obj).filter(([_, v]) => v !== null && v !== undefined).map(([k, v]) => [k, cleanNulls(v)]));
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
      setPipelineData({ trigger: [], pipeline: [] }); 
      return; 
    }
    try { 
      const parsed = yaml.load(nextValue); 
      if (parsed && typeof parsed === 'object') {
        setHistoryPast(prev => [...prev, pipelineData]);
        setHistoryFuture([]);
        setPipelineData(parsed);
      }
    } catch (e) { /* silent catch */ }
  };

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

  return { pipelineData, yamlString, setPipelineData, updatePipeline, handleEditorChange, handleUndo, handleRedo, historyPast, historyFuture };
};