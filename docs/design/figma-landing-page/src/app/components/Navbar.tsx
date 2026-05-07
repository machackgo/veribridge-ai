import { Sparkles } from 'lucide-react';

export function Navbar() {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 px-6 py-4">
      <div className="max-w-7xl mx-auto">
        <div className="backdrop-blur-xl bg-white/70 rounded-2xl border border-slate-200/50 shadow-lg shadow-slate-900/5 px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-indigo-600 flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <span className="font-semibold text-slate-900">VeriBridge AI</span>
            </div>

            <div className="hidden md:flex items-center gap-8">
              <a href="#platform" className="text-sm text-slate-600 hover:text-slate-900 transition-colors">Platform</a>
              <a href="#students" className="text-sm text-slate-600 hover:text-slate-900 transition-colors">Students</a>
              <a href="#recruiters" className="text-sm text-slate-600 hover:text-slate-900 transition-colors">Recruiters</a>
              <a href="#universities" className="text-sm text-slate-600 hover:text-slate-900 transition-colors">Universities</a>
              <a href="#roadmap" className="text-sm text-slate-600 hover:text-slate-900 transition-colors">Roadmap</a>
            </div>

            <button className="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-emerald-600 text-white text-sm font-medium hover:from-emerald-600 hover:to-emerald-700 transition-all shadow-lg shadow-emerald-500/30">
              Start Building Profile
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
