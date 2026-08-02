"use client";
import React from 'react';
import { Lock, CreditCard, ShieldCheck } from 'lucide-react';

export const PremiumPaymentPage = () => {
  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950 flex items-center justify-center p-4 transition-colors duration-300">
      <div className="max-w-5xl w-full grid md:grid-cols-2 gap-8 bg-white dark:bg-zinc-900 rounded-3xl shadow-2xl overflow-hidden border border-zinc-200 dark:border-zinc-800">
        
        {/* Left Side: Summary */}
        <div className="p-8 bg-zinc-100 dark:bg-zinc-950/50 flex flex-col justify-between">
          <div>
            <h2 className="text-2xl font-semibold text-zinc-900 dark:text-white">Order Summary</h2>
            <div className="mt-8 space-y-4">
              <div className="flex justify-between text-zinc-600 dark:text-zinc-400">
                <span>Enterprise Plan</span>
                <span>$2,999.00</span>
              </div>
              <div className="flex justify-between text-zinc-600 dark:text-zinc-400">
                <span>Tax (10%)</span>
                <span>$299.90</span>
              </div>
              <div className="border-t border-zinc-300 dark:border-zinc-800 pt-4 flex justify-between font-bold text-lg text-zinc-900 dark:text-white">
                <span>Total</span>
                <span>$3,298.90</span>
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400 mt-12">
            <ShieldCheck size={16} />
            <span>Secure 256-bit encrypted checkout</span>
          </div>
        </div>

        {/* Right Side: Payment Form */}
        <div className="p-8">
          <h2 className="text-xl font-semibold text-zinc-900 dark:text-white mb-6">Payment Details</h2>
          
          <form className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Cardholder Name</label>
              <input type="text" className="w-full px-4 py-3 rounded-xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 focus:ring-2 focus:ring-blue-500 outline-none transition-all dark:text-white" placeholder="Jane Doe" />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Card Number</label>
              <div className="relative">
                <CreditCard className="absolute left-3 top-3.5 text-zinc-400" size={18} />
                <input type="text" className="w-full pl-10 pr-4 py-3 rounded-xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 focus:ring-2 focus:ring-blue-500 outline-none transition-all dark:text-white" placeholder="0000 0000 0000 0000" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Expiry</label>
                <input type="text" className="w-full px-4 py-3 rounded-xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 focus:ring-2 focus:ring-blue-500 outline-none transition-all dark:text-white" placeholder="MM/YY" />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-zinc-700 dark:text-zinc-300">CVC</label>
                <input type="text" className="w-full px-4 py-3 rounded-xl bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 focus:ring-2 focus:ring-blue-500 outline-none transition-all dark:text-white" placeholder="123" />
              </div>
            </div>

            <button className="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-4 rounded-xl flex items-center justify-center gap-2 transition-all shadow-lg shadow-blue-500/20 active:scale-[0.98]">
              <Lock size={18} />
              Pay $3,298.90
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};