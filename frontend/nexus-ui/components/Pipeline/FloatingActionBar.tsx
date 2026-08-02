"use client";
import React, { useState, useRef, useEffect } from 'react';
import { Sparkles, ArrowUp, MessageSquare, Play, Square, LayoutGrid, Bug, GitBranch, ListTree, ZoomOut, ZoomIn, ChevronDown, Save, Undo2, Redo2 } from 'lucide-react';

interface FloatingActionBarProps {
  isActionExpanded: boolean;
  setIsActionExpanded: (expanded: boolean) => void;
  isAiPanelVisible: boolean;
  setIsAiPanelVisible: (visible: boolean) => void;
  isDark: boolean;
  aiInput: string;
  setAiInput: (input: string) => void;
  cycleEditorLayout: () => void;
  editorLayout: 'both' | 'visual' | 'monaco';
  setViewMode: (mode: string) => void;
  viewMode: string;
  handleZoom: (dir: 'in' | 'out') => void;
  activePanel: string;
  builderZoom: number;
  terminalFontSize: number;
  editorFontSize: number;
  setIsTerminalOpen: (open: boolean) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onSave?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
}

// Sophisticated Loading Component
const AiLoadingDots = ({ isDark }: { isDark: boolean }) => (
  <div className="flex gap-1.5 items-center px-2 py-1">
    {[0, 1, 2].map((i) => (
      <div
        key={i}
        className={`w-1.5 h-1.5 rounded-full animate-bounce ${isDark ? 'bg-blue-400' : 'bg-blue-600'}`}
        style={{ animationDelay: `${i * 0.2}s` }}
      />
    ))}
  </div>
);

