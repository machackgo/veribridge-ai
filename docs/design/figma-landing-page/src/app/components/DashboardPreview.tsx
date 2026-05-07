import { motion } from 'motion/react';
import { Upload, Target, TrendingDown, CheckSquare, Award } from 'lucide-react';

const dashboardCards = [
  {
    icon: Upload,
    title: 'Resume Upload',
    description: 'AI-powered resume analysis',
    stat: '98%',
    statLabel: 'Completeness',
    gradient: 'from-blue-500 to-blue-600',
  },
  {
    icon: Target,
    title: 'Job Match',
    description: 'Top opportunities for you',
    stat: '12',
    statLabel: 'Matches',
    gradient: 'from-emerald-500 to-emerald-600',
  },
  {
    icon: TrendingDown,
    title: 'Skill Gap',
    description: 'Areas to improve',
    stat: '3',
    statLabel: 'Skills',
    gradient: 'from-orange-500 to-orange-600',
  },
  {
    icon: CheckSquare,
    title: 'Application Tracker',
    description: 'Track your progress',
    stat: '8',
    statLabel: 'Active',
    gradient: 'from-indigo-500 to-indigo-600',
  },
  {
    icon: Award,
    title: 'CareerProof Score',
    description: 'Your career readiness',
    stat: '92',
    statLabel: 'Score',
    gradient: 'from-purple-500 to-purple-600',
  },
];

export function DashboardPreview() {
  return (
    <section className="relative py-24 px-6 bg-gradient-to-br from-slate-50 via-indigo-50/30 to-emerald-50/20">
      <div className="absolute inset-0 opacity-20">
        <div className="absolute top-1/3 left-1/3 w-96 h-96 bg-emerald-400/30 rounded-full blur-3xl"></div>
        <div className="absolute bottom-1/3 right-1/3 w-96 h-96 bg-indigo-400/30 rounded-full blur-3xl"></div>
      </div>

      <div className="max-w-7xl mx-auto relative">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold text-slate-900 mb-4">
            Your complete career command center
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Track every aspect of your career journey in one powerful dashboard
          </p>
        </motion.div>

        <div className="grid md:grid-cols-3 gap-6">
          {dashboardCards.map((card, index) => (
            <motion.div
              key={card.title}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.1 }}
              whileHover={{ y: -8 }}
              className={`backdrop-blur-xl bg-white/80 border border-slate-200/50 rounded-3xl p-6 shadow-xl shadow-slate-900/5 hover:shadow-2xl transition-all duration-300 ${
                index === 4 ? 'md:col-span-3' : ''
              }`}
            >
              <div className="flex items-start justify-between mb-4">
                <div className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${card.gradient} flex items-center justify-center shadow-lg`}>
                  <card.icon className="w-7 h-7 text-white" />
                </div>
                <div className="text-right">
                  <div className="text-3xl font-bold text-slate-900">{card.stat}</div>
                  <div className="text-xs text-slate-500">{card.statLabel}</div>
                </div>
              </div>

              <h3 className="font-semibold text-slate-900 mb-1">{card.title}</h3>
              <p className="text-sm text-slate-600">{card.description}</p>

              {index === 4 && (
                <div className="mt-6 grid grid-cols-2 md:grid-cols-5 gap-4">
                  {['Projects', 'Skills', 'Experience', 'Education', 'Certifications'].map((item) => (
                    <div key={item} className="text-center">
                      <div className="w-full h-2 bg-slate-200 rounded-full overflow-hidden mb-2">
                        <motion.div
                          initial={{ width: 0 }}
                          whileInView={{ width: `${Math.random() * 30 + 70}%` }}
                          viewport={{ once: true }}
                          transition={{ duration: 1, delay: 0.5 }}
                          className="h-full bg-gradient-to-r from-purple-500 to-indigo-500 rounded-full"
                        ></motion.div>
                      </div>
                      <span className="text-xs text-slate-600">{item}</span>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
