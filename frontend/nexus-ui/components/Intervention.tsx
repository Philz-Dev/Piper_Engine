import React, { useState } from 'react';

// 1. Updated interface to include 'id'
interface Intervention {
  id: number;
  app_name: string;
  auth_url: string;
}

interface AuthModalProps {
  intervention: Intervention | null;
  onClose: () => void;
  // 2. Added onResolve prop
  onResolve: (id: number) => Promise<void>;
}

const AuthModal: React.FC<AuthModalProps> = ({ intervention, onClose, onResolve }) => {
  // 3. Added loading state
  const [isResolving, setIsResolving] = useState(false);

  if (!intervention) return null;

  const handleConfirm = async () => {
    setIsResolving(true);
    
    const width = 600;
    const height = 700;
    const left = window.screen.width / 2 - width / 2;
    const top = window.screen.height / 2 - height / 2;
    
    // Open the auth window
    window.open(
      intervention.auth_url, 
      '_blank', 
      `width=${width},height=${height},top=${top},left=${left},noopener,noreferrer`
    );
    
    // 4. Call the resolve function and wait for it to complete
    await onResolve(intervention.id);
    
    setIsResolving(false);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50">
      <div className="bg-white p-8 rounded-xl shadow-2xl w-[450px] text-center">
        <h2 className="text-2xl font-bold mb-4">Authentication Required</h2>
        <p className="mb-6 text-gray-600">
          We need permission for <strong>{intervention.app_name}</strong> to continue the pipeline.
        </p>
        
        {/* 5. Updated button with loading states */}
        <button 
          onClick={handleConfirm} 
          disabled={isResolving}
          className={`w-full py-3 rounded-lg font-semibold transition ${
            isResolving 
              ? "bg-gray-400 cursor-not-allowed" 
              : "bg-blue-600 hover:bg-blue-700 text-white"
          }`}
        >
          {isResolving ? "Authorizing..." : "Open Authorization Window"}
        </button>
        
        <p className="mt-4 text-xs text-gray-400">
          {isResolving 
            ? "Waiting for authorization..." 
            : "If the window doesn't open, please check your browser's pop-up blocker settings."}
        </p>
      </div>
    </div>
  );
};

export default AuthModal;