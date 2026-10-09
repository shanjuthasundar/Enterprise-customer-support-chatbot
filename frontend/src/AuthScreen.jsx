import React, { useState } from "react";
import { ArrowRight, Eye, EyeOff, LockKeyhole, ShieldCheck, Sparkles } from "lucide-react";

function AuthScreen({ onSubmit, busy, connectionError }) {
  const [mode, setMode] = useState("signin");
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");

  const isSignup = mode === "signup";

  async function handleSubmit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (isSignup && form.get("password") !== form.get("confirmPassword")) {
      setMessage("Those passwords don't match yet.");
      return;
    }
    setMessage("");
    try {
      await onSubmit(mode, {
        display_name: form.get("name"),
        email: form.get("email"),
        password: form.get("password"),
      });
    } catch (error) {
      setMessage(error.message || "We couldn't sign you in. Please try again.");
    }
  }

  function switchMode(nextMode) {
    setMode(nextMode);
    setMessage("");
  }

  return (
    <main className="auth-page">
      <section className="auth-story">
        <a className="auth-brand" href="#" onClick={(event) => event.preventDefault()} aria-label="Kindred home">
          <span className="brand-mark"><span /><span /><span /><span /></span>
          <span className="auth-brand-name">kindred<span>.</span></span>
        </a>
        <div className="story-content">
          <div className="story-kicker"><span /> A LITTLE MORE HUMAN <span /></div>
          <h1>Make every<br />conversation<br />feel <span>like care.</span></h1>
          <p>One thoughtful space for the people who make your business matter.</p>
          <div className="story-art" aria-hidden="true">
            <div className="art-glow" />
            <div className="art-orbit art-orbit-outer" />
            <div className="art-orbit art-orbit-inner" />
            <div className="art-sparkle art-sparkle-one"><Sparkles size={15} /></div>
            <div className="art-sparkle art-sparkle-two"><span /></div>
            <div className="care-card">
              <div className="care-card-top"><div className="care-avatar">M</div><div><span>Mia from Kindred</span><small><span /> Here for you</small></div><Sparkles size={15} /></div>
              <p>“Oh, absolutely. Let’s make this right for you.”</p>
              <div className="care-card-bottom"><span /><span /><span /></div>
            </div>
            <div className="art-caption"><span /> A little kindness goes a long way.</div>
          </div>
        </div>
        <div className="story-bottom"><ShieldCheck size={15} /><span>Thoughtful support starts with a little trust.</span><span className="story-bottom-right">© 2026 Kindred</span></div>
      </section>

      <section className="auth-panel">
        <div className="auth-panel-top"><span>{isSignup ? "Already have an account?" : "New to Kindred?"}</span><button type="button" onClick={() => switchMode(isSignup ? "signin" : "signup")}>{isSignup ? "Sign in" : "Create an account"} <ArrowRight size={14} /></button></div>
        <div className="auth-form-wrap">
          <div className="auth-mobile-brand">
            <span className="brand-mark"><span /><span /><span /><span /></span>
            <span className="auth-brand-name">kindred<span>.</span></span>
          </div>
          <div className="auth-welcome-icon"><Sparkles size={20} /></div>
          <p className="auth-eyebrow">{isSignup ? "YOUR KIND OF CUSTOMER CARE" : "WELCOME BACK"}</p>
          <h2>{isSignup ? "Let’s get you started." : "Good to see you again."}</h2>
          <p className="auth-subtitle">{isSignup ? "Create your workspace. Your customers are in good hands." : "Your thoughtful little corner of the internet awaits."}</p>

          <div className="auth-tabs" role="tablist" aria-label="Account options">
            <button type="button" role="tab" aria-selected={!isSignup} className={!isSignup ? "auth-tab active" : "auth-tab"} onClick={() => switchMode("signin")}>Sign in</button>
            <button type="button" role="tab" aria-selected={isSignup} className={isSignup ? "auth-tab active" : "auth-tab"} onClick={() => switchMode("signup")}>Create account</button>
          </div>

          <form className="auth-form" key={mode} onSubmit={handleSubmit}>
            {isSignup && (
              <label className="auth-field">
                <span>Your name</span>
                <input name="name" type="text" placeholder="Jordan Davis" autoComplete="name" minLength={2} required />
              </label>
            )}
            <label className="auth-field">
              <span>Work email</span>
              <input name="email" type="email" placeholder="you@yourcompany.com" autoComplete="email" required />
            </label>
            <label className="auth-field">
              <span>Password</span>
              <span className="password-input">
                <input name="password" type={showPassword ? "text" : "password"} placeholder={isSignup ? "At least 12 characters" : "Your password"} autoComplete={isSignup ? "new-password" : "current-password"} minLength={isSignup ? 12 : 1} maxLength={128} required />
                <button className="password-toggle" type="button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button>
              </span>
            </label>
            {isSignup && (
              <label className="auth-field">
                <span>Confirm password</span>
                <input name="confirmPassword" type="password" placeholder="Type your password again" autoComplete="new-password" minLength={12} maxLength={128} required />
              </label>
            )}
            {!isSignup && <div className="auth-forgot"><span><LockKeyhole size={12} /> Your space is yours alone</span><button type="button" onClick={() => setMessage("Password reset isn't set up yet. Please contact your workspace administrator.")}>Forgot password?</button></div>}
            {connectionError && <p className="auth-message" role="alert">{connectionError}</p>}
            {message && <p className="auth-message" role="status">{message}</p>}
            <button className="auth-submit" type="submit" disabled={busy}>{busy ? "One moment…" : isSignup ? "Create your account" : "Sign in to Kindred"} {!busy && <ArrowRight size={16} />}</button>
          </form>

          <div className="auth-divider"><span /> <span>A LITTLE NOTE</span> <span /></div>
          <div className="demo-note"><ShieldCheck size={16} /><p><strong>Your details stay yours</strong><br />Your profile is saved to this workspace. Passwords are protected with a one-way salted hash.</p></div>
        </div>
        <div className="auth-panel-footer"><span>Made with a little more care.</span><a href="mailto:hello@kindred.support">Need a hand?</a></div>
      </section>
    </main>
  );
}

export default AuthScreen;
