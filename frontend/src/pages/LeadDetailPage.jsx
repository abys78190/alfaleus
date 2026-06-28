import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getLead, generateDrafts, generateSequence, getSequence, exportSequence, syncToCRM, retryEnrichment } from '../api/client';
import './LeadDetailPage.css';

function ScoreRing({ score, size = 90 }) {
  const r = 36, stroke = 6;
  const circ = 2 * Math.PI * r;
  const offset = circ - (Math.min(score || 0, 100) / 100) * circ;
  const color = score >= 80 ? '#00d4aa' : score >= 60 ? '#f59e0b' : '#ef4444';
  return (
    <svg width={size} height={size} viewBox="0 0 90 90">
      <circle cx="45" cy="45" r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={stroke} />
      <circle cx="45" cy="45" r={r} fill="none" stroke={color}
        strokeWidth={stroke} strokeLinecap="round"
        strokeDasharray={circ} strokeDashoffset={offset}
        transform="rotate(-90 45 45)"
        style={{ transition: 'stroke-dashoffset 1s ease' }} />
      <text x="45" y="50" textAnchor="middle" fill={color}
        fontSize="16" fontWeight="700" fontFamily="JetBrains Mono">
        {Math.round(score || 0)}
      </text>
    </svg>
  );
}

function ConfidenceDot({ level }) {
  const colors = { high: '#00d4aa', medium: '#f59e0b', low: '#ef4444' };
  return <span className="conf-dot" style={{ background: colors[level] || '#666' }} title={`Confidence: ${level}`} />;
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button className="btn btn-ghost btn-sm copy-btn" onClick={copy}>
      {copied ? '✅ Copied!' : '📋 Copy'}
    </button>
  );
}

const SIGNAL_ICONS = {
  recent_funding: '💰', hiring_expansion: '👥', tech_fit: '🔧', growth_news: '📈', leadership_hire: '👔',
};

const SOURCE_COLORS = {
  success: '#00d4aa', blocked: '#f59e0b', failed: '#ef4444', skipped: '#6666aa', empty: '#f59e0b',
};

