import React from 'react';
import Editor from '@monaco-editor/react';
import { Terminal, Maximize2, Minimize2, X, ChevronLeft, ChevronRight } from 'lucide-react';

export const PipelineEditor = ({ 
  yamlString, handleEditorChange, isDark, editorFontSize, isTerminalOpen, 
  setIsTerminalOpen, terminalHeight, isTerminalMaximized, setIsTerminalMaximized, 
  logs, terminalFontSize, editorLayout, setIsSidebarExpanded, isSidebarExpanded,
  setActiveRightTab, activeRightTab, setActivePanel 
}: any) => (
  <section onClick={() => setActivePanel('editor')} className={`border-l flex flex-col ${isDark ? 'bg-[#080808] border-white/5' : 'bg-white border-gray-200'}`}>
    <div className="h-10 w-full border-b border-white/5 flex items-center px-4 justify-between">
      <div className="flex items-center gap-6 h-full">
        {editorLayout === 'monaco' && (
          <button onClick={() => setIsSidebarExpanded(!isSidebarExpanded)} className="text-zinc-500">
            {isSidebarExpanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
          </button>
        )}
        <button onClick={() => setActiveRightTab('yaml')} className={`text-xs font-medium h-full border-b-2 ${activeRightTab === 'yaml' ? 'text-blue-500 border-blue-500' : 'border-transparent'}`}>pipeline.yaml</button>
        <button onClick={() => setIsTerminalOpen(!isTerminalOpen)} className={`text-xs font-medium h-full border-b-2 ${isTerminalOpen ? 'text-blue-500 border-blue-500' : 'border-transparent'}`}>Terminal</button>
      </div>
    </div>
    <Editor 
      height={isTerminalOpen ? `calc(100% - ${terminalHeight}px)` : "100%"} 
      theme={isDark ? "vs-dark" : "light"} 
      language="yaml" 
      value={yamlString} 
      onChange={handleEditorChange}
      options={{ fontSize: editorFontSize }}
    />
    {isTerminalOpen && (
      <div className={`border-t flex flex-col ${isDark ? 'bg-[#0d0d0d] border-white/5' : 'bg-zinc-50'}`} style={{ height: isTerminalMaximized ? 'calc(100vh - 40px)' : terminalHeight }}>
        <div className="h-8 flex items-center justify-between px-4 bg-[#151515]">
          <div className="flex items-center gap-2 text-[10px] uppercase font-bold text-zinc-500"><Terminal size={12} /> Log/Terminal</div>
          <div className="flex items-center gap-2">
            <button onClick={() => setIsTerminalMaximized(!isTerminalMaximized)}>{isTerminalMaximized ? <Minimize2 size={12} /> : <Maximize2 size={12} />}</button>
            <button onClick={() => setIsTerminalOpen(false)}><X size={12} /></button>
          </div>
        </div>
        <div className="flex-1 p-3 overflow-y-auto font-mono" style={{ fontSize: `${terminalFontSize}px` }}>
          {logs.map((log: any, idx: number) => <div key={idx}>{log}</div>)}
        </div>
      </div>
    )}
  </section>
);