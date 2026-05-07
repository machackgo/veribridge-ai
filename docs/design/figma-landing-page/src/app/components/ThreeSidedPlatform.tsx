import { motion } from 'motion/react';
import { GraduationCap, Briefcase, Building2, ArrowRight } from 'lucide-react';

const platforms = [
  {
    icon: GraduationCap,
    title: 'Students',
    description: 'Build verified career profiles backed by real projects, coursework, and skills. Stand out with proof-of-skill credentials.',
    features: ['Resume Analysis', 'Skill Verification', 'Job Matching', 'Interview Prep'],
    gradient: 'from-emerald-500 to-emerald-600',
    bgGradient: 'from-emerald-500/10 to-emerald-600/5',
  },
  {
    icon: Briefcase,
    title: 'Recruiters',
    description: 'Access verified student profiles with proof-backed skills. Reduce hiring risk and find the best-fit candidates faster.',
    features: ['Verified Candidates', 'Skill Matching', 'Talent Pipeline', 'Analytics Dashboard'],
    gradient: 'from-indigo-500 to-indigo-600',
    bgGradient: 'from-indigo-500/10 to-indigo-600/5',
  },
  {
    icon: Building2,
    title: 'Universities',
    description: 'Track student career readiness, improve placement rates, and provide data-driven career guidance at scale.',
    features: ['Student Analytics', 'Placement Tracking', 'Career Services', 'Employer Network'],
    gradient: 'from-purple-500 to-purple-600',
    bgGradient: 'from-purple-500/10 to-purple-600/5',
  },
];

export function ThreeSidedPlatform() {
  return (
    <section className="relative py-24 px-6 bg-white" id="platform">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold text-slate-900 mb-4">
            One platform, three perspectives
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            CareerProof AI connects students, recruiters, and universities through verified career data
          </p>
        </motion.div>

        <div className="grid md:grid-cols-3 gap-8">
          {platforms.map((platform, index) => (
            <motion.div
              key={platform.title}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.1 }}
              className="group"
            >
              <div className="h-full backdrop-blur-xl bg-white border border-slate-200/50 rounded-3xl p-8 shadow-xl shadow-slate-900/5 hover:shadow-2xl hover:shadow-slate-900/10 transition-all duration-300">
                <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${platform.gradient} flex items-center justify-center mb-6 shadow-lg shadow-${platform.gradient.split(' ')[1]}/30`}>
                  <platform.icon className="w-8 h-8 text-white" />
                </div>

                <h3 className="text-2xl font-bold text-slate-900 mb-3">{platform.title}</h3>
                <p className="text-slate-600 mb-6 leading-relaxed">{platform.description}</p>

                <div className="space-y-3 mb-6">
                  {platform.features.map((feature) => (
                    <div key={feature} className="flex items-center gap-2">
                      <div className={`w-1.5 h-1.5 rounded-full bg-gradient-to-r ${platform.gradient}`}></div>
                      <span className="text-sm text-slate-700">{feature}</span>
                    </div>
                  ))}
                </div>

                <button className="w-full py-3 rounded-xl bg-gradient-to-br from-slate-50 to-slate-100 border border-slate-200 text-slate-700 font-medium hover:from-slate-100 hover:to-slate-200 transition-all flex items-center justify-center gap-2 group-hover:border-slate-300">
                  Learn More
                  <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                </button>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
