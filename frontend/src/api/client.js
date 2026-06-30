import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'https://alfaleus-backend-production.up.railway.app/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  timeout: 60000,
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const message = err.response?.data?.detail || err.message || 'An error occurred';
    return Promise.reject(new Error(message));
  }
);

// Leads
export const uploadCSV = (formData) => api.post('/leads/upload', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
});
export const getLeads = (params = {}) => api.get('/leads', { params });
export const getLead = (id) => api.get(`/leads/${id}`);
export const deleteLead = (id) => api.delete(`/leads/${id}`);
export const submitExtensionLead = (data) => api.post('/leads/extension', data);
export const submitDomainLead = (domain) => api.post('/leads/domain', { domain });

// ICP
export const getICP = () => api.get('/icp');
export const saveICP = (data) => api.post('/icp', data);
export const previewICP = (sampleLead) => api.post('/icp/preview', { sample_lead: sampleLead });

// Enrichment
export const retryEnrichment = (id) => api.post(`/enrichment/${id}/retry`);
export const getEnrichmentStatus = (id) => api.get(`/enrichment/${id}/status`);

// Drafts
export const getDrafts = (leadId) => api.get(`/drafts/${leadId}`);
export const generateDrafts = (leadId) => api.post(`/drafts/${leadId}/generate`);
export const generateSequence = (leadId) => api.post(`/drafts/sequence/${leadId}`);
export const getSequence = (leadId) => api.get(`/drafts/sequence/${leadId}`);
export const exportSequence = (leadId) => {
  window.open(`${API_BASE}/drafts/sequence/${leadId}/export`, '_blank');
};

// CRM
export const syncToCRM = (leadId) => api.post(`/crm/sync/${leadId}`);
export const syncAll = () => api.post('/crm/sync/all');
export const getCRMStatus = (leadId) => api.get(`/crm/status/${leadId}`);

// SSE
export const createLeadSSE = (leadId) =>
  new EventSource(`${API_BASE}/leads/sse/${leadId}`);
export const createPipelineSSE = () =>
  new EventSource(`${API_BASE}/leads/sse/pipeline`);

export default api;
