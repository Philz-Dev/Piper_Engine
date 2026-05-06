import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY! // Use Service Role to ensure update permissions
);

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { token, ip_address, port, status } = body;

    const { data, error } = await supabase
      .from('engines')
      .update({ 
        ip_address: ip_address, 
        port: port?.toString() || '8080', // Matches your TEXT type in SQL
        status: status || 'active',
        last_ping: new Date().toISOString() // Matches your SQL column name
      })
      .eq('install_token', token) // Filters by the unique token
      .select();

    if (error || !data || data.length === 0) {
      return NextResponse.json({ error: "Engine not found or update failed" }, { status: 400 });
    }

    return NextResponse.json({ message: "Registration successful" });
  } catch (err) {
    return NextResponse.json({ error: "Internal Server Error" }, { status: 500 });
  }
}