export const FloatingActionBar: React.FC<FloatingActionBarProps> = ({
  isActionExpanded,
  setIsActionExpanded,
  isAiPanelVisible,
  setIsAiPanelVisible,
  isDark,
  aiInput,
  setAiInput,
  cycleEditorLayout,
  editorLayout,
  setViewMode,
  viewMode,
  handleZoom,
  activePanel,
  builderZoom,
  terminalFontSize,
  editorFontSize,
  setIsTerminalOpen,
  onUndo,
  onRedo,
  onSave,
  canUndo = false,
  canRedo = false,
}) => {
  const [messages, setMessages] = useState<{ role: 'user' | 'ai'; text: string }[]>([]);
  const [isAiLoading, setIsAiLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsAiPanelVisible(false);
      }
    };

    if (isAiPanelVisible) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isAiPanelVisible, setIsAiPanelVisible]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isAiLoading]);

  const handleSend = () => {
    if (!aiInput.trim()) return;
    
    // Add user message
    const newUserMessage = { role: 'user' as const, text: aiInput };
    setMessages((prev) => [...prev, newUserMessage]);
    setAiInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = '24px';
    }
    
    // Simulate AI loading and response
    setIsAiLoading(true);
    setTimeout(() => {
      setMessages((prev) => [...prev, { 
        role: 'ai', 
        text: "I've analyzed your pipeline request. I've initialized the requested modules and optimized the build path. Would you like me to deploy these changes now?" 
      }]);
      setIsAiLoading(false);
    }, 2000);
  };

  return (
    <div 
      ref={containerRef}
      onClick={(e) => e.stopPropagation()} 
      className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 flex flex-col items-center gap-2"
    >
      {isActionExpanded && isAiPanelVisible && (
        <div className={`w-[720px] h-64 border backdrop-blur-2xl rounded-2xl p-6 shadow-2xl mb-2 overflow-y-auto flex flex-col gap-4 ${isDark ? 'bg-[#0a0a0a]/95 border-white/10' : 'bg-white/95 border-gray-200'}`}>
          {messages.length === 0 ? (
             <p className={`text-sm ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>AI Response window content...</p>
          ) : (
            <>
              {messages.map((msg, index) => (
                <div 
                  key={index} 
                  className={`flex w-full ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {msg.role === 'user' ? (
                    <div className={`px-4 py-2 rounded-lg text-base bg-zinc-200 dark:bg-zinc-700 text-zinc-900 dark:text-white max-w-[80%] break-words whitespace-pre-wrap`}>
                      {msg.text}
                    </div>
                  ) : (
                    <div className={`w-full text-base break-words whitespace-pre-wrap leading-relaxed ${isDark ? 'text-white' : 'text-zinc-800'}`}>
                      <span className="font-semibold block mb-1">AI Assistant:</span>
                      {msg.text}
                    </div>
                  )}
                </div>
              ))}
              {isAiLoading && <AiLoadingDots isDark={isDark} />}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>
      )}

      <div 
        className={`flex items-center gap-3 rounded-full shadow-2xl transition-all duration-300 ease-in-out ${
          isActionExpanded 
            ? 'px-4 py-2 border' 
            : 'p-3 w-11 h-11 border justify-center cursor-pointer hover:scale-105'
        } ${isDark ? 'bg-[#0a0a0a]/90 border-white/10' : 'bg-white border-gray-200'}`}
        onClick={() => { if (!isActionExpanded) setIsActionExpanded(true); }}
      >
        {isActionExpanded ? (
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-3">
              <Sparkles size={16} className="text-blue-400 shrink-0" />
              <textarea
                ref={textareaRef}
                value={aiInput}
                onChange={(e) => {
                  setAiInput(e.target.value);
                  e.target.style.height = 'auto';
                  e.target.style.height = Math.min(e.target.scrollHeight, 128) + 'px';
                }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                placeholder="Ask AI to architect pipeline..."
                className={`w-[240px] max-h-32 bg-transparent text-base focus:outline-none resize-none overflow-y-auto py-1 leading-relaxed ${isDark ? 'text-white placeholder:text-white/30' : 'text-black placeholder:text-black/30'}`}
                rows={1}
                style={{ height: '24px' }}
              />
              <button onClick={handleSend} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-zinc-400 hover:text-black dark:hover:text-white transition-colors">
                <ArrowUp size={16} />
              </button>
              <button onClick={() => setIsAiPanelVisible(!isAiPanelVisible)} className={`p-1.5 rounded-lg transition-colors ${isAiPanelVisible ? 'bg-blue-600/20 text-blue-400' : 'text-zinc-400 hover:bg-zinc-800/10'}`}>
                <MessageSquare size={16} />
              </button>
            </div>

            <div className={`w-px h-6 ${isDark ? 'bg-white/10' : 'bg-gray-200'}`} />

            <div className="flex items-center gap-1">
              <button onClick={onSave} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-zinc-400 hover:text-blue-500 transition-colors" title="Save File"><Save size={16} /></button>
              <button onClick={onUndo} disabled={!canUndo} className={`p-1.5 rounded-lg transition-colors ${canUndo ? 'text-zinc-400 hover:bg-zinc-800/10 hover:text-blue-500 cursor-pointer' : 'text-zinc-600/30 dark:text-white/10 cursor-not-allowed'}`} title="Undo"><Undo2 size={16} /></button>
              <button onClick={onRedo} disabled={!canRedo} className={`p-1.5 rounded-lg transition-colors ${canRedo ? 'text-zinc-400 hover:bg-zinc-800/10 hover:text-blue-500 cursor-pointer' : 'text-zinc-600/30 dark:text-white/10 cursor-not-allowed'}`} title="Redo"><Redo2 size={16} /></button>
              
              <div className={`w-px h-4 mx-1 ${isDark ? 'bg-white/5' : 'bg-gray-200'}`} />

              <button onClick={() => setIsTerminalOpen(true)} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-green-500"><Play size={16} /></button>
              <button onClick={() => setIsTerminalOpen(true)} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-red-500"><Square size={16} /></button>
              
              <button onClick={cycleEditorLayout} title={`Layout View: ${editorLayout}`} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-zinc-400 hover:text-blue-500 transition-colors"><LayoutGrid size={16} /></button>
              <button className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-blue-400"><Bug size={16} /></button>
              <button onClick={() => setViewMode(viewMode === 'tree' ? 'graph' : 'tree')} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-zinc-400">{viewMode === 'tree' ? <GitBranch size={16} /> : <ListTree size={16} />}</button>
              <button onClick={() => handleZoom('out')} className="p-1.5 hover:bg-zinc-800/10 rounded-lg"><ZoomOut size={16} /></button>
              <span className={`text-[10px] font-mono w-10 text-center ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>{activePanel === 'builder' ? `${Math.round(builderZoom * 100)}%` : activePanel === 'terminal' ? `${terminalFontSize}px` : `${editorFontSize}px`}</span>
              <button onClick={() => handleZoom('in')} className="p-1.5 hover:bg-zinc-800/10 rounded-lg"><ZoomIn size={16} /></button>
              <button onClick={(e) => { e.stopPropagation(); setIsActionExpanded(false); }} className="p-1.5 hover:bg-zinc-800/10 rounded-lg text-zinc-400 transition-colors" title="Collapse Menu"><ChevronDown size={16} /></button>
            </div>
          </div>
        ) : (
          <div className="relative group flex items-center justify-center">
            <Sparkles size={16} className="text-blue-400 shrink-0 animate-pulse" />
          </div>
        )}
      </div>
    </div>
  );
};