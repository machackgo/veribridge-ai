import { Navbar } from './components/Navbar';
import { Hero } from './components/Hero';
import { ThreeSidedPlatform } from './components/ThreeSidedPlatform';
import { ProofOfSkill } from './components/ProofOfSkill';
import { AIWorkflow } from './components/AIWorkflow';
import { DashboardPreview } from './components/DashboardPreview';
import { FinalCTA } from './components/FinalCTA';
import { Footer } from './components/Footer';

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50">
      <Navbar />
      <Hero />
      <ThreeSidedPlatform />
      <ProofOfSkill />
      <AIWorkflow />
      <DashboardPreview />
      <FinalCTA />
      <Footer />
    </div>
  );
}