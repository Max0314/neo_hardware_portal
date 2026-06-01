import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthGate } from './components/AuthGate';
import { NeoErrorBoundary } from './components/NeoErrorBoundary';
import { IdleSessionGuard } from './components/IdleSessionGuard';
import { HomePage } from './pages/HomePage';
import { DashboardPage } from './pages/DashboardPage';
import { GroupChatRoom } from './components/GroupChatRoom';
import { NetlistComparePage } from './pages/NetlistComparePage';
import { BomComparePage } from './pages/BomComparePage';
import { ReplacementPairsPage } from './pages/ReplacementPairsPage';
import { LeaderboardPage } from './pages/LeaderboardPage';

function App() {
  return (
    <BrowserRouter basename="/neo">
      <AuthGate>
        <IdleSessionGuard>
          <NeoErrorBoundary>
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/leaderboard" element={<LeaderboardPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/netlist-compare" element={<NetlistComparePage />} />
              <Route path="/bom-compare" element={<BomComparePage />} />
              <Route path="/replacement-pairs" element={<ReplacementPairsPage />} />
              <Route path="/meeting" element={
                <div className="h-screen w-screen">
                  <GroupChatRoom title="原理图AI审核" mode="schematic" />
                </div>
              } />
              <Route path="/bom-check" element={
                <div className="h-screen w-screen">
                  <GroupChatRoom title="BOM AI check" mode="bom" />
                </div>
              } />
            </Routes>
          </NeoErrorBoundary>
        </IdleSessionGuard>
      </AuthGate>
    </BrowserRouter>
  );
}

export default App;
