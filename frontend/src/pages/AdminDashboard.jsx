import AuditDashboard from '../components/AuditDashboard';

export default function AdminDashboard({ user, onLogout }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex justify-between items-center">
        <span className="text-sm text-gray-500">
          Admin: <span className="font-medium text-gray-700">{user?.username}</span>
        </span>
        <button
          onClick={onLogout}
          className="text-sm text-red-600 hover:text-red-800 font-medium"
        >
          Sign Out
        </button>
      </header>
      <div className="container mx-auto p-6">
        <h1 className="text-3xl font-bold mb-6">Admin Dashboard</h1>
        <AuditDashboard />
      </div>
    </div>
  );
}
