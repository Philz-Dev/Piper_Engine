"use client";
import React, { useCallback } from 'react';
import ReactFlow, { 
  Background, 
  Controls, 
  MiniMap, 
  useNodesState, 
  useEdgesState, 
  addEdge,
  Connection,
  Edge,
  Node
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Play, Save, Settings, ChevronLeft } from 'lucide-react';

interface BuildPageProps {
  automationName: string;
  isDark: boolean;
  onBack: () => void;
}

const initialNodes: Node[] = [
  { 
    id: '1', 
    type: 'input', 
    data: { label: 'Webhook Trigger' }, 
    position: { x: 250, y: 100 },
    style: { background: '#111', color: '#fff', border: '1px solid #333', fontSize: '10px', borderRadius: '4px' }
  },
];

export default function BuildPage({ automationName, isDark, onBack }: BuildPageProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

  return (
    <div className="flex flex-col h-full w-full overflow-hidden animate-in fade-in duration-500">
      {/* BUILDER SUB-HEADER */}
      <div className={`h-14 border-b flex items-center justify-between px-6 shrink-0 z-20 ${isDark ? 'bg-[#0a0a0a] border-[#1a1a1a]' : 'bg-white border-gray-200'}`}>
        <div className="flex items-center gap-4">
          <button 
            onClick={onBack}
            className={`p-1 rounded-md transition-colors ${isDark ? 'hover:bg-white/5 text-white/40 hover:text-white' : 'hover:bg-black/5 text-black/40 hover:text-black'}`}
          >
            <ChevronLeft size={18} />
          </button>
          <div className="flex items-center gap-3">
            <span className={`text-[10px] font-mono px-2 py-0.5 rounded border uppercase ${isDark ? 'bg-white/5 border-white/10 text-white/40' : 'bg-black/5 border-black/10 text-black/40'}`}>
              Scenario
            </span>
            <h2 className="text-sm font-bold tracking-tight uppercase italic">{automationName}</h2>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button className={`flex items-center gap-2 px-3 py-1.5 rounded text-[10px] font-bold uppercase tracking-wider transition-all border ${isDark ? 'border-white/10 hover:bg-white/5' : 'border-black/10 hover:bg-black/5'}`}>
            <Settings size={14} /> Config
          </button>
          <button className="flex items-center gap-2 px-3 py-1.5 rounded bg-white text-black text-[10px] font-bold uppercase tracking-wider hover:bg-white/90">
            <Save size={14} /> Save
          </button>
          <button className="flex items-center gap-2 px-4 py-1.5 rounded bg-blue-600 text-white text-[10px] font-bold uppercase tracking-wider hover:bg-blue-500">
            <Play size={14} fill="currentColor" /> Deploy
          </button>
        </div>
      </div>

      {/* REACT FLOW CANVAS */}
      <div className="flex-1 relative bg-[#050505]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          colorMode={isDark ? 'dark' : 'light'}
          fitView
        >
          <Background color={isDark ? "#222" : "#ddd"} gap={20} size={1} />
          <Controls className="!bg-[#111] !border-[#222] !fill-white" />
          <MiniMap 
            nodeColor={() => '#3b82f6'} 
            maskColor={isDark ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.7)'}
            className="!bg-[#0a0a0a] border border-[#1a1a1a]"
          />
        </ReactFlow>
        
        {/* ACTION BAR */}
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 flex items-center gap-4 p-1 rounded-full border border-white/10 bg-black/80 backdrop-blur-md px-4 py-2 z-10">
            {['HubSpot', 'Discord', 'Tally', 'Custom API'].map(tool => (
                <button key={tool} className="text-[9px] font-bold uppercase tracking-widest text-white/40 hover:text-white transition-colors">
                    + {tool}
                </button>
            ))}
        </div>
      </div>
    </div>
  );
}