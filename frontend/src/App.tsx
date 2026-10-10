import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Dashboard } from "./pages/Dashboard";
import { Targets } from "./pages/Targets";
import { History } from "./pages/History";
import { RoamHistory } from "./pages/RoamHistory";
import { WalkTest } from "./pages/WalkTest";
import { WalkTestResult } from "./pages/WalkTestResult";
import { RfTools } from "./pages/RfTools";
import { Settings } from "./pages/Settings";

export default function App() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-[1200px] mx-auto px-6 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/targets" element={<Targets />} />
            <Route path="/history" element={<History />} />
            <Route path="/roaming" element={<RoamHistory />} />
            <Route path="/walk-test" element={<WalkTest />} />
            <Route path="/walk-test/:id" element={<WalkTestResult />} />
            <Route path="/rf-tools" element={<RfTools />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