export default function LeadDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [lead, setLead] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('overview');
  const [draftsLoading, setDraftsLoading] = useState(false);
  const [seqLoading, setSeqLoading] = useState(false);
  const [sequence, setSequence] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const fetch = async () => {
    try {
      const res = await getLead(id);
      setLead(res.data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetch(); }, [id]);

  const handleGenerateDrafts = async () => {
    setDraftsLoading(true);
    try {
      await generateDrafts(id);
      await fetch();
    } catch (e) { alert(e.message); }
    finally { setDraftsLoading(false); }
  };

  const handleGenerateSequence = async () => {
    setSeqLoading(true);
    try {
      const res = await generateSequence(id);
      setSequence(res.data);
      setTab('sequence');
    } catch (e) { alert(e.message); }
    finally { setSeqLoading(false); }
  };

  const handleLoadSequence = async () => {
    try {
      const res = await getSequence(id);
      setSequence(res.data);
    } catch (_) {}
  };

  useEffect(() => { if (tab === 'sequence' && !sequence) handleLoadSequence(); }, [tab]);

  const handleSync = async () => {
    setSyncing(true);
    try { await syncToCRM(id); setTimeout(fetch, 2000); }
    catch (e) { alert(e.message); }
    finally { setSyncing(false); }
  };

  const handleRetry = async () => {
    await retryEnrichment(id);
    setTimeout(fetch, 2000);
  };

  if (loading) return <div className="detail-loading"><div className="spinner" /></div>;
  if (!lead) return <div className="detail-error">Lead not found. <button className="link-btn" onClick={() => navigate('/')}>← Back</button></div>;

  const { enrichment: enr, drafts = [], crm_sync, score_history = [], icp_score_breakdown } = lead;

  const TABS = [
    { key: 'overview', label: '📋 Overview' },
    { key: 'signals', label: '⚡ Signals' },
    { key: 'outreach', label: '✉️ Outreach' },
    { key: 'sequence', label: '📅 Sequence' },
    { key: 'history', label: '📈 History' },
    { key: 'crm', label: '🔗 CRM' },
  ];

  return (
    <div className="lead-detail">
      {/* Header */}
      <div className="detail-header">
        <button className="back-btn" onClick={() => navigate('/')}>← Dashboard</button>
        <div className="lead-hero">
          <div className="hero-avatar">
            {(lead.name || lead.company || '?')[0].toUpperCase()}
          </div>
          <div className="hero-info">
            <h1 className="hero-name">{lead.name || 'Unknown Lead'}</h1>
            <div className="hero-meta">
              {enr?.contact_role && <span>{enr.contact_role}</span>}
              {lead.company && <span>@ <strong>{lead.company}</strong></span>}
              {lead.domain && <span className="text-muted">· {lead.domain}</span>}
            </div>
          </div>
          <div className="hero-score">
            <ScoreRing score={lead.total_score} />
            <div className="score-label-sm">Total Score</div>
          </div>
        </div>

        {/* Source chips */}
        {enr?.enriched_sources && (
          <div className="source-chips">
            {Object.entries(enr.enriched_sources).map(([src, status]) => (
              <span key={src} className="source-chip" style={{ borderColor: SOURCE_COLORS[status] || '#444' }}>
                <span className="source-dot" style={{ background: SOURCE_COLORS[status] || '#444' }} />
                {src}
              </span>
            ))}
          </div>
        )}

        {lead.status === 'failed' && (
          <button className="btn btn-secondary btn-sm" onClick={handleRetry}>🔄 Retry Enrichment</button>
        )}
      </div>

      {/* Tabs */}
      <div className="tab-bar">
        {TABS.map(t => (
          <button key={t.key} className={`tab-btn ${tab === t.key ? 'tab-btn--active' : ''}`}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {/* Overview */}
        {tab === 'overview' && (
          <div className="tab-pane overview-grid">
            <div className="overview-card card">
              <h3 className="card-title">🏢 Company Profile</h3>
              <dl className="detail-list">
                <dt>Company Size</dt>
                <dd>{enr?.company_size ? <><ConfidenceDot level={enr.company_size_confidence} /> {enr.company_size}</> : '—'}</dd>
                <dt>Industry</dt>
                <dd>{enr?.industry ? <><ConfidenceDot level={enr.industry_confidence} /> {enr.industry}{enr.sub_industry && ` / ${enr.sub_industry}`}</> : '—'}</dd>
                <dt>Funding</dt>
                <dd>{enr?.funding_status ? <><ConfidenceDot level={enr.funding_confidence} /> {enr.funding_status}</> : '—'}</dd>
                <dt>Tech Stack</dt>
                <dd>
                  {enr?.tech_stack?.length > 0
                    ? <div className="tech-chips">{enr.tech_stack.map(t => <span key={t} className="tech-chip">{t}</span>)}</div>
                    : '—'}
                </dd>
              </dl>
            </div>
            <div className="overview-card card">
              <h3 className="card-title">👤 Contact</h3>
              <dl className="detail-list">
                <dt>Role</dt>
                <dd>{enr?.contact_role || '—'}</dd>
                <dt>Seniority</dt>
                <dd>{enr?.contact_seniority || '—'}</dd>
                <dt>Email</dt>
                <dd>{lead.email || '—'}</dd>
                <dt>LinkedIn</dt>
                <dd>{lead.linkedin_url ? <a href={lead.linkedin_url} target="_blank" rel="noopener" className="link">View Profile ↗</a> : '—'}</dd>
              </dl>
            </div>
            {enr?.email_candidates?.length > 0 && (
              <div className="overview-card card full-width">
                <h3 className="card-title">📧 Email Candidates <span className="badge badge-info">Bonus</span></h3>
                <div className="email-candidates">
                  {enr.email_candidates.map((c, i) => (
                    <div key={i} className="email-candidate">
                      <code className="email-addr">{c.email}</code>
                      <span className={`badge badge-${c.confidence === 'high' ? 'success' : c.confidence === 'medium' ? 'warning' : 'info'}`}>
                        {c.confidence}
                      </span>
                      {c.mx_verified && <span className="badge badge-success">MX ✓</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {enr?.recent_news?.length > 0 && (
              <div className="overview-card card full-width">
                <h3 className="card-title">📰 Recent News</h3>
                <div className="news-list">
                  {enr.recent_news.slice(0, 5).map((n, i) => (
                    <a key={i} href={n.url} target="_blank" rel="noopener" className="news-item">
                      <span className={`news-signal signal-${n.signal_type}`}>{n.signal_type}</span>
                      <span className="news-title">{n.title}</span>
                      <span className="news-source">{n.source}</span>
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Signals */}
        {tab === 'signals' && (
          <div className="tab-pane">
            {icp_score_breakdown && (
              <div className="card score-breakdown-card">
                <h3 className="card-title">🎯 ICP Score Breakdown</h3>
                <div className="breakdown-grid">
                  {Object.entries(icp_score_breakdown).filter(([k]) => k !== 'disqualified').map(([k, v]) => (
                    <div key={k} className="breakdown-item">
                      <div className="breakdown-label">{k.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</div>
                      <div className="breakdown-bar-full">
                        <div className="breakdown-fill" style={{ width: `${v.score || 0}%`, background: v.matched ? 'var(--accent-secondary)' : 'var(--accent-warning)' }} />
                      </div>
                      <div className="breakdown-stats">
                        <span className="breakdown-score">{v.score || 0}</span>
                        <span className="breakdown-weight">weight: {v.weight}</span>
                        {v.matched && <span className="match-badge">✓ match</span>}
                      </div>
                    </div>
                  ))}
                </div>
                {icp_score_breakdown.disqualified && (
                  <div className="disq-banner">⚠ Disqualifier triggered — score penalised</div>
                )}
              </div>
            )}
            <div className="signals-list">
              <h3 className="card-title">⚡ Buying Signals</h3>
              {enr?.buying_signals?.length > 0 ? enr.buying_signals.map((sig, i) => (
                <div key={i} className="signal-card card">
                  <div className="signal-left">
                    <div className="signal-cat-icon">{SIGNAL_ICONS[sig.category] || '📊'}</div>
                    <div>
                      <div className="signal-text">{sig.signal}</div>
                      <div className="signal-source">Source: {sig.source}</div>
                    </div>
                  </div>
                  <div className="signal-strength">
                    <div className="strength-bar"><div className="strength-fill" style={{ width: `${sig.strength}%` }} /></div>
                    <span className="strength-num">{sig.strength}</span>
                  </div>
                </div>
              )) : <div className="no-data">No buying signals detected</div>}
            </div>
          </div>
        )}

        {/* Outreach */}
        {tab === 'outreach' && (
          <div className="tab-pane">
            {drafts.length === 0 ? (
              <div className="draft-empty card-glass">
                <div className="empty-icon">✉️</div>
                <h3>No drafts generated yet</h3>
                <p className="text-muted">Generate personalized outreach emails based on enriched data</p>
                <button className="btn btn-primary" onClick={handleGenerateDrafts} disabled={draftsLoading}>
                  {draftsLoading ? '⏳ Generating...' : '⚡ Generate Drafts'}
                </button>
              </div>
            ) : (
              <>
                <div className="drafts-header">
                  <h3 className="card-title">Outreach Drafts</h3>
                  <button className="btn btn-secondary btn-sm" onClick={handleGenerateDrafts} disabled={draftsLoading}>
                    {draftsLoading ? 'Regenerating...' : '🔄 Regenerate'}
                  </button>
                </div>
                <div className="drafts-grid">
                  {drafts.map(draft => (
                    <div key={draft.id} className="draft-card card">
                      <div className="draft-header">
                        <span className={`tone-badge tone-${draft.tone}`}>
                          {draft.tone === 'direct' ? '⚡ Direct' : '🤝 Social Proof'}
                        </span>
                        <CopyButton text={`Subject: ${draft.subject}\n\n${draft.body}\n\n${draft.call_to_action}`} />
                      </div>
                      <div className="draft-content-wrap">
                        <div className="draft-subject">{draft.subject}</div>
                        <div className="draft-body">{draft.body}</div>
                        <div className="draft-cta">{draft.call_to_action}</div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="sequence-cta">
                  <button className="btn btn-secondary" onClick={handleGenerateSequence} disabled={seqLoading}>
                    {seqLoading ? '⏳ Building...' : '📅 Build 3-Step Sequence'}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {/* Sequence */}
        {tab === 'sequence' && (
          <div className="tab-pane">
            {!sequence ? (
              <div className="draft-empty card-glass">
                <div className="empty-icon">📅</div>
                <h3>No sequence yet</h3>
                <p className="text-muted">Build a 3-step outreach sequence (Day 0, Day 3, Day 7)</p>
                <button className="btn btn-primary" onClick={handleGenerateSequence} disabled={seqLoading}>
                  {seqLoading ? '⏳ Generating...' : '⚡ Generate Sequence'}
                </button>
              </div>
            ) : (
              <div>
                <div className="seq-header">
                  <h3 className="card-title">3-Step Outreach Sequence</h3>
                  <button className="btn btn-secondary btn-sm" onClick={() => exportSequence(id)}>📥 Export CSV</button>
                </div>
                <div className="sequence-steps">
                  {sequence.steps?.map((step, i) => (
                    <div key={i} className="seq-step card">
                      <div className="seq-step-header">
                        <div className="seq-day">Day {step.delay_days}</div>
                        <span className="badge badge-info">{step.tone}</span>
                        <span className="seq-desc">{step.description}</span>
                        <CopyButton text={`Subject: ${step.subject}\n\n${step.body}\n\n${step.call_to_action}`} />
                      </div>
                      <div className="draft-subject">{step.subject}</div>
                      <div className="draft-body">{step.body}</div>
                      <div className="draft-cta">{step.call_to_action}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* History */}
        {tab === 'history' && (
          <div className="tab-pane">
            <h3 className="card-title">📈 Score History</h3>
            {score_history.length === 0 ? (
              <div className="no-data">No score history yet. Re-run enrichment to track changes.</div>
            ) : (
              <>
                <div className="history-chart card">
                  <svg viewBox={`0 0 ${Math.max(score_history.length * 80, 400)} 120`} style={{ width: '100%', height: '120px' }}>
                    {score_history.map((h, i) => {
                      const x = i * 80 + 40;
                      const y = 100 - (h.total_score / 100) * 80;
                      const prev = i > 0 ? score_history[i - 1] : null;
                      return (
                        <g key={i}>
                          {prev && (
                            <line x1={(i - 1) * 80 + 40} y1={100 - (prev.total_score / 100) * 80}
                              x2={x} y2={y} stroke="var(--accent-primary)" strokeWidth="2" />
                          )}
                          <circle cx={x} cy={y} r="5" fill="var(--accent-primary)" />
                          <text x={x} y={y - 10} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
                            {Math.round(h.total_score)}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
                <table className="data-table">
                  <thead><tr><th>Date</th><th>ICP Score</th><th>Total Score</th><th>Signals</th></tr></thead>
                  <tbody>
                    {score_history.map((h, i) => (
                      <tr key={i}>
                        <td>{new Date(h.recorded_at).toLocaleDateString()}</td>
                        <td>{Math.round(h.icp_score)}</td>
                        <td><strong>{Math.round(h.total_score)}</strong></td>
                        <td>{h.buying_signal_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}

        {/* CRM */}
        {tab === 'crm' && (
          <div className="tab-pane">
            <div className="crm-card card">
              <h3 className="card-title">🔗 Notion CRM Sync</h3>
              <div className="crm-status-row">
                <div>
                  <div className="crm-status-val">
                    <span className={`badge badge-${crm_sync?.status === 'synced' || crm_sync?.status === 'updated' ? 'success' : crm_sync?.status === 'failed' ? 'danger' : 'info'}`}>
                      {crm_sync?.status || 'Not synced'}
                    </span>
                  </div>
                  {crm_sync?.synced_at && <div className="crm-date">Last synced: {new Date(crm_sync.synced_at).toLocaleString()}</div>}
                  {crm_sync?.crm_record_id && <div className="crm-id text-muted">Record ID: {crm_sync.crm_record_id.slice(0, 20)}...</div>}
                  {crm_sync?.error_message && <div className="error-text">{crm_sync.error_message}</div>}
                </div>
                <button className="btn btn-primary" onClick={handleSync} disabled={syncing || lead.status !== 'enriched'}>
                  {syncing ? 'Syncing...' : crm_sync?.status ? '🔄 Re-sync' : '🔗 Sync to Notion'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
