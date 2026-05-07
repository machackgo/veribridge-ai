import { motion } from 'motion/react';
import { ArrowRight, CheckCircle2, Award, TrendingUp, Shield } from 'lucide-react';

export function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center px-6 pt-32 pb-20 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-slate-50 via-indigo-50/30 to-emerald-50/20"></div>

      <div className="absolute inset-0 opacity-30">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-emerald-400/20 rounded-full blur-3xl"></div>
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-indigo-400/20 rounded-full blur-3xl"></div>
      </div>

      <div className="relative max-w-7xl mx-auto grid md:grid-cols-2 gap-12 items-center">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-gradient-to-r from-emerald-500/10 to-indigo-500/10 border border-emerald-500/20 mb-6">
            <Shield className="w-4 h-4 text-emerald-600" />
            <span className="text-sm text-slate-700">Verified .edu Students Only</span>
          </div>

          <h1 className="text-5xl md:text-6xl font-bold text-slate-900 leading-tight mb-6">
            Verified student talent, backed by real evidence.
          </h1>

          <p className="text-lg text-slate-600 mb-8 leading-relaxed">
            VeriBridge AI helps verified students turn projects, coursework, resumes, and applications into evidence-backed career profiles recruiters and universities can trust.
          </p>

          <div className="flex flex-wrap gap-4">
            <button className="px-8 py-4 rounded-xl bg-gradient-to-r from-emerald-500 to-emerald-600 text-white font-medium hover:from-emerald-600 hover:to-emerald-700 transition-all shadow-xl shadow-emerald-500/30 flex items-center gap-2 group">
              Start Building Profile
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
            <button className="px-8 py-4 rounded-xl bg-white/80 backdrop-blur-sm border border-slate-200 text-slate-700 font-medium hover:bg-white hover:border-slate-300 transition-all shadow-lg">
              View Platform
            </button>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.7, delay: 0.2 }}
          className="relative"
        >
          <div className="relative">
            <motion.div
              animate={{ y: [0, -10, 0] }}
              transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
              className="relative"
            >
              <div className="backdrop-blur-xl bg-white/60 rounded-3xl border border-slate-200/50 shadow-2xl shadow-slate-900/10 p-8 relative overflow-hidden">
                <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-indigo-500/5"></div>

                <div className="relative space-y-6">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-slate-900">Career Dashboard</h3>
                    <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-700 text-xs font-medium">Active</span>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="backdrop-blur-sm bg-gradient-to-br from-emerald-500/10 to-emerald-600/10 rounded-2xl p-4 border border-emerald-200/50">
                      <TrendingUp className="w-8 h-8 text-emerald-600 mb-2" />
                      <div className="text-3xl font-bold text-slate-900 mb-1">92</div>
                      <div className="text-xs text-slate-600">Career Readiness</div>
                    </div>

                    <div className="backdrop-blur-sm bg-gradient-to-br from-indigo-500/10 to-indigo-600/10 rounded-2xl p-4 border border-indigo-200/50">
                      <Award className="w-8 h-8 text-indigo-600 mb-2" />
                      <div className="text-3xl font-bold text-slate-900 mb-1">15</div>
                      <div className="text-xs text-slate-600">Verified Skills</div>
                    </div>
                  </div>

                  <div className="backdrop-blur-sm bg-white/50 rounded-2xl p-4 border border-slate-200/50">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-sm font-medium text-slate-700">Job Match Score</span>
                      <span className="text-sm font-bold text-emerald-600">88%</span>
                    </div>
                    <div className="h-2 bg-slate-200/50 rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: '88%' }}
                        transition={{ duration: 1, delay: 0.5 }}
                        className="h-full bg-gradient-to-r from-emerald-500 to-indigo-500 rounded-full"
                      ></motion.div>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-xs font-medium text-slate-700 mb-2">Proof-of-Skill Cards</div>
                    {['React Development', 'Machine Learning', 'Data Structures'].map((skill, i) => (
                      <motion.div
                        key={skill}
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.7 + i * 0.1 }}
                        className="flex items-center gap-3 backdrop-blur-sm bg-white/40 rounded-xl p-3 border border-slate-200/30"
                      >
                        <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                        <span className="text-xs text-slate-700 flex-1">{skill}</span>
                        <span className="text-xs text-slate-500">Verified</span>
                      </motion.div>
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>

            <motion.div
              animate={{ rotate: [0, 5, 0] }}
              transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
              className="absolute -right-4 -bottom-4 w-24 h-24 bg-gradient-to-br from-emerald-400 to-indigo-500 rounded-2xl opacity-20 blur-xl"
            ></motion.div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
