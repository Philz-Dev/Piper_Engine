'use client';

import React, { useState, useCallback } from 'react';
import ReactFlow, { 
  addEdge, 
  Background, 
  Controls, 
  MiniMap,
  useNodesState,
  useEdgesState,
  Panel
} from 'reactflow';
import 'reactflow/dist/style.css';

// Initial structure representing a new automation
const initialNodes = [
  {
    id: 'node-1',
    type: 'input',
    data: { label: 'Trigger (e.g., Typeform)' },
    position: { x: 250, y: 5 },
  },
];

export default function BuildPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [pipelineName, setPipelineName] = useState('New Automation');

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const savePipeline = async () => {
    // This maps the visual flow back to your "interpreted dict" format
    const flowData = {
      pipeline_slug: pipelineName.toLowerCase().replace(/\s+/g, '-'),
      nodes,
      edges,
    };

    const response = await fetch('/api/pipeline/save', {
      method: 'POST',
      body: JSON.stringify(flowData),
    });

    if (response.ok) alert('Pipeline Saved Successfully');
  };

  return (
    <div className="flex h-screen w-full bg-slate-900 text-white">
      {/* Sidebar for Node Selection */}
      <div className="w-64 border-r border-slate-700 p-4 flex flex-col gap-4 bg-slate-800">
        <h2 className="text-xl font-bold">Piper Nodes</h2>
        <div className="p-3 bg-blue-600 rounded cursor-pointer hover:bg-blue-500 text-center shadow-lg">
          Trigger (Webhook)
        </div>
        <div className="p-3 bg-green-600 rounded cursor-pointer hover:bg-green-500 text-center shadow-lg">
          Action (HubSpot)
        </div>
        <div className="p-3 bg-purple-600 rounded cursor-pointer hover:bg-purple-500 text-center shadow-lg">
          Logic (Condition)
        </div>
        <div className="mt-auto">
           <label className="text-xs uppercase text-slate-400">Pipeline Name</label>
           <input 
            value={pipelineName}
            onChange={(e) => setPipelineName(e.target.value)}
            className="w-full bg-slate-700 border border-slate-600 p-2 rounded mt-1"
           />
        </div>
      </div>

      {/* Main Builder Canvas */}
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background color="#334155" gap={20} />
          <Controls />
          <MiniMap nodeStrokeColor="#3b82f6" maskColor="rgba(15, 23, 42, 0.6)" />
          
          <Panel position="top-right">
            <button 
              onClick={savePipeline}
              className="bg-emerald-500 hover:bg-emerald-400 px-6 py-2 rounded-full font-bold shadow-xl transition-all"
            >
              Deploy Pipeline
            </button>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}