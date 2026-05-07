import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/layout/Layout";
import { DashboardPage } from "@/pages/DashboardPage";
import { UniqualizerPage } from "@/pages/UniqualizerPage";
import { ShadowbanPage } from "@/pages/ShadowbanPage";
import { PnLPage } from "@/pages/PnLPage";
import { ProxyPage } from "@/pages/ProxyPage";
import { WarmupPage } from "@/pages/WarmupPage";
import { CookieFarmerPage } from "@/pages/CookieFarmerPage";
import { ProfilesPage } from "@/pages/ProfilesPage";
import { PricingPage } from "@/pages/PricingPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { ProfileLinksPage } from "@/pages/ProfileLinksPage";
import { ProfileJobsPage } from "@/pages/ProfileJobsPage";
import { UploadsPage } from "@/pages/UploadsPage";
import { QueuePage } from "@/pages/QueuePage";
import { ResearchPage } from "@/pages/ResearchPage";
import { DownloaderPage } from "@/pages/DownloaderPage";
import { SubtitlesPage } from "@/pages/SubtitlesPage";
import { CampaignPage } from "@/pages/CampaignPage";
import { LoginPage } from "@/pages/LoginPage";
import { ProfilePage } from "@/pages/cabinet/ProfilePage";
import { UsagePage } from "@/pages/cabinet/UsagePage";
import { BillingPage } from "@/pages/cabinet/BillingPage";
import { AdminUsersPage } from "@/pages/admin/AdminUsersPage";
import { AdminStatsPage } from "@/pages/admin/AdminStatsPage";
import { AdminSystemPage } from "@/pages/admin/AdminSystemPage";
import { ProtectedRoute } from "@/components/ProtectedRoute";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="uniqualizer" element={<UniqualizerPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="shadowban" element={<ShadowbanPage />} />
        <Route path="pnl" element={<PnLPage />} />
        <Route path="uploads" element={<UploadsPage />} />
        <Route path="queue" element={<QueuePage />} />
        <Route path="research" element={<ResearchPage />} />
        <Route path="downloader" element={<DownloaderPage />} />
        <Route path="subtitles" element={<SubtitlesPage />} />
        <Route path="campaigns" element={<CampaignPage />} />
        <Route path="proxy" element={<ProxyPage />} />
        <Route path="warmup" element={<WarmupPage />} />
        <Route path="cookie-farmer" element={<CookieFarmerPage />} />
        <Route path="accounts" element={<ProfilesPage />} />
        <Route path="profile-links" element={<ProfileLinksPage />} />
        <Route path="profile-jobs" element={<ProfileJobsPage />} />
        <Route path="pricing" element={<PricingPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route
          path="cabinet/profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="cabinet/usage"
          element={
            <ProtectedRoute>
              <UsagePage />
            </ProtectedRoute>
          }
        />
        <Route
          path="cabinet/billing"
          element={
            <ProtectedRoute>
              <BillingPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin/users"
          element={
            <ProtectedRoute requiredRole="admin">
              <AdminUsersPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin/stats"
          element={
            <ProtectedRoute requiredRole="admin">
              <AdminStatsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin/system"
          element={
            <ProtectedRoute requiredRole="admin">
              <AdminSystemPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
