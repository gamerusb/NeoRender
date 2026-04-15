import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "@/layout/Layout";
import { DashboardPage } from "@/pages/DashboardPage";
import { UniqualizerPage } from "@/pages/UniqualizerPage";
import { ShadowbanPage } from "@/pages/ShadowbanPage";
import { PnLPage } from "@/pages/PnLPage";
import { ProxyPage } from "@/pages/ProxyPage";
import { WarmupPage } from "@/pages/WarmupPage";
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

export function App() {
  return (
    <Routes>
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
        <Route path="accounts" element={<ProfilesPage />} />
        <Route path="profile-links" element={<ProfileLinksPage />} />
        <Route path="profile-jobs" element={<ProfileJobsPage />} />
        <Route path="pricing" element={<PricingPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
