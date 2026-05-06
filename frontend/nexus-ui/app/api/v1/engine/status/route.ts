import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

// Initialize the Supabase client using your .env.local keys
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export async function GET() {
  try {
    const { data: engine, error } = await supabase
      .from('engines')
      .select('ip_address, port, status')
      .eq('install_token', 'PIPER-772-X90') // Filter by YOUR specific engine
      .single();

    // If there is an error or no engine found at all
    if (error || !engine) {
      return NextResponse.json({ 
        active: false, 
        message: "Engine not found in database" 
      }, { status: 200 }); 
    }

    // Success: Return the actual status from the database
    return NextResponse.json({ 
      active: engine.status === 'active', // This will be true only when the DB says 'active'
      ip: engine.ip_address,
      port: engine.port,
      status: engine.status
    }, { status: 200 });

  } catch (error) {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}