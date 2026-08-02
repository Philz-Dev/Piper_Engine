// --- ClovoAuthPortal.tsx ---
import { useState, useEffect, useRef } from 'react';
import { 
  Loader2, ArrowRight, ShieldCheck, Zap, 
  Sun, Moon, Activity, Layers, Send, CheckCircle2, Sparkles
} from 'lucide-react';
import { loginUser, getEngineCommand, signupUser, verifySignup, googleLogin, forgotPassword, resetPassword } from '@/lib/api';

interface ClovoAuthPortalProps {
  onSuccess?: (userData: any) => void;
  theme?: 'dark' | 'light';
  toggleTheme?: () => void;
}

export default function ClovoAuthPortal({ onSuccess, theme = 'dark', toggleTheme }: ClovoAuthPortalProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'form' | 'verify' | 'forgot' | 'reset'>('form');
  const [isLogin, setIsLogin] = useState(true);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: 'error' | 'success', text: string } | null>(null);
  const [newsletterEmail, setNewsletterEmail] = useState('');
  const [newsletterSubscribed, setNewsletterSubscribed] = useState(false);

  const isDark = theme !== 'light';
  const onSuccessRef = useRef(onSuccess);

  useEffect(() => {
    onSuccessRef.current = onSuccess;
  });

  // --- HELPER: Synchronize System ID with LocalStorage ---
  const fetchAndSaveUserContext = async (userEmail: string) => {
    try {
      const data = await getEngineCommand(email);
    
      return {
        id: data.user_id,
        userId: data.user_id,
        email: userEmail,
        command: data.command
      };
    } catch (err) {
      console.error("Identity synchronization failed:", err);
      // THROW the error so the calling function knows to stop
      throw new Error("Could not retrieve system configuration. Please check your credentials.");
    }
  };

  const handleGoogleAuth = async () => {
    window.onblur = null;
    window.onfocus = null;

    setLoading(true);
    setMessage(null);

    let isResolvedOrRejected = false;
    let windowBlurred = false;

    const handleBlur = () => {
      windowBlurred = true;
      window.removeEventListener('blur', handleBlur);
    };

    const handleFocus = () => {
      if (windowBlurred && !isResolvedOrRejected) {
        setTimeout(() => {
          if (!isResolvedOrRejected) {
            isResolvedOrRejected = true;
            setLoading(false);
            setMessage({ type: 'error', text: 'Google sign-in window was closed. Please try again.' });
            cleanup();
          }
        }, 800);
      }
    };

    const cleanup = () => {
      window.removeEventListener('blur', handleBlur);
      window.removeEventListener('focus', handleFocus);
    };

    window.addEventListener('blur', handleBlur);
    window.addEventListener('focus', handleFocus);

    try {
      const data = await googleLogin();
      isResolvedOrRejected = true;
      cleanup();
      
      // Sync the user context (Assuming data contains the email)
      const userEmail = data.email || email;
      const context = await fetchAndSaveUserContext(userEmail);
      
      if (onSuccessRef.current) {
        onSuccessRef.current({ ...data, ...context });
      } else {
        window.location.reload();
      }
    } catch (err: any) {
      isResolvedOrRejected = true;
      cleanup();
      setMessage({ type: 'error', text: err?.message || 'Google sign-in failed. Please try again.' });
    } finally {
      if (!isResolvedOrRejected) {
        setLoading(false);
        cleanup();
      }
    }
  };

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);
    
    try {
      if (isLogin) {
        if (step === 'forgot') {
          await forgotPassword(email);
          setStep('reset');
          setMessage({ type: 'success', text: 'Password reset code sent to your email.' });
        } else if (step === 'reset') {
          await resetPassword(email, code, password);
          setMessage({ type: 'success', text: 'Password reset successfully! Please sign in.' });
          setStep('form');
          setCode('');
          setPassword('');
        } else {
          const data = await loginUser(email, password);
          
          // CRITICAL: Synchronize Identity before triggering success
          const context = await fetchAndSaveUserContext(email);

          if (onSuccess) {
            onSuccess({ ...data, ...context });
          } else {
            window.location.reload();
          }
        }
      } else {
        if (step === 'form') {
          await signupUser(email, password);
          setStep('verify');
          setMessage({ type: 'success', text: 'Verification code sent to your email.' });
        } else {
          await verifySignup(email, code);
          setMessage({ type: 'success', text: 'Account verified successfully! Please sign in.' });
          setIsLogin(true);
          setStep('form');
          setCode('');
        }
      }
    } catch (err: any) {
      setMessage({ type: 'error', text: err?.message || 'Load failed. Please check your network connection.' });
    } finally {
      setLoading(false);
    }
  };

  const handleNewsletterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newsletterEmail) return;
    setNewsletterSubscribed(true);
    setNewsletterEmail('');
  };

  return (
    <div className={`min-h-screen w-full flex flex-col relative overflow-x-hidden overflow-y-auto transition-colors duration-500 ${isDark ? 'bg-black text-white' : 'bg-white text-black'}`}>
      
      {/* --- DYNAMIC AUTOMATION CANVAS BACKGROUND GLOWS & PULSING NODES --- */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden z-0">
        <div className={`absolute -top-40 -left-40 w-[650px] h-[650px] rounded-full blur-[140px] opacity-20 animate-pulse transition-colors duration-700 ${isDark ? 'bg-blue-600' : 'bg-blue-400'}`} />
        <div className={`absolute top-1/3 -right-40 w-[550px] h-[550px] rounded-full blur-[160px] opacity-15 animate-pulse transition-colors duration-700 ${isDark ? 'bg-indigo-600' : 'bg-cyan-300'}`} style={{ animationDuration: '4s' }} />
        <div className={`absolute bottom-1/4 left-1/3 w-[750px] h-[750px] rounded-full blur-[180px] opacity-10 animate-pulse transition-colors duration-700 ${isDark ? 'bg-purple-600' : 'bg-indigo-200'}`} style={{ animationDuration: '6s' }} />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808018_1px,transparent_1px),linear-gradient(to_bottom,#80808018_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_65%_55%_at_50%_50%,#000_70%,transparent_100%)] opacity-50" />
      </div>

      {/* --- NAVIGATION --- */}
      <nav className={`sticky top-0 z-50 backdrop-blur-xl border-b transition-colors duration-300 ${isDark ? 'border-white/10 bg-black/60' : 'border-black/10 bg-white/60'}`}>
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-lg shadow-lg ${isDark ? 'bg-white text-black shadow-white/10' : 'bg-black text-white shadow-black/10'}`}>
              <span>P</span>
            </div>
            <span className="font-extrabold tracking-tighter text-xl uppercase bg-gradient-to-r from-blue-500 to-indigo-500 bg-clip-text text-transparent">CLOVO</span>
          </div>
          <div className="flex items-center gap-8">
            <div className={`hidden md:flex items-center gap-8 text-sm font-medium ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
              <a href="#" className="hover:text-blue-500 transition-colors">Documentation</a>
              <a href="#" className="hover:text-blue-500 transition-colors">Community</a>
              <a href="#" className="hover:text-blue-500 transition-colors">Enterprise</a>
            </div>
            {toggleTheme && (
              <button 
                onClick={toggleTheme} 
                className={`p-2 rounded-lg transition-colors border ${isDark ? 'border-white/10 hover:bg-white/15 text-zinc-400' : 'border-black/10 hover:bg-black/15 text-zinc-600'}`}
                aria-label="Toggle theme"
              >
                {isDark ? <Sun size={18} /> : <Moon size={18} />}
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* --- MAIN AUTH CONTENT --- */}
      <main className="flex-grow flex items-center justify-center p-6 relative z-10 my-8">
        <div className={`w-full max-w-5xl border rounded-3xl overflow-hidden flex shadow-2xl transition-all duration-300 backdrop-blur-md ${isDark ? 'bg-zinc-900/40 border-white/10 shadow-blue-500/5' : 'bg-zinc-100/80 border-black/10 shadow-black/5'}`}>
          
          {/* Left Side: Brand Marketing */}
          <div className={`hidden lg:flex flex-1 flex-col justify-between p-12 border-r transition-colors duration-300 ${isDark ? 'bg-zinc-950/80 border-white/10' : 'bg-zinc-50 border-black/10'}`}>
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold mb-6 border bg-blue-500/10 text-blue-400 border-blue-500/20">
                <Sparkles size={12} /> v4.8 Enterprise Engine Online
              </div>
              <h2 className="text-4xl font-extrabold tracking-tight mb-4 leading-tight">
                The next generation<br />of cloud orchestration.
              </h2>
              <p className={`max-w-sm ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
                Experience high-fidelity engine management with real-time monitoring and global scaling capabilities.
              </p>
            </div>
            <div className={`flex gap-8 text-xs font-medium ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
              <div className="flex items-center gap-2"><ShieldCheck size={16} className="text-emerald-500" /> Enterprise Security</div>
              <div className="flex items-center gap-2"><Zap size={16} className="text-blue-500" /> Latency Optimized</div>
            </div>
          </div>

          {/* Right Side: Form */}
          <div className={`flex-1 flex items-center justify-center p-12 transition-colors duration-300 ${isDark ? 'bg-black/40' : 'bg-white'}`}>
            <div className="w-full max-w-[360px]">
              <div className="mb-8">
                <h1 className="text-2xl font-semibold mb-2">
                  {isLogin 
                    ? step === 'forgot' 
                      ? 'Reset password' 
                      : step === 'reset' 
                        ? 'Set new password' 
                        : 'Welcome back' 
                    : step === 'verify' 
                      ? 'Check your email' 
                      : 'Create your account'}
                </h1>
                <p className={`text-sm ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
                  {isLogin 
                    ? step === 'forgot' 
                      ? 'Enter your email to receive a reset code' 
                      : step === 'reset' 
                        ? 'Enter code and new password' 
                        : 'Sign in to access your dashboard' 
                    : step === 'verify' 
                      ? 'Enter the verification code sent to your inbox' 
                      : 'Enter your credentials to get started'}
                </p>
              </div>

              {isLogin && step === 'form' && (
                <>
                  <button
                    type="button"
                    onClick={handleGoogleAuth}
                    disabled={loading}
                    className={`w-full mb-6 py-3 px-4 rounded-xl text-sm font-semibold transition-all border flex items-center justify-center gap-3 disabled:opacity-50 ${isDark ? 'bg-zinc-900 border-white/10 hover:bg-zinc-800 text-white' : 'bg-zinc-50 border-black/10 hover:bg-zinc-200 text-black'}`}
                  >
                    <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
                    </svg>
                    Continue with Google
                  </button>

                  <div className="flex items-center my-6">
                    <div className={`flex-grow border-t ${isDark ? 'border-white/10' : 'border-black/10'}`}></div>
                    <span className={`px-3 text-[10px] uppercase tracking-wider font-semibold ${isDark ? 'text-zinc-500' : 'text-zinc-400'}`}>or use email</span>
                    <div className={`flex-grow border-t ${isDark ? 'border-white/10' : 'border-black/10'}`}></div>
                  </div>
                </>
              )}

              <form onSubmit={handleAuth} className="space-y-4">
                {(!isLogin && step === 'verify') || (isLogin && step === 'reset') ? (
                  <div>
                    <label className={`block text-xs font-medium mb-1.5 uppercase tracking-wider ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>Verification Code</label>
                    <input 
                      type="text" 
                      required 
                      maxLength={6}
                      placeholder="Enter 6-digit code"
                      className={`w-full border rounded-xl px-4 py-3 text-sm outline-none transition-all ${isDark ? 'bg-zinc-900/50 border-white/10 focus:border-blue-500 text-white placeholder:text-zinc-600' : 'bg-zinc-50 border-black/10 focus:border-blue-500 text-black placeholder:text-zinc-400'}`} 
                      value={code}
                      onChange={(e) => setCode(e.target.value)} 
                    />
                  </div>
                ) : null}

                {step !== 'verify' && step !== 'reset' && (
                  <div>
                    <label className={`block text-xs font-medium mb-1.5 uppercase tracking-wider ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>Email</label>
                    <input 
                      type="email" 
                      required 
                      placeholder="name@company.com"
                      className={`w-full border rounded-xl px-4 py-3 text-sm outline-none transition-all ${isDark ? 'bg-zinc-900/50 border-white/10 focus:border-blue-500 text-white placeholder:text-zinc-600' : 'bg-zinc-50 border-black/10 focus:border-blue-500 text-black placeholder:text-zinc-400'}`} 
                      value={email}
                      onChange={(e) => setEmail(e.target.value)} 
                    />
                  </div>
                )}

                {isLogin && step === 'reset' && (
                  <div>
                    <label className={`block text-xs font-medium mb-1.5 uppercase tracking-wider ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>Email</label>
                    <input 
                      type="email" 
                      required 
                      placeholder="name@company.com"
                      className={`w-full border rounded-xl px-4 py-3 text-sm outline-none transition-all ${isDark ? 'bg-zinc-900/50 border-white/10 focus:border-blue-500 text-white placeholder:text-zinc-600' : 'bg-zinc-50 border-black/10 focus:border-blue-500 text-black placeholder:text-zinc-400'}`} 
                      value={email}
                      onChange={(e) => setEmail(e.target.value)} 
                    />
                  </div>
                )}

                {isLogin ? (
                  step !== 'forgot' && (
                    <div>
                      <div className="flex justify-between items-center mb-1.5">
                        <label className={`block text-xs font-medium uppercase tracking-wider ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
                          {step === 'reset' ? 'New Password' : 'Password'}
                        </label>
                        {step === 'form' && (
                          <button type="button" onClick={() => { setStep('forgot'); setMessage(null); }} className={`text-[10px] transition-colors underline ${isDark ? 'text-zinc-500 hover:text-white' : 'text-zinc-600 hover:text-black'}`}>Forgot?</button>
                        )}
                      </div>
                      <input 
                        type="password" 
                        required 
                        placeholder="••••••••••••"
                        className={`w-full border rounded-xl px-4 py-3 text-sm outline-none transition-all ${isDark ? 'bg-zinc-900/50 border-white/10 focus:border-blue-500 text-white placeholder:text-zinc-600' : 'bg-zinc-50 border-black/10 focus:border-blue-500 text-black placeholder:text-zinc-400'}`} 
                        value={password}
                        onChange={(e) => setPassword(e.target.value)} 
                      />
                    </div>
                  )
                ) : (
                  step !== 'verify' && (
                    <div>
                      <div className="flex justify-between items-center mb-1.5">
                        <label className={`block text-xs font-medium uppercase tracking-wider ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>Password</label>
                      </div>
                      <input 
                        type="password" 
                        required 
                        placeholder="••••••••••••"
                        className={`w-full border rounded-xl px-4 py-3 text-sm outline-none transition-all ${isDark ? 'bg-zinc-900/50 border-white/10 focus:border-blue-500 text-white placeholder:text-zinc-600' : 'bg-zinc-50 border-black/10 focus:border-blue-500 text-black placeholder:text-zinc-400'}`} 
                        value={password}
                        onChange={(e) => setPassword(e.target.value)} 
                      />
                    </div>
                  )
                )}
                
                {message && (
                  <div className={`text-xs p-3 rounded-xl border ${message.type === 'error' ? 'bg-red-500/10 border-red-500/20 text-red-400' : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'}`}>
                    {message.text}
                  </div>
                )}

                <button 
                  type="submit" 
                  disabled={loading} 
                  className={`w-full mt-2 py-3.5 rounded-xl text-sm font-bold transition-all shadow-lg flex items-center justify-center gap-2 disabled:opacity-50 ${isDark ? 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white shadow-blue-500/20' : 'bg-black text-white hover:bg-zinc-800'}`}
                >
                  {loading ? <Loader2 size={16} className="animate-spin" /> : <> {isLogin ? (step === 'forgot' ? 'Send reset code' : step === 'reset' ? 'Reset password' : 'Sign in') : step === 'verify' ? 'Verify code' : 'Create account'} <ArrowRight size={16} /> </>}
                </button>

                {(step === 'forgot' || step === 'reset') && (
                  <button 
                    type="button" 
                    onClick={() => { setStep('form'); setMessage(null); }} 
                    className={`w-full text-center text-xs mt-2 underline ${isDark ? 'text-zinc-400 hover:text-white' : 'text-zinc-600 hover:text-black'}`}
                  >
                    Back to sign in
                  </button>
                )}
              </form>

              <div className={`mt-8 text-center text-sm ${isDark ? 'text-zinc-500' : 'text-zinc-600'}`}>
                {isLogin ? "Don't have an account?" : "Already have an account?"}{" "}
                <button onClick={() => { setIsLogin(!isLogin); setStep('form'); setMessage(null); }} className={`font-semibold hover:underline ${isDark ? 'text-white' : 'text-black'}`}>
                  {isLogin ? "Sign up" : "Sign in"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* --- ENTERPRISE SCALE SHOWCASE CARDS SECTION --- */}
      <section className="max-w-7xl mx-auto px-6 py-16 relative z-10 w-full">
        <div className="text-center mb-12">
          <span className="text-xs uppercase font-extrabold tracking-widest text-blue-500 mb-2 block">Unmatched Performance</span>
          <h3 className="text-3xl font-bold tracking-tight">Engineered for Global Scale</h3>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className={`p-8 rounded-2xl border transition-all duration-300 hover:scale-[1.02] ${isDark ? 'bg-zinc-900/30 border-white/10 hover:border-blue-500/40 shadow-xl' : 'bg-white border-black/10 shadow-lg'}`}>
            <div className="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-6">
              <Activity size={24} />
            </div>
            <h4 className="text-xl font-bold mb-2">99.999% SLA Uptime</h4>
            <p className={`text-sm ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
              Decentralized multi-region clusters ensure your automation pipelines execute continuously without single points of failure.
            </p>
          </div>

          <div className={`p-8 rounded-2xl border transition-all duration-300 hover:scale-[1.02] ${isDark ? 'bg-zinc-900/30 border-white/10 hover:border-indigo-500/40 shadow-xl' : 'bg-white border-black/10 shadow-lg'}`}>
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-6">
              <Activity size={24} />
            </div>
            <h4 className="text-xl font-bold mb-2">Sub-Millisecond Engine</h4>
            <p className={`text-sm ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
              Optimized worker spawning and memory caching cut execution delays down to negligible thresholds.
            </p>
          </div>

          <div className={`p-8 rounded-2xl border transition-all duration-300 hover:scale-[1.02] ${isDark ? 'bg-zinc-900/30 border-white/10 hover:border-cyan-500/40 shadow-xl' : 'bg-white border-black/10 shadow-lg'}`}>
            <div className="w-12 h-12 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 mb-6">
              <Layers size={24} />
            </div>
            <h4 className="text-xl font-bold mb-2">Quantum Vault Security</h4>
            <p className={`text-sm ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
              End-to-end payload credential encryption guarantees absolute privacy across multi-party integration hooks.
            </p>
          </div>
        </div>
      </section>

      {/* --- ENTERPRISE GRADE MULTI-MILLION DOLLAR FOOTER --- */}
      <footer className={`border-t py-16 relative z-10 transition-colors duration-500 ${isDark ? 'border-white/10 bg-zinc-950/90 text-zinc-400' : 'border-black/10 bg-zinc-100 text-zinc-600'}`}>
        <div className="max-w-7xl mx-auto px-6">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-12 mb-16">
            
            {/* Brand & Mission Column */}
            <div className="lg:col-span-2">
              <div className="flex items-center gap-2 mb-6">
                <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center text-white font-bold text-sm">
                  <Zap size={16} />
                </div>
                <span className="font-extrabold tracking-tight text-lg uppercase text-white">Clovo Systems</span>
              </div>
              <p className={`text-sm max-w-sm mb-6 ${isDark ? 'text-zinc-400' : 'text-zinc-600'}`}>
                The industry-leading orchestration infrastructure powering high-volume mission critical data flows for global enterprises.
              </p>
              
              <div className="flex items-center gap-3">
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                </span>
                <span className="text-xs font-semibold tracking-wider uppercase text-emerald-400">All Global Regions Operational</span>
              </div>
            </div>

            {/* Platform Links */}
            <div>
              <h5 className="font-bold text-xs uppercase tracking-widest mb-6 text-white">Platform</h5>
              <ul className="text-sm space-y-3 font-medium">
                <li><a href="#" className="hover:text-blue-500 transition-colors">Core Engine</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Integration Vault</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Latency Analytics</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">CLI Toolset</a></li>
              </ul>
            </div>

            {/* Enterprise & Company */}
            <div>
              <h5 className="font-bold text-xs uppercase tracking-widest mb-6 text-white">Enterprise</h5>
              <ul className="text-sm space-y-3 font-medium">
                <li><a href="#" className="hover:text-blue-500 transition-colors">Security & Trust</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Compliance ISO</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Custom Deployments</a></li>
                <li><a href="#" className="hover:text-blue-500 transition-colors">Executive Support</a></li>
              </ul>
            </div>

            {/* Newsletter Subscription Column */}
            <div>
              <h5 className="font-bold text-xs uppercase tracking-widest mb-6 text-white">Stay Synchronized</h5>
              <p className="text-xs mb-4">Receive private engineering releases and infrastructural scale updates.</p>
              {newsletterSubscribed ? (
                <div className="flex items-center gap-2 text-xs font-semibold text-emerald-400 bg-emerald-500/10 p-3 rounded-xl border border-emerald-500/20">
                  <CheckCircle2 size={16} /> Subscribed to updates.
                </div>
              ) : (
                <form onSubmit={handleNewsletterSubmit} className="space-y-2">
                  <div className="relative">
                    <input 
                      type="email" 
                      placeholder="Enter email address"
                      value={newsletterEmail}
                      onChange={(e) => setNewsletterEmail(e.target.value)}
                      className={`w-full text-xs rounded-xl px-3.5 py-3 outline-none border transition-all ${isDark ? 'bg-zinc-950 border-white/10 focus:border-blue-500 text-white placeholder:text-zinc-600' : 'bg-white border-black/10 focus:border-blue-500 text-black placeholder:text-zinc-400'}`}
                      required 
                    />
                  </div>
                  <button 
                    type="submit" 
                    className="w-full py-2.5 rounded-xl text-xs font-bold bg-blue-600 hover:bg-blue-500 text-white transition-all flex items-center justify-center gap-2 shadow-lg shadow-blue-500/10"
                  >
                    <Send size={12} /> Subscribe
                  </button>
                </form>
              )}
            </div>

          </div>

          {/* Bottom Bar */}
          <div className={`pt-8 border-t text-[11px] flex flex-col md:flex-row justify-between items-center gap-4 uppercase tracking-widest font-semibold ${isDark ? 'border-white/10 text-zinc-500' : 'border-black/10 text-zinc-400'}`}>
            <span>© 2026 Philz-Dev Systems. All Rights Reserved.</span>
            <div className="flex items-center gap-6">
              <a href="#" className="hover:text-white transition-colors">Privacy Policy</a>
              <a href="#" className="hover:text-white transition-colors">Terms of Service</a>
              <a href="#" className="hover:text-white transition-colors">Security Disclosure</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}