import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";
import { getToken } from "./api";
import Sidebar from "./components/Sidebar";
import LoginPage from "./pages/LoginPage";
import StoresPage from "./pages/StoresPage";
import StoreDetailPage from "./pages/StoreDetailPage";
import ConversationsPage from "./pages/ConversationsPage";
import SettingsPage from "./pages/SettingsPage";
import AiUsagePage from "./pages/AiUsagePage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex-1">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/stores"
          element={
            <RequireAuth>
              <Layout>
                <StoresPage />
              </Layout>
            </RequireAuth>
          }
        />
        <Route
          path="/stores/:storeId"
          element={
            <RequireAuth>
              <Layout>
                <StoreDetailPage />
              </Layout>
            </RequireAuth>
          }
        />
        <Route
          path="/conversations"
          element={
            <RequireAuth>
              <Layout>
                <ConversationsPage />
              </Layout>
            </RequireAuth>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAuth>
              <Layout>
                <SettingsPage />
              </Layout>
            </RequireAuth>
          }
        />
        <Route
          path="/ai-usage"
          element={
            <RequireAuth>
              <Layout>
                <AiUsagePage />
              </Layout>
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/stores" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
