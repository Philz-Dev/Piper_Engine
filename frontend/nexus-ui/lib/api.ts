// --- lib/api.ts ---
// const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';
const API_URL = 'https://piper-backend-production.up.railway.app';

export async function loginUser(email: string, password: string) {
  const res = await fetch(`${API_URL}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error('Invalid credentials');
  return res.json();
}

export async function signupUser(email: string, password: string) {
  const res = await fetch(`${API_URL}/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error('Registration failed');
  return res.json();
}

export async function checkUserAccess(email: string) {
  const res = await fetch(`${API_URL}/api/check-access/${email}`);
  if (!res.ok) throw new Error('Failed to fetch status');
  return res.json(); // returns { is_installed, is_subscribed }
}

function promptGoogleCredential(): Promise<string> {
  return new Promise((resolve, reject) => {
    if (typeof window === 'undefined' || !(window as any).google?.accounts?.oauth2) {
      return reject(new Error('Google Identity Services SDK is not loaded. Ensure the Google script is included in your layout.'));
    }

    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '837407650291-gi3sm0u7sb9vp2v7gfrni4q7a3vgem2o.apps.googleusercontent.com';
    
    const client = (window as any).google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: 'email profile openid',
      callback: (tokenResponse: any) => {
        if (tokenResponse.error) {
          return reject(new Error(`Google authorization error: ${tokenResponse.error}`));
        }
        if (tokenResponse.access_token) {
          resolve(tokenResponse.access_token);
        } else {
          reject(new Error('Google authentication failed: No access token received'));
        }
      },
    });

    // Pass prompt: 'select_account' to ensure mobile view re-opens the selector window on retry
    client.requestAccessToken({ prompt: 'select_account' });
  });
}

export async function googleLogin(token?: string) {
  const authToken = token || await promptGoogleCredential();
  if (!authToken) {
    throw new Error('Google ID token is required');
  }
  const res = await fetch(`${API_URL}/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: authToken }),
  });
  if (!res.ok) throw new Error('Google sign-in failed');
  return res.json();
}

export function renderGoogleButton(elementId: string, onSuccessCallback: (token: string) => void) {
  if (typeof window === 'undefined' || !(window as any).google?.accounts?.id) return;

  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || '837407650291-gi3sm0u7sb9vp2v7gfrni4q7a3vgem2o.apps.googleusercontent.com';

  (window as any).google.accounts.id.initialize({
    client_id: clientId,
    callback: (response: any) => {
      if (response.credential) {
        onSuccessCallback(response.credential);
      }
    },
  });

  const element = document.getElementById(elementId);
  if (element) {
    const containerWidth = element.parentElement ? element.parentElement.clientWidth : 350;
    (window as any).google.accounts.id.renderButton(element, {
      theme: 'outline',
      size: 'large',
      width: Math.min(350, containerWidth > 0 ? containerWidth : 350),
    });
  }
}

export async function verifySignup(email: string, code: string) {
  const res = await fetch(`${API_URL}/signup/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, code }),
  });
  if (!res.ok) {
    const errData = await res.json();
    throw new Error(errData.detail || 'Verification failed');
  }
  return res.json();
}

export async function forgotPassword(email: string) {
  const res = await fetch(`${API_URL}/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || 'Password reset request failed');
  }
  return res.json();
}

export async function resetPassword(email: string, code: string, new_password: string) {
  const res = await fetch(`${API_URL}/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, code, new_password }),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || 'Password reset failed');
  }
  return res.json();
}

export async function getEngineCommand(email: string) {
  const res = await fetch(`${API_URL}/api/v1/engine/command/${encodeURIComponent(email)}`);
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || 'Failed to fetch engine command');
  }
  return res.json(); // returns { user_id, command }
}