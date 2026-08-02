import { useState, useEffect, useRef, useCallback } from 'react';
import { io, Socket } from 'socket.io-client';

export function usePiperConnection(activeClient: string, userId: string) {
  const [engineActive, setEngineActive] = useState(false);
  const [engineLoading, setEngineLoading] = useState(true);
  const [activeIntervention, setActiveIntervention] = useState(null);
  const [globalStats, setGlobalStats] = useState({ cpu: "0.00%", ram: "0.00MB", disk: "11.05GB used" });
  
  // Dashboard requirement states
  const [automations, setAutomations] = useState<any[]>([]);
  const [clients, setClients] = useState<string[]>([]);
  const [status, setStatus] = useState<{ locked: boolean | null; exists: boolean }>({ locked: null, exists: false });
  const [scriptContent, setScriptContent] = useState<string | null>(null);
  const [fileTree, setFileTree] = useState<any[]>([]);

  const [config, setConfig] = useState<any | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const [systemState, setSystemState] = useState<any[]>([]); 

  // Ref to track pending task promise resolvers for async methods like getScriptContent
  const pendingResolversRef = useRef<Map<string, { resolve: (val: any) => void; reject: (err: any) => void }>>(new Map());

  // Add this near your other refs
  const activeClientRef = useRef(activeClient);

  // Add this effect to keep the ref in sync
  useEffect(() => {
    activeClientRef.current = activeClient;
  }, [activeClient]);

  // Fetch initial config
  useEffect(() => {
    const fetchEngineConfig = async () => {
      if (!userId || userId === "") return;
      try {
        const response = await fetch(`https://piper-backend-production.up.railway.app/api/v1/engine/config/${userId}`);
        const data = await response.json();
        
        // Log the data to confirm the field names
        console.log("Fetched engine config:", data); 

        setConfig(data);
        
        // Update this part to map your API fields to the booleans your UI needs
        setStatus({ 
          locked: data.status === 'locked', 
          exists: data.status !== 'not_found' 
        });
        
        } catch (err) {
          console.error("Error initializing engine:", err);
        } finally {
          setEngineLoading(false);
        }
      };
      fetchEngineConfig();
    }, [userId]);

  // Handle Socket/Engine connectivity
  useEffect(() => {
    if (!config || engineLoading || status.locked) return;

    if (config.installation_type === 'cloud') {
      setEngineActive(true);
      return;
    }

    const socket = io("https://piper-backend-production.up.railway.app", {
      transports: ['websocket'],
      auth: { token: config.install_token },
      query: { userId: userId, installationType: config.installation_type }
    });

    socketRef.current = socket;
    
    socket.on("connect", () => {
      socket.emit("join_user_room", { user_id: userId });
      setEngineActive(true);

      fetchClients();
    });

    socket.on("stats_update", (data) => {
      if (data.total) {
        setGlobalStats({ cpu: data.total.total_cpu, ram: data.total.total_ram, disk: data.total.total_disk });
      }
    });

    socket.on("task_response", (data) => {
      const { status, task_id, result } = data;
      
      // Resolve any pending promise waiting on this specific task_id
      if (pendingResolversRef.current.has(task_id)) {
        const { resolve, reject } = pendingResolversRef.current.get(task_id)!;
        pendingResolversRef.current.delete(task_id);
        if (status !== "SUCCESS") {
          reject(result);
        } else {
          resolve(result);
        }
      }

      if (status !== "SUCCESS") {
        console.error(`Task ${task_id} failed:`, result);
        return;
      }

      console.log(`📥 Task ${task_id} completed successfully.`);

      // Handle logic based on the action performed with specific routing
      if (task_id?.startsWith("fetch_auto_")) {
        setAutomations(result || []);
      } else if (task_id?.startsWith("fetch_system_state_")) {
        setSystemState(result || []);
      } else if (task_id?.startsWith("fetch_script_")) {
        console.log("[DEBUG] Fetched script content result:", result);
        setScriptContent(result || []);
      } else if (task_id?.startsWith("fetch_clients_")) {
        setClients(result || []);
      } else if (task_id?.startsWith("fetch_file_tree_")) {
        console.log("[DEBUG] Fetched file tree result:", result);
        setFileTree(result || []);
      
      } else if (task_id?.startsWith("toggle_") || task_id?.startsWith("delete_")) {
        // REFRESH DATA: Use the activeClient passed to this hook to refresh the current view
        fetchAutomations(activeClient); 
      }
    });

    return () => { socket.disconnect(); };
  // Added activeClient to dependencies to keep listener scope synced
  }, [config, engineLoading, status.locked, userId, activeClient]); 

  const fetchAutomations = useCallback(async (client: string) => {
    if (!userId || userId === "" || !config || !client) return;

    try {
      if (config.installation_type === 'cloud') {
        const res = await fetch(`https://${config.domain}/api/v1/automations/${client}`, {
          headers: { 'Authorization': `Bearer ${config.install_token}` }
        });
        const data = await res.json();
        setAutomations(data.automations || []);
        setClients(data.clients || []);
      } else {
        // Emit as a task, handled by the task_response listener
        socketRef.current?.emit("execute_task", { 
          method: "get_automations", 
          params: { client_name: client },
          task_id: `fetch_auto_${Date.now()}`,
          userId: userId
        });
      }
    } catch (err) { 
      console.error("Fetch failed", err); 
    }
  }, [config, userId]);

  const fetchClients = useCallback(async () => {
    if (!userId || !config) return;

    if (config.installation_type === 'cloud') {
      const res = await fetch(`https://piper-backend-production.up.railway.app/api/v1/clients/${userId}`);
      const data = await res.json();
      setClients(data || []);
    } else {
      socketRef.current?.emit("execute_task", { 
          method: "list_clients", 
          params: {},
          task_id: `fetch_clients_${Date.now()}`,
          userId: userId
        });
      }
    }, [config, userId]);

  const unlockEngine = async (password: string) => {
    try {
      const res = await fetch(`https://piper-backend-production.up.railway.app/api/v1/engine/unlock`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId, password })
      });
      const data = await res.json();
      if (data.success) {
        setStatus({ locked: false, exists: true });
        return true;
      }
      return false;
    } catch { return false; }
  };

  const getScriptContent = useCallback(async (client: string, fileName: string, is_absolute: boolean=false) => {
    if (!config) return null;

    if (config.installation_type === 'cloud') {
      try {
        const res = await fetch(`https://${config.domain}/api/v1/script/${client}/${fileName}`, {
          headers: { 'Authorization': `Bearer ${config.install_token}` }
        });
        const data = await res.json();
        setScriptContent(data.content);
        return data.content;
      } catch (err) {
        console.error("Failed to fetch script content (cloud):", err);
        return null;
      }
    } else {
      return new Promise((resolve, reject) => {
        const taskId = `fetch_script_${Date.now()}`;
        pendingResolversRef.current.set(taskId, { resolve, reject });

        socketRef.current?.emit("execute_task", { 
          method: "get_script_content", 
          params: { client_name: client, file_name: fileName, is_absolute: is_absolute},
          task_id: taskId,
          userId: userId
        });
      });
    }
  }, [config, userId]);

  const toggleAutomation = async (name: string, action: string, client: string) => {
    if (config.installation_type === 'cloud') {
      await fetch(`https://${config.domain}/api/v1/toggle/${name}?action=${action}&client_name=${client}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${config.install_token}` }
      });
    } else {
      socketRef.current?.emit("execute_task", { 
        method: "toggle_container", 
        params: { container_name: name, action, client_name: client },
        task_id: `toggle_${Date.now()}`,
        userId: userId
      });
    }
  };

  const fetchSystemState = useCallback(() => {
    if (!userId || !config) return;
    socketRef.current?.emit("execute_task", { 
        method: "get_system_state", 
        params: {},
        task_id: `fetch_system_state_${Date.now()}`,
        userId: userId
    });
  }, [config, userId]);

  const deleteAutomation = async (path: string) => {
    if (config.installation_type === 'cloud') {
      await fetch(`https://${config.domain}/api/v1/automations/${client}/${name}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${config.install_token}` }
      });
    } else {
      socketRef.current?.emit("execute_task", { 
        method: "get_file_tree", 
        params: {},
        task_id: `file_tree_${Date.now()}`,
        userId: userId
      });
    }
  };

  const getFileTree = async (client: string, name: string) => {
    if (config.installation_type === 'cloud') {
      await fetch(`https://${config.domain}/api/v1/automations/${client}/${name}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${config.install_token}` }
      });
    } else {
      return new Promise((resolve, reject) => {
        const task_id = `fetch_file_tree_${Date.now()}`;
        pendingResolversRef.current.set(task_id, { resolve, reject });
        socketRef.current?.emit('execute_task', {
          method: 'get_file_tree',
          task_id: task_id,
          params: {},
          userId: userId
        });
      });
    }
  };

  // Update this useEffect block
  useEffect(() => {
    // Added config to the check to ensure engine is ready
    if (activeClient && activeClient !== "" && config) {
      fetchAutomations(activeClient);
    }
  // Added 'config' to dependencies so it fires when config loads
  }, [activeClient, config, fetchAutomations]);

  return { 
    automations, 
    clients, 
    status, 
    loading: engineLoading, 
    toggleAutomation, 
    deleteAutomation, 
    fetchAutomations, 
    fetchClients,
    unlockEngine,
    getFileTree,
    getScriptContent,
    fetchSystemState,
    scriptContent,
    engineActive,
    systemState,
    activeIntervention, 
    globalStats, 
    setActiveIntervention 
  };
}