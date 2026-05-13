import axios from 'axios';

const API_BASE = '/api';

export const apiClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true  // Send cookies
});

export const searchAPI = {
  search: (query) => apiClient.post('/search', { query }),
  upload: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return apiClient.post('/ingest', formData);
  }
};

export const authAPI = {
  login: (username, password) => apiClient.post('/auth/login', { username, password }),
  logout: () => apiClient.post('/auth/logout')
};
