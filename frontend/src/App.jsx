import { useState } from 'react';
import './App.css';
import LoginPage from './pages/LoginPage';
import SearchPage from './pages/SearchPage';
import AdminDashboard from './pages/AdminDashboard';

export default function App() {
  const [user, setUser] = useState(null);

  const handleLogin = (userData) => setUser(userData);
  const handleLogout = () => setUser(null);

  if (!user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  if (user.role === 'administrator') {
    return <AdminDashboard user={user} onLogout={handleLogout} />;
  }

  return <SearchPage user={user} onLogout={handleLogout} />;
}
