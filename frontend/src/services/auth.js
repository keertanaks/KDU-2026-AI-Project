import { authAPI } from './api.js';

export async function login(username, password) {
  await authAPI.login(username, password);
}

export async function logout() {
  await authAPI.logout();
}
