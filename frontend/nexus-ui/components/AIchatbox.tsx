"use client";
import { useAIChat } from '@/hooks/useAIChat';
import { useState, useRef, useEffect } from 'react';
import { Bot, User, Send, Sparkles, Mic, MicOff } from 'lucide-react';

export default function AIchatbox({ theme }: { theme: string | null }) {
  const { messages, sendMessage, isLoading } = useAIChat();
  const [input, setInput] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const recognitionRef = useRef<any>(null);

  // Check for Speech Recognition support on mount
  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    setIsSupported(!!SpeechRecognition);

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, []);

  const toggleListening = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
    } else {
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onstart = () => setIsListening(true);
      recognition.onend = () => setIsListening(false);
      recognition.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript;
        setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
      };

      recognitionRef.current = recognition;
      recognition.start();
    }
  };

  return (
    <div className="flex h-full w-full flex-col bg-background">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-4 py-8">
        <div className="mx-auto max-w-3xl space-y-8">
          {messages.map((m, i) => (
            <div key={i} className={`flex gap-4 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {m.role === 'assistant' && (
                <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full border bg-background shadow-sm">
                  <Bot size={16} className="text-primary" />
                </div>
              )}
              
              <div className={`rounded-2xl px-5 py-3.5 text-sm shadow-sm max-w-[80%] break-words whitespace-pre-wrap ${
                m.role === 'user' 
                  ? 'bg-primary text-white rounded-br-none' 
                  : 'bg-muted/50 border border-border/50 text-foreground rounded-bl-none'
              }`}>
                {m.content}
              </div>

              {m.role === 'user' && (
                <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full border bg-primary/10">
                  <User size={16} className="text-primary" />
                </div>
              )}
            </div>
          ))}
          
          {isLoading && (
            <div className="flex gap-4">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border bg-background shadow-sm">
                <Sparkles size={16} className="animate-pulse text-primary" />
              </div>
              <div className="flex items-center gap-1 rounded-2xl bg-muted/50 px-5 py-3.5 text-xs text-muted-foreground">
                <span className="animate-bounce">●</span>
                <span className="animate-bounce delay-100">●</span>
                <span className="animate-bounce delay-200">●</span>
              </div>
            </div>
          )}
        </div>
      </div>
      
      {/* Composer Area */}
      <div className="border-t bg-background p-4">
        <div className="mx-auto max-w-3xl">
          <div className="relative flex items-end rounded-xl border border-border/50 bg-background shadow-lg focus-within:ring-2 focus-within:ring-primary/20">
            <textarea 
              rows={1}
              className="w-full max-h-48 bg-transparent p-4 pr-20 text-sm outline-none placeholder:text-muted-foreground resize-none overflow-hidden" 
              placeholder="Ask Gordon about your pipeline..."
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${e.target.scrollHeight}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage(input);
                  setInput('');
                  // Tell TypeScript to treat e.target as a textarea
                  (e.target as HTMLTextAreaElement).style.height = 'auto';
                }
              }}
            />
            
            <div className="absolute right-2 bottom-2 flex items-center gap-1">
              {isSupported && (
                <button 
                  onClick={toggleListening}
                  className={`p-2 rounded-lg transition-colors ${isListening ? 'text-red-500 bg-red-500/10 animate-pulse' : 'text-muted-foreground hover:text-primary hover:bg-primary/10'}`}
                >
                  {isListening ? <MicOff size={18} /> : <Mic size={18} />}
                </button>
              )}
              
              <button 
                onClick={() => { sendMessage(input); setInput(''); }}
                disabled={!input.trim() || isLoading}
                className="p-2 text-primary hover:bg-primary/10 rounded-lg transition-colors disabled:opacity-50"
              >
                <Send size={18} />
              </button>
            </div>
          </div>
          <p className="mt-2 text-center text-[10px] text-muted-foreground">
            Gordon can make mistakes. Consider checking important information.
          </p>
        </div>
      </div>
    </div>
  );
}