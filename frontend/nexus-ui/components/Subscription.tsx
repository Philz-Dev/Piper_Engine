"use client";
import React, { useState } from 'react';
import { Check, ArrowRight, Zap, ShieldCheck } from 'lucide-react';

const PricingCard = ({ title, price, features, highlighted, isYearly }: any) => {
  const displayPrice = typeof price === 'object' 
    ? (isYearly ? price.yearly : price.monthly)
    : price;

  return (
    <div className={`relative p-8 rounded-3xl border flex flex-col h-full transition-colors duration-200 ${
      highlighted 
        ? 'border-primary bg-primary/5' 
        : 'border-border bg-card'
    }`}>
      {highlighted && (
        <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-primary text-white text-[10px] font-bold uppercase tracking-widest px-3 py-1 rounded-full">
          Best Value
        </div>
      )}
      <h3 className="text-xl font-semibold mb-2 text-foreground">{title}</h3>
      <div className="flex items-baseline gap-1 mb-6">
        <span className="text-4xl font-bold text-foreground">
          {displayPrice === 'Custom' || displayPrice === 'Free' ? displayPrice : `$${displayPrice}`}
        </span>
        {displayPrice !== 'Custom' && displayPrice !== 'Free' && <span className="text-muted text-sm">/mo</span>}
      </div>
      
      {/* flex-1 pushes the trailing action button down to align evenly across cards */}
      <ul className="space-y-4 mb-8 flex-1">
        {features.map((f: string, i: number) => (
          <li key={i} className="flex items-center gap-3 text-muted text-sm">
            <Check size={16} className="text-log-info" /> {f}
          </li>
        ))}
      </ul>

      <button className={`w-full py-3 rounded-xl font-medium transition-all mt-auto ${
        highlighted 
          ? 'bg-btn-primary hover:bg-btn-primary-hover text-white' 
          : 'bg-btn-secondary hover:bg-btn-secondary-hover text-foreground'
      }`}>
        {displayPrice === 'Custom' ? 'Contact Sales' : 'Get Started'}
      </button>
    </div>
  );
};

export default function SubscriptionPage() {
  const [isYearly, setIsYearly] = useState(true);

  return (
    <div className="w-full min-h-screen bg-background text-foreground py-16 px-4 flex flex-col items-center justify-between gap-12 transition-colors duration-200">
      <div className="text-center">
        <h1 className="text-4xl font-bold mb-4 text-foreground">Pricing for Clovo</h1>
        <div className="flex items-center justify-center gap-4 bg-surface p-1 rounded-full w-fit mx-auto border border-border">
          <button 
            onClick={() => setIsYearly(false)} 
            className={`px-6 py-2 rounded-full text-sm transition-all ${!isYearly ? 'bg-foreground text-background font-medium' : 'text-muted'}`}
          >
            Monthly
          </button>
          <button 
            onClick={() => setIsYearly(true)} 
            className={`px-6 py-2 rounded-full text-sm transition-all ${isYearly ? 'bg-foreground text-background font-medium' : 'text-muted'}`}
          >
            Yearly <span className="text-[10px] text-log-info ml-1 font-bold">Save ~17%</span>
          </button>
        </div>
      </div>

      <div className="w-full max-w-3xl">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-stretch">
          <PricingCard 
              title="Clovo" 
              price="Free" 
              features={['Piper Engine Access', 'Basic CLI', 'Community Support']} 
              isYearly={isYearly} 
          />
          <PricingCard 
              title="Clovo Studio" 
              price={{ monthly: 120, yearly: 99 }} 
              highlighted
              features={[
                'Piper Engine Access', 
                'Basic CLI', 
                'Community Support',
                'Visual Dashboard', 
                'GUI Workflow Builder', 
                'AI Workflow Building & Debugging'
              ]} 
              isYearly={isYearly} 
          />
        </div>
      </div>

      <div className="flex gap-8 items-center text-muted text-sm">
        <div className="flex items-center gap-2"><ShieldCheck size={16} className="text-log-info" /> SOC2 Compliant</div>
        <div className="flex items-center gap-2"><ShieldCheck size={16} className="text-log-info" /> Encrypted Data</div>
      </div>
    </div>
  );
}