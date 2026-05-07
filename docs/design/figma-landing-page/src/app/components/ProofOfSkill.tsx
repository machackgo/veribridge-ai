import { motion } from 'motion/react';
import { Github, FileText, Award, BookOpen, CheckCircle2, Link as LinkIcon } from 'lucide-react';

const proofSources = [
  { icon: Github, label: 'GitHub Projects', color: 'emerald' },
  { icon: FileText, label: 'Coursework', color: 'indigo' },
  { icon: Award, label: 'Certifications', color: 'purple' },
  { icon: BookOpen, label: 'Portfolio', color: 'blue' },
];

const skillCards = [
  { skill: 'Full-Stack Development', sources: ['GitHub', 'Projects'], verified: true },
  { skill: 'Machine Learning', sources: ['Coursework', 'Certifications'], verified: true },
  { skill: 'Cloud Architecture', sources: ['Portfolio', 'GitHub'], verified: true },
];

export function ProofOfSkill() {
  return (
    <section className="relative py-24 px-6 bg-gradient-to-br from-slate-50 via-white to-slate-50">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold text-slate-900 mb-4">
            Skills backed by proof, not just claims
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Every skill is connected to verified evidence from your projects, coursework, and achievements
          </p>
        </motion.div>

        <div className="grid md:grid-cols-2 gap-12 items-center">
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="space-y-6"
          >
            {skillCards.map((card, index) => (
              <motion.div
                key={card.skill}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1 }}
                className="backdrop-blur-xl bg-white/80 border border-slate-200/50 rounded-2xl p-6 shadow-xl shadow-slate-900/5 hover:shadow-2xl hover:border-emerald-200/50 transition-all duration-300 group"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="font-semibold text-slate-900">{card.skill}</h3>
                      {card.verified && (
                        <div className="flex items-center gap-1 px-2 py-1 rounded-full bg-emerald-500/10 border border-emerald-200/50">
                          <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                          <span className="text-xs text-emerald-700">Verified</span>
                        </div>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {card.sources.map((source) => (
                        <span key={source} className="text-xs text-slate-600 px-3 py-1 rounded-full bg-slate-100 border border-slate-200">
                          {source}
                        </span>
                      ))}
                    </div>
                  </div>
                  <LinkIcon className="w-5 h-5 text-slate-400 group-hover:text-emerald-500 transition-colors" />
                </div>

                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: '100%' }}
                    viewport={{ once: true }}
                    transition={{ duration: 1, delay: index * 0.1 + 0.3 }}
                    className="h-full bg-gradient-to-r from-emerald-500 to-indigo-500 rounded-full"
                  ></motion.div>
                </div>
              </motion.div>
            ))}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, x: 30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="relative"
          >
            <div className="relative">
              <div className="grid grid-cols-2 gap-4">
                {proofSources.map((source, index) => (
                  <motion.div
                    key={source.label}
                    initial={{ opacity: 0, scale: 0.9 }}
                    whileInView={{ opacity: 1, scale: 1 }}
                    viewport={{ once: true }}
                    transition={{ delay: index * 0.1 }}
                    whileHover={{ scale: 1.05 }}
                    className={`backdrop-blur-xl bg-gradient-to-br from-${source.color}-500/10 to-${source.color}-600/5 border border-${source.color}-200/50 rounded-2xl p-6 shadow-lg hover:shadow-xl transition-all duration-300`}
                  >
                    <div className={`w-12 h-12 rounded-xl bg-gradient-to-br from-${source.color}-500 to-${source.color}-600 flex items-center justify-center mb-4 shadow-lg`}>
                      <source.icon className="w-6 h-6 text-white" />
                    </div>
                    <h4 className="font-semibold text-slate-900 text-sm">{source.label}</h4>
                  </motion.div>
                ))}
              </div>

              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-32 h-32 pointer-events-none">
                <svg className="w-full h-full" viewBox="0 0 100 100">
                  {[0, 1, 2, 3].map((i) => (
                    <motion.line
                      key={i}
                      x1="50"
                      y1="50"
                      x2={50 + 40 * Math.cos((i * Math.PI) / 2)}
                      y2={50 + 40 * Math.sin((i * Math.PI) / 2)}
                      stroke="url(#gradient)"
                      strokeWidth="2"
                      strokeDasharray="4 4"
                      initial={{ pathLength: 0, opacity: 0 }}
                      whileInView={{ pathLength: 1, opacity: 0.3 }}
                      viewport={{ once: true }}
                      transition={{ duration: 1, delay: i * 0.1 }}
                    />
                  ))}
                  <defs>
                    <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#10b981" />
                      <stop offset="100%" stopColor="#6366f1" />
                    </linearGradient>
                  </defs>
                </svg>
              </div>

              <motion.div
                animate={{ scale: [1, 1.1, 1] }}
                transition={{ duration: 3, repeat: Infinity }}
                className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-16 bg-gradient-to-br from-emerald-400 to-indigo-500 rounded-full opacity-20 blur-2xl"
              ></motion.div>
            </div>
          </motion.div>
        </div>
      </div>
    </section>
  );
}
