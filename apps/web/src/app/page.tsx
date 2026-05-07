import {
  AIWorkflow,
  DashboardPreview,
  FinalCTA,
  Footer,
  Hero,
  Navbar,
  ProofOfSkill,
  ThreeSidedPlatform,
} from "../../components/landing";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <Navbar />
      <Hero />
      <ThreeSidedPlatform />
      <ProofOfSkill />
      <AIWorkflow />
      <DashboardPreview />
      <FinalCTA />
      <Footer />
    </main>
  );
}
