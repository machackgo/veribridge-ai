import { Sparkles } from 'lucide-react';

export function Footer() {
  return (
    <footer className="relative py-12 px-6 bg-slate-900 border-t border-slate-800">
      <div className="max-w-7xl mx-auto">
        <div className="grid md:grid-cols-4 gap-8 mb-8">
          <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-indigo-600 flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <span className="font-semibold text-white">CareerProof AI</span>
            </div>
            <p className="text-sm text-slate-400">
              Proof-backed career readiness for verified students
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-4">Platform</h4>
            <ul className="space-y-2">
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">For Students</a></li>
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">For Recruiters</a></li>
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">For Universities</a></li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-4">Resources</h4>
            <ul className="space-y-2">
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Documentation</a></li>
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">API</a></li>
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Support</a></li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-white mb-4">Company</h4>
            <ul className="space-y-2">
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">About</a></li>
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Careers</a></li>
              <li><a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Contact</a></li>
            </ul>
          </div>
        </div>

        <div className="pt-8 border-t border-slate-800 flex flex-col md:flex-row justify-between items-center gap-4">
          <p className="text-sm text-slate-400">
            © 2026 CareerProof AI. All rights reserved.
          </p>
          <div className="flex gap-6">
            <a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Privacy</a>
            <a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Terms</a>
            <a href="#" className="text-sm text-slate-400 hover:text-white transition-colors">Security</a>
          </div>
        </div>
      </div>
    </footer>
  );
}
