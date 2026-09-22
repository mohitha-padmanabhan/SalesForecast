import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import './Login.css';

function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  
  const navigate = useNavigate();
  const location = useLocation();

  // Handle post-Microsoft redirect detection
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const loginSuccess = searchParams.get('login_success');
    const user = searchParams.get('user');
    const email = searchParams.get('email'); // Captures email parameter if sent by backend

    if (loginSuccess === 'true') {
      // Log the authenticated user info/email to the console
      console.log('Microsoft Auth Successful!');
      console.log('Logged in User/Email:', email || user || 'No email/user payload provided');

      // Save auth state to local storage
    localStorage.setItem('isLoggedIn', 'true');
    if (user) localStorage.setItem('user', user);
    if (email) {
      localStorage.setItem('user_email', email);
      localStorage.setItem('userEmail', email); // Keep both for fallback
    }

      // Programmatically navigate to dashboard
      navigate('/dashboard', { replace: true });
    }
  }, [location, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    await new Promise(resolve => setTimeout(resolve, 900));
    if (username === 'admin' && password === 'password') {
      localStorage.setItem('isLoggedIn', 'true');
      navigate('/dashboard');
    } else {
      setError('Invalid username or password');
      setIsLoading(false);
    }
  };

  const handleMicrosoftLogin = () => {
    const backendBaseUrl = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';
    window.location.href = `${backendBaseUrl}/auth/microsoft/login`;
  };

  return (
    <div className="login-container">
      <div className="login-wrapper">
        <section className="login-brand">
          <div className="brand-logo">
            <img className="brand-logo-image" src="/infinium-logo.jpg" alt="Infinium Spirits" />
            <div className="brand-copy">
              <h1>Forecast Planning Portal</h1>
              <div className="brand-accent" />
              <p>Review actuals, manage forecasts and update planning data from one secure workspace.</p>
              <ul className="brand-points">
                <li>Planning ID based forecasting</li>
                <li>Monthly and annual planning modes</li>
                <li>Versioned forecast submissions</li>
              </ul>
            </div>
          </div>
        </section>

        <section className="login-card">
          <div className="login-header">
            <h2>Welcome Back</h2>
            <p>Sign in to access the Infinium forecast dashboard.</p>
          </div>
          <form onSubmit={handleSubmit} className="login-form">
            <div className="form-group">
              <label>
                <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                Username
              </label>
              <input type="text" value={username} onChange={(e)=>setUsername(e.target.value)} placeholder="Enter your username" required className={error?'error':''}/>
            </div>
            <div className="form-group">
              <label>
                <svg className="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                Password
              </label>
              <div className="password-input-wrapper">
                <input type={showPassword?'text':'password'} value={password} onChange={(e)=>setPassword(e.target.value)} placeholder="Enter your password" required className={error?'error':''}/>
                <button type="button" className="password-toggle" aria-label="Toggle password visibility" onClick={()=>setShowPassword(!showPassword)}>
                  {showPassword ? (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                      <line x1="1" y1="1" x2="23" y2="23"/>
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8z"/>
                      <circle cx="12" cy="12" r="3"/>
                    </svg>
                  )}
                </button>
              </div>
            </div>
            <div className="form-options">
              <label className="remember-me"><input type="checkbox"/><span>Remember me</span></label>
              <a href="#" className="forgot-password">Forgot Password?</a>
            </div>
            {error && <div className="error-message">{error}</div>}
            <button type="submit" className="login-btn" disabled={isLoading}>
              {isLoading ? <span className="btn-loader"><span className="loader-dot"/><span className="loader-dot"/><span className="loader-dot"/></span> : <>Sign In <svg className="btn-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg></>}
            </button>
          </form>

          <div className="login-divider">
            <span>OR</span>
          </div>

          <button type="button" className="microsoft-btn" onClick={handleMicrosoftLogin} disabled={isLoading}>
            <svg className="ms-icon" viewBox="0 0 23 23">
              <path fill="#f35325" d="M1 1h10v10H1z"/>
              <path fill="#81bc06" d="M12 1h10v10H1z"/>
              <path fill="#05a6f0" d="M1 12h10v10H1z"/>
              <path fill="#ffba08" d="M12 12h10v10H12z"/>
            </svg>
            Sign in with Microsoft
          </button>

          <div className="login-footer"><p>Need access? <a href="#">Contact Admin</a></p></div>
        </section>
      </div>
    </div>
  );
}

export default Login;