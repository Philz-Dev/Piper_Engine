"use client";

import React, { useCallback } from 'react';
import ReactFlow, { 
  Background, 
  Controls, 
  useNodesState, 
  useEdgesState, 
  addEdge, 
  Connection, 
  Panel,
  Handle,
  Position
} from 'reactflow';
import 'reactflow/dist/style.css';
import { Plus, Play, Save, Settings, Database, MousePointer2 } from 'lucide-react';

// --- CUSTOM CIRCULAR NODE COMPONENT ---
const AutomationNode = ({ data }: any) => (
  <div className="group relative transition-all">
    <Handle type="target" position={Position.Left} className="w-3 h-3 bg-indigo-400" />
    <div className="w-20 h-20 rounded-full bg-white border-4 border-indigo-500 shadow-xl flex flex-col items-center justify-center hover:scale-110 transition-transform">
      <data.icon className="text-indigo-600" size={24} />
      <span className="text-[10px] mt-1 font-bold uppercase text-slate-500">{data.label}</span>
    </div>
    <Handle type="source" position={Position.Right} className="w-3 h-3 bg-indigo-400" />
  </div>
);

const nodeTypes = { automation: AutomationNode };

// --- MAIN BUILDER PAGE ---
export default function MakeClone() {
  const [nodes, setNodes, onNodesChange] = useNodesState([
    { 
      id: '1', 
      type: 'automation', 
      data: { label: 'Webhook', icon: Database }, 
      position: { x: 100, y: 200 } 
    }
  ]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

  const addModule = () => {
    const id = (nodes.length + 1).toString();
    setNodes((nds) => [
      ...nds,
      { 
        id, 
        type: 'automation', 
        data: { label: 'Action', icon: Settings }, 
        position: { x: 300, y: 200 } 
      },
    ]);
  };

  return (
    <div className="h-screen w-screen bg-slate-50 overflow-hidden flex flex-col">
      {/* Top Navbar */}
      <nav className="h-14 bg-white border-b flex items-center justify-between px-6 z-10">
        <div className="flex items-center gap-4">
          <div className="bg-indigo-600 p-1.5 rounded-lg text-white font-black italic">M</div>
          <h1 className="font-semibold text-slate-700">New Scenario</h1>
        </div>
        <div className="flex gap-2">
          <button className="flex items-center gap-2 px-4 py-1.5 rounded-md text-sm border hover:bg-slate-50"><Save size={16}/> Save</button>
          <button className="flex items-center gap-2 px-4 py-1.5 rounded-md text-sm bg-indigo-600 text-white hover:bg-indigo-700"><Play size={16}/> Run once</button>
        </div>
      </nav>

      {/* The Canvas */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
        >
          <Background color="#cbd5e1" variant={'dots' as any} gap={20} />
          <Controls />
          
          {/* Bottom Toolbar - This is very "Make" style */}
          <Panel position="bottom-center" className="mb-10">
            <div className="bg-white/80 backdrop-blur-md px-6 py-3 rounded-full shadow-2xl border flex items-center gap-8 border-slate-200">
              <button onClick={addModule} className="p-3 bg-indigo-600 text-white rounded-full hover:scale-110 transition-all shadow-lg active:scale-95">
                <Plus size={28} />
              </button>
              <div className="h-8 w-[1px] bg-slate-300" />
              <div className="flex gap-6 text-slate-500">
                <MousePointer2 size={20} className="cursor-pointer hover:text-indigo-600" />
                <Settings size={20} className="cursor-pointer hover:text-indigo-600" />
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}