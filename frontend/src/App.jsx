import React, { useCallback, useEffect, useRef, useState } from "react";
import { LogOut } from "lucide-react";
import AuthScreen from "./AuthScreen.jsx";
import "./auth.css";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileText,
  Headphones,
  Inbox,
  LoaderCircle,
  Menu,
  MessageCircle,
  MoreHorizontal,
  Paperclip,
  Plus,
  Settings2,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Upload,
  X,
} from "lucide-react";

const DEFAULT_API_URL = window.location.port === "5173"
  ? `${window.location.protocol}//${window.location.hostname}:8000/api`
  : `${window.location.origin}/api`;
const API_URL = import.meta.env.VITE_API_URL || DEFAULT_API_URL;
const getInitials = (name) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0].toUpperCase()).join("");
const SUGGESTIONS = [
  { icon: ArrowDownToLine, text: "How do I return an order?", tag: "RETURNS" },
  { icon: Clock3, text: "When will my order arrive?", tag: "SHIPPING" },
  { icon: ShieldCheck, text: "What's covered by my warranty?", tag: "WARRANTY" },
  { icon: CircleHelp, text: "How do I reset my password?", tag: "ACCOUNT" },
];

const formatCharacters = (value) =>
  value > 999 ? `${(value / 1000).toFixed(1)}k` : `${value} characters`;

