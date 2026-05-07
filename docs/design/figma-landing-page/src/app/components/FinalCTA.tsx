import { motion } from 'motion/react';
import { ArrowRight, Sparkles, Shield, Zap } from 'lucide-react';

export function FinalCTA() {
  return (
    <section className="relative py-24 px-6 bg-white overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-slate-900 via-indigo-900 to-emerald-900"></div>

      <div className="absolute inset-0 opacity-10">
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-emerald-400 rounded-full blur-3xl"></div>
        <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-indigo-400 rounded-full blur-3xl"></div>
      </div>

      <div className="max-w-4xl mx-auto relative">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center"
        >
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 mb-8">
            <Sparkles className="w-4 h-4 text-emerald-400" />
            <span className="text-sm text-white">Join thousands of verified students</span>
          </div>

          <h2 className="text-4xl md:text-5xl font-bold text-white mb-6">
            Build your verified career profile today
          </h2>

          <p className="text-xl text-slate-300 mb-12 max-w-2xl mx-auto">
            Turn your resume, projects, and skills into a proof-backed profile that recruiters and universities trust
          </p>

          <div className="flex flex-wrap gap-4 justify-center mb-16">
            <button className="px-10 py-5 rounded-xl bg-gradient-to-r from-emerald-500 to-emerald-600 text-white font-medium hover:from-emerald-600 hover:to-emerald-700 transition-all shadow-2xl shadow-emerald-500/40 flex items-center gap-3 group">
              Start Building Profile
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
            <button className="px-10 py-5 rounded-xl bg-white/10 backdrop-blur-sm border border-white/20 text-white font-medium hover:bg-white/20 transition-all flex items-center gap-3">
              Schedule Demo
            </button>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.1 }}
              className="backdrop-blur-sm bg-white/5 border border-white/10 rounded-2xl p-6"
            >
              <Shield className="w-8 h-8 text-emerald-400 mb-3 mx-auto" />
              <h3 className="font-semibold text-white mb-2">Verified .edu Only</h3>
              <p className="text-sm text-slate-300">Exclusive access for verified students</p>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.2 }}
              className="backdrop-blur-sm bg-white/5 border border-white/10 rounded-2xl p-6"
            >
              <Zap className="w-8 h-8 text-indigo-400 mb-3 mx-auto" />
              <h3 className="font-semibold text-white mb-2">AI-Powered</h3>
              <p className="text-sm text-slate-300">Smart matching and analysis</p>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.3 }}
              className="backdrop-blur-sm bg-white/5 border border-white/10 rounded-2xl p-6"
            >
              <Sparkles className="w-8 h-8 text-purple-400 mb-3 mx-auto" />
              <h3 className="font-semibold text-white mb-2">Proof-Backed</h3>
              <p className="text-sm text-slate-300">Every skill verified by evidence</p>
            </motion.div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
