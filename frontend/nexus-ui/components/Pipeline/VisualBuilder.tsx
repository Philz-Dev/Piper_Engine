"use client";
import React, { useState, useRef, useEffect, useMemo } from 'react';
import { ChevronLeft, ChevronRight, Box, Settings, Plus } from 'lucide-react';
import { TreeRenderer, GraphRenderer } from '@/components/Pipeline/PipelineRenderer';
import { TriggerRenderer } from '@/components/Pipeline/TriggerRenderer'

export const VisualBuilder: React.FC<VisualBuilderProps> = ({
  isSidebarExpanded,
  setIsSidebarExpanded,
  isDark,
  setIsModalOpen,
  setInsertTargetParentId,
  setInsertMode,
  setActivePanel,
  setSelectedNodeId,
  builderZoom,
  viewMode,
  editorLayout,
  pipelineData,
  selectedNodeId,
  handleNodeDelete,
  handleNodeReplace,
  handleNodeSelect,
  getServiceColor,
  getServiceIcon,
}) => {
  const sequenceMap = useMemo(() => {
    const map: Record<string, number> = {};
    let counter = 1;

    const traverse = (steps: any[]) => {
      if (!Array.isArray(steps)) return;
      steps.forEach((step) => {
        map[step.id] = counter++;
        if (step.steps) traverse(step.steps);
      });
    };

    traverse(pipelineData?.pipeline || []);
    return map;
  }, [pipelineData]);

  const onReplaceInitiated = (id: string) => {
    setInsertTargetParentId(id);
    setInsertMode('replace'); 
    setIsModalOpen(true);
  };

  const [offsets, setOffsets] = useState<Record<string, { x: number; y: number }>>({
    tree: { x: 0, y: 0 },
    graph: { x: 0, y: 0 }
  });
  
  const [isPanning, setIsPanning] = useState(false);
  const panStartRef = useRef({ x: 0, y: 0 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const contentInnerRef = useRef<HTMLDivElement>(null);
  
  const targetOffsetRef = useRef({ x: 0, y: 0 });
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    targetOffsetRef.current = offsets[viewMode] || { x: 0, y: 0 };
  }, [viewMode]);

  const clampOffset = (x: number, y: number): { x: number; y: number } => {
    if (!canvasRef.current || !contentInnerRef.current) return { x, y };
    const viewportWidth = canvasRef.current.clientWidth;
    const viewportHeight = canvasRef.current.clientHeight;
    const contentWidth = (contentInnerRef.current.offsetWidth + 160) * builderZoom;
    const contentHeight = (contentInnerRef.current.offsetHeight + 160) * builderZoom;
    const restraintBuffer = editorLayout === 'visual' ? 100 : 240;
    
    let minX = viewMode === 'tree' ? 0 : Math.min(0, viewportWidth - contentWidth - restraintBuffer);
    let maxX = viewMode === 'tree' ? 0 : restraintBuffer;
    let minY = Math.min(0, viewportHeight - contentHeight - 140);
    let maxY = 140;

    return {
      x: viewMode === 'tree' ? 0 : Math.min(Math.max(x, minX), maxX),
      y: Math.min(Math.max(y, minY), maxY),
    };
  };

  useEffect(() => {
    const updateInterpolation = () => {
      const current = offsets[viewMode];
      const dx = targetOffsetRef.current.x - current.x;
      const dy = targetOffsetRef.current.y - current.y;
      
      if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01) {
        setOffsets(prev => ({
          ...prev,
          [viewMode]: {
            x: current.x + dx * 0.15,
            y: current.y + dy * 0.15
          }
        }));
      }
      rafRef.current = requestAnimationFrame(updateInterpolation);
    };
    rafRef.current = requestAnimationFrame(updateInterpolation);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [viewMode, offsets]);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest('button') || target.closest('.node-interactive-element')) return;
    setIsPanning(true);
    targetOffsetRef.current = { ...offsets[viewMode] };
    panStartRef.current = {
      x: e.clientX - offsets[viewMode].x * builderZoom,
      y: e.clientY - offsets[viewMode].y * builderZoom,
    };
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isPanning) return;
      const rawX = (e.clientX - panStartRef.current.x) / builderZoom;
      const rawY = (e.clientY - panStartRef.current.y) / builderZoom;
      targetOffsetRef.current = clampOffset(rawX, rawY);
    };
    const handleMouseUp = () => setIsPanning(false);
    if (isPanning) { window.addEventListener('mousemove', handleMouseMove); window.addEventListener('mouseup', handleMouseUp); }
    return () => { window.removeEventListener('mousemove', handleMouseMove); window.removeEventListener('mouseup', handleMouseUp); };
  }, [isPanning, viewMode, builderZoom]);

  useEffect(() => {
    const canvasElement = canvasRef.current;
    if (!canvasElement) return;
    const handleWheelPan = (e: WheelEvent) => {
      e.preventDefault();
      const rawX = targetOffsetRef.current.x - e.deltaX / builderZoom;
      const rawY = targetOffsetRef.current.y - e.deltaY / builderZoom;
      targetOffsetRef.current = clampOffset(rawX, rawY);
    };
    canvasElement.addEventListener('wheel', handleWheelPan, { passive: false });
    return () => canvasElement.removeEventListener('wheel', handleWheelPan);
  }, [viewMode, builderZoom]);

  const isEmpty = (!pipelineData?.trigger || pipelineData.trigger.length === 0) && (!pipelineData?.pipeline || pipelineData.pipeline.length === 0);

  return (
    <main onClick={() => { setActivePanel('builder'); setSelectedNodeId(null); }} className={`flex flex-col flex-1 h-full min-w-0 overflow-hidden transition-colors ${editorLayout === 'monaco' ? 'hidden' : ''} ${!React.isValidElement(pipelineData) ? 'ring-1 ring-blue-500/50' : ''}`}>
      <div className={`h-10 w-full border-b flex items-center px-6 flex-shrink-0 justify-between z-10 ${isDark ? 'bg-[#080808] border-white/5' : 'bg-white border-gray-200'}`}>
        <div className="flex items-center">
           <button onClick={() => setIsSidebarExpanded(!isSidebarExpanded)} className="text-zinc-500 hover:text-black dark:hover:text-white mr-4">
            {isSidebarExpanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
          </button>
          <span className={`text-xs font-medium ${isDark ? 'text-white' : 'text-black'}`}>pipeline.yaml</span>
        </div>
        <div className="flex items-center gap-6">
           <button onClick={() => { setInsertTargetParentId('root'); setInsertMode('child'); setIsModalOpen(true); }}><Box size={16} className="text-zinc-500 hover:text-blue-500" /></button>
           <Settings size={16} className="text-zinc-500" />
        </div>
      </div>

      <div ref={canvasRef} onMouseDown={handleMouseDown} className={`flex-1 w-full h-full overflow-hidden relative grid place-items-start select-none ${isPanning ? 'cursor-grabbing' : 'cursor-grab'}`}>
        {isEmpty && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-20 pointer-events-none">
            <button 
              onClick={(e) => { e.stopPropagation(); setInsertTargetParentId('root'); setInsertMode('child'); setIsModalOpen(true); }} 
              className={`pointer-events-auto flex items-center justify-center w-16 h-16 rounded-full shadow-2xl transition-all duration-500 ease-in-out transform hover:rotate-180 hover:scale-110 ${isDark ? 'bg-blue-600' : 'bg-blue-500'} text-white`}
            >
              <Plus size={32} />
            </button>
          </div>
        )}

        <div className="p-20 flex flex-col items-start justify-start min-w-full min-h-full origin-top-left" style={{ transform: `translate3d(${offsets[viewMode].x}px, ${offsets[viewMode].y}px, 0) scale(${builderZoom})`, willChange: 'transform' }}>
          <div ref={contentInnerRef} className={`flex mb-6 w-full ${viewMode === 'graph' ? 'flex-col items-center justify-start' : 'flex-col items-start'}`}>
             {(Array.isArray(pipelineData?.trigger) ? pipelineData.trigger : []).filter(Boolean).map((trig: any) => (
               <TriggerRenderer 
                 key={trig.id} 
                 trigger={trig} 
                 isDark={isDark}
                 isSelected={selectedNodeId === trig.id}
                 getServiceColor={getServiceColor}
                 getServiceIcon={getServiceIcon}
                 onSelect={handleNodeSelect}
                 // Added interaction handlers to Triggers
                 onAddSibling={(id) => { setInsertTargetParentId(id); setInsertMode('sibling'); setIsModalOpen(true); }}
                 onDelete={handleNodeDelete}
                 onReplace={onReplaceInitiated}
               />
             ))}

            {viewMode === 'tree' ? (
              <div className="w-full max-w-fit">
                <div className={`ml-4 pl-4 border-l ${isDark ? 'border-zinc-800' : 'border-zinc-200'}`}>
                  {(Array.isArray(pipelineData?.pipeline) ? pipelineData.pipeline : []).filter(Boolean).map((step: any) => (
                    <TreeRenderer 
                      key={step.id} 
                      step={step} 
                      sequenceMap={sequenceMap}
                      onAdd={(id) => { setInsertTargetParentId(id); setInsertMode('child'); setIsModalOpen(true); }} 
                      onAddSibling={(id) => { setInsertTargetParentId(id); setInsertMode('sibling'); setIsModalOpen(true); }}
                      onDelete={handleNodeDelete}
                      onReplace={onReplaceInitiated}
                      onSelect={handleNodeSelect} 
                      selectedId={selectedNodeId} 
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center mt-4">
                {(Array.isArray(pipelineData?.pipeline) ? pipelineData.pipeline : []).filter(Boolean).map((step: any, idx: number, arr: any[]) => (
                  <React.Fragment key={step.id}>
                    <GraphRenderer 
                      step={step}
                      sequenceMap={sequenceMap}
                      index={idx}
                      onAdd={(id) => { setInsertTargetParentId(id); setInsertMode('child'); setIsModalOpen(true); }} 
                      onAddSibling={(id) => { setInsertTargetParentId(id); setInsertMode('sibling'); setIsModalOpen(true); }}
                      onDelete={handleNodeDelete}
                      onReplace={onReplaceInitiated}
                      onSelect={handleNodeSelect} 
                      selectedId={selectedNodeId} 
                      layoutMode={editorLayout} 
                    />
                    {idx !== arr.length - 1 && <div className={`h-8 w-0.5 flex-shrink-0 ${isDark ? 'bg-zinc-800' : 'bg-zinc-200'}`} />}
                  </React.Fragment>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
};