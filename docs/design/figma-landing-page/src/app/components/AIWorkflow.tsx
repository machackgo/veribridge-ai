import { motion } from 'motion/react';
import { FileText, Github, BookOpen, Brain, Target, TrendingUp, CheckCircle2, ArrowRight } from 'lucide-react';

const workflowSteps = [
  { icon: FileText, label: 'Resume Upload', color: 'slate' },
  { icon: Github, label: 'GitHub Analysis', color: 'emerald' },
  { icon: BookOpen, label: 'Coursework Review', color: 'indigo' },
  { icon: Brain, label: 'AI Analysis', color: 'purple' },
  { icon: Target, label: 'Match Score', color: 'blue' },
  { icon: TrendingUp, label: 'Skill Gap Analysis', color: 'orange' },
  { icon: CheckCircle2, label: 'Interview Prep', color: 'green' },
];

export function AIWorkflow() {
  return (
    <section className="relative py-24 px-6 bg-white">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="text-center mb-16"
        >
          <h2 className="text-4xl md:text-5xl font-bold text-slate-900 mb-4">
            AI-powered career intelligence
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            Our AI analyzes your entire profile to match you with opportunities and identify growth areas
          </p>
        </motion.div>

        <div className="relative">
          <div className="hidden md:block absolute top-1/2 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-slate-200 to-transparent"></div>

          <div className="grid grid-cols-2 md:grid-cols-7 gap-6 md:gap-4 relative">
            {workflowSteps.map((step, index) => (
              <motion.div
                key={step.label}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1 }}
                className="flex flex-col items-center text-center"
              >
                <motion.div
                  whileHover={{ scale: 1.1, rotate: 5 }}
                  className="relative mb-4"
                >
                  <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-white to-slate-50 border border-slate-200 flex items-center justify-center shadow-xl shadow-slate-900/10 relative z-10">
                    <step.icon className="w-8 h-8 text-slate-700" />
                  </div>
                  <div className="absolute inset-0 bg-gradient-to-br from-emerald-400/20 to-indigo-400/20 rounded-2xl blur-xl"></div>
                </motion.div>

                <h4 className="font-medium text-slate-900 text-sm mb-1">{step.label}</h4>
                <div className="w-8 h-1 bg-gradient-to-r from-emerald-500 to-indigo-500 rounded-full"></div>

                {index < workflowSteps.length - 1 && (
                  <ArrowRight className="hidden md:block absolute top-10 -right-2 w-4 h-4 text-slate-300" />
                )}
              </motion.div>
            ))}
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 30 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="mt-16 backdrop-blur-xl bg-gradient-to-br from-emerald-500/5 to-indigo-500/5 border border-emerald-200/30 rounded-3xl p-8 md:p-12"
        >
          <div className="grid md:grid-cols-3 gap-8">
            <div className="text-center">
              <div className="text-4xl font-bold text-slate-900 mb-2">10K+</div>
              <div className="text-slate-600">Skills Analyzed</div>
            </div>
            <div className="text-center">
              <div className="text-4xl font-bold text-slate-900 mb-2">95%</div>
              <div className="text-slate-600">Match Accuracy</div>
            </div>
            <div className="text-center">
              <div className="text-4xl font-bold text-slate-900 mb-2">2.5x</div>
              <div className="text-slate-600">Faster Hiring</div>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