async function api(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, { credentials: "include", ...options });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(body.detail || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function App() {
  const [authUser, setAuthUser] = useState(null);
  const [isAuthReady, setIsAuthReady] = useState(false);
  const [isAuthSubmitting, setIsAuthSubmitting] = useState(false);
  const [authConnectionError, setAuthConnectionError] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [documents, setDocuments] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isKnowledgeOpen, setIsKnowledgeOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [apiError, setApiError] = useState("");
  const [notice, setNotice] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const fileRef = useRef(null);

  useEffect(() => {
    let isMounted = true;
    api("/auth/me")
      .then((result) => {
        if (isMounted) setAuthUser(result.user);
      })
      .catch((error) => {
        if (isMounted && error.status !== 401) {
          setAuthConnectionError("We couldn't connect to the account service. Please check that the API is running.");
        }
      })
      .finally(() => {
        if (isMounted) setIsAuthReady(true);
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await api("/documents");
      setDocuments(data.documents);
      setApiError("");
    } catch (error) {
      if (error.status === 401) {
        setAuthUser(null);
      } else {
        setApiError(error.message || "Can't reach your support assistant. Start the API to connect.");
      }
    }
  }, []);

  useEffect(() => {
    if (authUser) loadDocuments();
  }, [authUser, loadDocuments]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, isTyping]);

  useEffect(() => {
    if (notice) {
      const timer = window.setTimeout(() => setNotice(""), 3600);
      return () => window.clearTimeout(timer);
    }
  }, [notice]);

  async function sendMessage(message = input) {
    const question = message.trim();
    if (!question || isTyping) return;
    const messageId = crypto.randomUUID();
    setMessages((items) => [...items, { id: messageId, role: "user", text: question }]);
    setInput("");
    setIsTyping(true);
    requestAnimationFrame(() => inputRef.current?.focus());
    try {
      const result = await api("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question }),
      });
      setMessages((items) => [
        ...items,
        { id: crypto.randomUUID(), role: "assistant", text: result.answer, sources: result.sources, confidence: result.confidence },
      ]);
      setApiError("");
    } catch (error) {
      if (error.status === 401) setAuthUser(null);
      setMessages((items) => [
        ...items,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: error.message || "Something went wrong. Please try again.",
          error: true,
          sources: [],
        },
      ]);
    } finally {
      setIsTyping(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }

  async function handleFiles(files) {
    const file = files?.[0];
    if (!file) return;
    setIsUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const uploaded = await api("/documents", { method: "POST", body: form });
      setDocuments((current) => [...current, uploaded]);
      setNotice(`“${uploaded.title}” is ready to use.`);
      setIsKnowledgeOpen(false);
      setApiError("");
    } catch (error) {
      setNotice(error.message);
    } finally {
      setIsUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function removeDocument(document) {
    try {
      await api(`/documents/${document.id}`, { method: "DELETE" });
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setNotice(`“${document.title}” removed from your knowledge base.`);
    } catch (error) {
      if (error.status === 401) setAuthUser(null);
      setNotice(error.message);
    }
  }

  async function submitAuthentication(mode, credentials) {
    setIsAuthSubmitting(true);
    setAuthConnectionError("");
    try {
      const endpoint = mode === "signup" ? "signup" : "login";
      const result = await api(`/auth/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      });
      setAuthUser(result.user);
      setMessages([]);
      setInput("");
    } catch (error) {
      if (!error.status || error.status >= 500) {
        setAuthConnectionError("We couldn't connect to the account service. Please try again.");
      }
      throw error;
    } finally {
      setIsAuthSubmitting(false);
    }
  }

  async function signOut() {
    try {
      await api("/auth/logout", { method: "POST" });
      setAuthUser(null);
      setMessages([]);
      setDocuments([]);
      setApiError("");
    } catch (error) {
      if (error.status === 401) {
        setAuthUser(null);
      } else {
        setNotice(error.message || "Couldn't sign out. Please try again.");
      }
    }
  }

  function startFresh() {
    setMessages([]);
    setInput("");
    setIsSidebarOpen(false);
    inputRef.current?.focus();
  }

  const sampleCount = documents.filter((doc) => doc.is_sample).length;

  if (!isAuthReady) {
    return <main className="auth-loading"><div className="auth-loading-mark"><Sparkles size={19} /></div><span>Getting your space ready…</span></main>;
  }

  if (!authUser) {
    return <AuthScreen onSubmit={submitAuthentication} busy={isAuthSubmitting} connectionError={authConnectionError} />;
  }

  return (
    <main className="app-shell">
      {isSidebarOpen && <button className="mobile-scrim" aria-label="Close menu" onClick={() => setIsSidebarOpen(false)} />}
      <aside className={`sidebar ${isSidebarOpen ? "sidebar-open" : ""}`}>
        <a className="brand" href="#" onClick={(event) => event.preventDefault()} aria-label="Kindred home">
          <span className="brand-mark"><span /><span /><span /><span /></span>
          <span className="brand-word">kindred<span className="brand-period">.</span></span>
        </a>
        <div className="workspace-switcher">
          <div className="workspace-avatar">{getInitials(authUser.display_name).slice(0, 1)}</div>
          <div className="workspace-name"><span>{authUser.display_name}'s workspace</span><small>{authUser.email}</small></div>
          <ChevronDown size={15} strokeWidth={1.8} />
        </div>
        <span className="nav-caption">WORKSPACE</span>
        <nav className="main-nav" aria-label="Workspace navigation">
          <button className="nav-item active" onClick={startFresh}><MessageCircle size={17} /> <span>AI assistant</span><span className="nav-live" /></button>
          <button className="nav-item" onClick={() => setNotice("Your inbox is all caught up.")}><Inbox size={17} /> <span>Inbox</span><span className="nav-count">3</span></button>
          <button className="nav-item" onClick={() => setIsKnowledgeOpen(true)}><BookOpen size={17} /> <span>Knowledge base</span><span className="nav-count">{documents.length}</span></button>
          <button className="nav-item" onClick={() => setNotice("Analytics are coming soon.")}><Settings2 size={17} /> <span>Insights</span></button>
        </nav>
        <div className="sidebar-divider" />
        <div className="recent-heading"><span className="nav-caption">RECENT CONVERSATIONS</span><button aria-label="New conversation" onClick={startFresh}><Plus size={16} /></button></div>
        {messages.length > 0 ? (
          <button className="conversation-link current-conversation" onClick={() => setIsSidebarOpen(false)}>
            <span className="conversation-dot" />{messages.find((item) => item.role === "user")?.text}
          </button>
        ) : (
          <div className="empty-recent">Your conversations will show up here.</div>
        )}
        <div className="sidebar-spacer" />
        <div className="plan-card">
          <div className="plan-top"><span className="plan-spark"><Sparkles size={14} /></span><span>You're off to a great start</span></div>
          <p>Your AI has learned from <strong>{documents.length} helpful resources.</strong></p>
          <button onClick={() => setIsKnowledgeOpen(true)}>Add more knowledge <ArrowRight size={13} /></button>
        </div>
        <button className="profile-row" onClick={() => setNotice("Account settings are coming soon.")}>
          <div className="profile-avatar">{getInitials(authUser.display_name)}<span /></div>
          <div className="profile-info"><span>{authUser.display_name}</span><small>{authUser.email}</small></div>
          <MoreHorizontal size={19} />
        </button>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <button className="mobile-menu icon-button" onClick={() => setIsSidebarOpen(true)} aria-label="Open menu"><Menu size={19} /></button>
          <div className="breadcrumb"><span className="breadcrumb-muted">Workspace</span><ChevronRight size={14} /><span>AI assistant</span></div>
          <div className="topbar-right">
            <div className="status-pill"><span className="status-dot" /> All systems operational</div>
            <button className="icon-button help-button" aria-label="Help" onClick={() => setNotice("Need a hand? Reach us at hello@kindred.support.")}><CircleHelp size={18} /></button>
            <button className="sign-out-button" onClick={signOut}><LogOut size={14} /><span>Sign out</span></button>
          </div>
        </header>

        <div className="workspace-content">
          <div className="chat-column">
            <section className="conversation-header">
              <div className="assistant-ident">
                <div className="assistant-avatar"><Sparkles size={19} fill="currentColor" /></div>
                <div><h1>Your AI assistant</h1><p><span className="online-dot" /> Ready to help your customers</p></div>
              </div>
              <div className="header-actions">
                <button className="header-button" onClick={() => setIsKnowledgeOpen(true)}><BookOpen size={15} /> <span>Knowledge</span></button>
                <button className="header-button header-icon" aria-label="Conversation options" onClick={() => setNotice("Your chat is private and powered by your knowledge base.")}><MoreHorizontal size={19} /></button>
              </div>
            </section>

            {apiError && <div className="connection-banner"><CircleHelp size={16} /><span>{apiError}</span><button onClick={loadDocuments}>Retry</button></div>}

            <div className="chat-scroll" ref={scrollRef}>
              {messages.length === 0 ? (
                <div className="welcome">
                  <div className="welcome-orbit"><span className="orbit-dot dot-one" /><span className="orbit-dot dot-two" /><span className="orbit-dot dot-three" /><div className="orbit-center"><Sparkles size={27} /></div></div>
                  <div className="welcome-label"><span /> YOUR SUPPORT, AT ITS BEST <span /></div>
                  <h2>Every great conversation<br />starts <span>right here.</span></h2>
                  <p className="welcome-copy">Ask me anything about your products, policies, or orders.<br className="desktop-break" /> I’ll find the right answer, straight from your knowledge base.</p>
                  <div className="suggestion-grid">
                    {SUGGESTIONS.map(({ icon: Icon, text, tag }) => (
                      <button className="suggestion-card" key={text} onClick={() => sendMessage(text)}>
                        <span className="suggestion-top"><span className="suggestion-icon"><Icon size={15} /></span><span className="suggestion-tag">{tag}</span></span>
                        <span className="suggestion-text">{text}</span>
                        <ArrowRight className="suggestion-arrow" size={15} />
                      </button>
                    ))}
                  </div>
                  <div className="welcome-foot"><ShieldCheck size={14} /><span>Answers are grounded in your knowledge base</span><span className="foot-separator">·</span><span>Nothing made up</span></div>
                </div>
              ) : (
                <div className="message-list">
                  <div className="conversation-day"><span /> TODAY <span /></div>
                  {messages.map((message) => (
                    <article className={`message-row ${message.role === "user" ? "user-message-row" : ""}`} key={message.id}>
                      {message.role === "assistant" && <div className="message-avatar"><Sparkles size={14} fill="currentColor" /></div>}
                      <div className="message-body">
                        <div className="message-meta"><strong>{message.role === "user" ? "You" : "Kindred assistant"}</strong><span>{message.role === "user" ? "just now" : <><span className="meta-dot" /> just now</>}</span></div>
                        <div className={`message-bubble ${message.role === "user" ? "user-bubble" : ""} ${message.error ? "error-bubble" : ""}`}>{message.text}</div>
                        {message.role === "assistant" && message.sources?.length > 0 && (
                          <div className="sources-wrap">
                            <div className="source-label"><ShieldCheck size={13} /> GROUNDED IN {message.sources.length} {message.sources.length === 1 ? "SOURCE" : "SOURCES"} <span className={`confidence confidence-${message.confidence}`}>{message.confidence} match</span></div>
                            <div className="source-list">{message.sources.map((source) => <div className="source-card" key={source.document_id}><FileText size={15} /><div><strong>{source.title}</strong><span>{source.excerpt}</span></div><span className="source-score">{Math.round(source.relevance * 100)}%</span></div>)}</div>
                          </div>
                        )}
                        {message.role === "assistant" && !message.error && <div className="response-actions"><span>Was this helpful?</span><button title="Helpful" onClick={() => setNotice("Thanks for your feedback!")}><ThumbsUp size={14} /></button><button title="Not helpful" onClick={() => setNotice("Thanks for your feedback!")}><ThumbsDown size={14} /></button></div>}
                      </div>
                      {message.role === "user" && <div className="user-avatar">JD</div>}
                    </article>
                  ))}
                  {isTyping && <div className="message-row"><div className="message-avatar"><Sparkles size={14} fill="currentColor" /></div><div className="typing-bubble"><span /><span /><span /></div></div>}
                </div>
              )}
            </div>

            <div className="composer-area">
              <div className="composer">
                <textarea ref={inputRef} rows={1} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } }} placeholder="Ask anything about your business…" aria-label="Ask a question" />
                <div className="composer-toolbar">
                  <div className="composer-tools"><button className="composer-tool" onClick={() => fileRef.current?.click()} title="Add knowledge document"><Paperclip size={16} /><span>Add knowledge</span></button><span className="composer-tool-divider" /><span className="grounded-indicator"><ShieldCheck size={14} /> Grounded answers</span></div>
                  <div className="send-side"><span className="keyboard-hint"><kbd>↵</kbd> to send</span><button className="send-button" onClick={() => sendMessage()} disabled={!input.trim() || isTyping} aria-label="Send message">{isTyping ? <LoaderCircle size={16} className="spin" /> : <ArrowUp size={17} strokeWidth={2.2} />}</button></div>
                </div>
              </div>
              <p className="composer-disclaimer"><Sparkles size={12} /> Kindred AI can make mistakes. Answers are based on your uploaded resources.</p>
            </div>
          </div>

          <aside className="context-panel">
            <div className="context-title"><div><span className="eyebrow">YOUR ASSISTANT</span><h2>At a glance</h2></div><button className="icon-button" aria-label="Settings" onClick={() => setNotice("Assistant settings are coming soon.")}><Settings2 size={17} /></button></div>
            <div className="assistant-card">
              <div className="assistant-card-top"><div className="assistant-card-avatar"><Sparkles size={17} fill="currentColor" /></div><span className="active-badge"><span /> ACTIVE</span></div>
              <h3>{authUser.display_name}'s assistant</h3><p>Here for the little things and the big questions.</p>
              <div className="card-bottom"><span><Headphones size={13} /> Customer support</span><span>·</span><span>English</span></div>
            </div>
            <div className="context-section">
              <div className="section-heading"><div><h3>Knowledge base</h3><span className="section-subtitle">What your AI knows</span></div><button className="text-action" onClick={() => setIsKnowledgeOpen(true)}>Manage <ArrowRight size={13} /></button></div>
              <div className="knowledge-stats"><div className="knowledge-number">{documents.length}<span> resources</span></div><span className="ready-chip"><Check size={12} /> Up to date</span></div>
              <div className="progress-track"><span style={{ width: `${Math.min(100, documents.length * 12)}%` }} /></div>
              <div className="resource-list">
                {documents.slice(0, 4).map((document, index) => (
                  <button className="resource-row" key={document.id} onClick={() => setIsKnowledgeOpen(true)}>
                    <span className={`resource-icon resource-color-${index % 4}`}><FileText size={14} /></span>
                    <span className="resource-copy"><strong>{document.title}</strong><small>{document.category} <span>·</span> {formatCharacters(document.characters)}</small></span>
                    <ChevronRight size={15} />
                  </button>
                ))}
                {documents.length === 0 && <div className="no-resources">Add a resource to teach your AI about your business.</div>}
              </div>
              <button className="add-resource-button" onClick={() => setIsKnowledgeOpen(true)}><Plus size={15} /> Add a resource</button>
              {sampleCount > 0 && <p className="sample-note">{sampleCount} sample policies included to help you explore.</p>}
            </div>
            <div className="context-section quick-tips">
              <div className="section-heading"><div><h3>Make it yours</h3><span className="section-subtitle">A few helpful next steps</span></div></div>
              <button className="tip-row" onClick={() => setIsKnowledgeOpen(true)}><span className="tip-number">01</span><span><strong>Upload your FAQs</strong><small>Teach your AI the way you help.</small></span><ArrowRight size={14} /></button>
              <button className="tip-row" onClick={() => setNotice("Personalization settings are coming soon.")}><span className="tip-number">02</span><span><strong>Set your brand voice</strong><small>Sound unmistakably like you.</small></span><ArrowRight size={14} /></button>
            </div>
            <div className="privacy-note"><ShieldCheck size={16} /><span><strong>Your data stays yours.</strong><br />Private, secure, and only used to help your customers.</span></div>
          </aside>
        </div>
      </section>

      {isKnowledgeOpen && (
        <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setIsKnowledgeOpen(false); }}>
          <section className="knowledge-modal" role="dialog" aria-modal="true" aria-labelledby="knowledge-modal-title">
            <div className="modal-heading"><div><div className="modal-icon"><BookOpen size={18} /></div><div><h2 id="knowledge-modal-title">Your knowledge base</h2><p>The answers your AI learns from.</p></div></div><button className="icon-button" onClick={() => setIsKnowledgeOpen(false)} aria-label="Close"><X size={19} /></button></div>
            <button className={`upload-zone ${isDragging ? "upload-zone-active" : ""}`} onClick={() => fileRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setIsDragging(true); }} onDragLeave={() => setIsDragging(false)} onDrop={(event) => { event.preventDefault(); setIsDragging(false); handleFiles(event.dataTransfer.files); }} disabled={isUploading}>
              <span className="upload-icon">{isUploading ? <LoaderCircle size={21} className="spin" /> : <Upload size={21} />}</span>
              <strong>{isUploading ? "Adding to your knowledge…" : "Drop a file here or browse"}</strong>
              <span>PDF, DOCX, TXT, or Markdown · up to 10 MB</span>
            </button>
            <div className="modal-list-heading"><span>RESOURCES <span className="resource-count">{documents.length}</span></span><span>Your AI learns from all of these</span></div>
            <div className="modal-resource-list">
              {documents.map((document, index) => (
                <div className="modal-resource-row" key={document.id}>
                  <span className={`resource-icon resource-color-${index % 4}`}><FileText size={15} /></span>
                  <div className="modal-resource-copy"><strong>{document.title}</strong><span>{document.category} · {formatCharacters(document.characters)}</span></div>
                  {document.is_sample ? <span className="sample-resource-tag">SAMPLE</span> : <button className="remove-document" onClick={() => removeDocument(document)} aria-label={`Remove ${document.title}`}><X size={15} /></button>}
                </div>
              ))}
              {documents.length === 0 && <div className="modal-empty">No resources yet. Add your first document above.</div>}
            </div>
            <div className="modal-footer"><span><ShieldCheck size={14} /> Your documents are stored locally.</span><button onClick={() => setIsKnowledgeOpen(false)}>Done <CheckCheck size={14} /></button></div>
          </section>
        </div>
      )}
      <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={(event) => handleFiles(event.target.files)} />
      {notice && <div className="toast"><span className="toast-check"><Check size={14} /></span>{notice}<button onClick={() => setNotice("")} aria-label="Dismiss"><X size={14} /></button></div>}
    </main>
  );
}

export default App;
