import { useState, useCallback, useEffect } from 'react';

export const useLayout = () => {
  const [editorLayout, setEditorLayout] = useState<'both' | 'visual' | 'monaco'>('both');
  const [isResizing, setIsResizing] = useState(false);
  const [editorWidth, setEditorWidth] = useState(800);
  const [terminalHeight, setTerminalHeight] = useState(200);
  const [isResizingTerminal, setIsResizingTerminal] = useState(false);
  const [builderZoom, setBuilderZoom] = useState(1);

  const cycleEditorLayout = () => setEditorLayout(prev => prev === 'both' ? 'monaco' : prev === 'monaco' ? 'visual' : 'both');
  const startResizing = useCallback(() => setIsResizing(true), []);
  const startResizingTerminal = useCallback((e: React.MouseEvent) => { e.preventDefault(); setIsResizingTerminal(true); }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizing) setEditorWidth(window.innerWidth - e.clientX);
      if (isResizingTerminal) {
        const newHeight = window.innerHeight - e.clientY;
        if (newHeight > 100 && newHeight < window.innerHeight - 100) setTerminalHeight(newHeight);
      }
    };
    const stopResizing = () => { setIsResizing(false); setIsResizingTerminal(false); };
    if (isResizing || isResizingTerminal) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', stopResizing);
    }
    return () => { window.removeEventListener('mousemove', handleMouseMove); window.removeEventListener('mouseup', stopResizing); };
  }, [isResizing, isResizingTerminal]);

  return { editorLayout, cycleEditorLayout, editorWidth, terminalHeight, builderZoom, setBuilderZoom, startResizing, startResizingTerminal };
};