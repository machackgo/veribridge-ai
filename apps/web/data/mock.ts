export const student = {
  name: "Maya Reyes",
  initials: "MR",
  email: "maya.reyes@wpi.edu",
  school: "WPI",
  major: "Computer Science",
  gradYear: "2026",
  score: 82,
  scoreDelta: "+14 in 30d",
  verifiedSkills: 24,
  publicProof: 18,
  topMatch: "Backend Engineer · Stripe",
};

export const jobs = [
  {
    company: "Stripe",
    role: "Backend Engineer Intern",
    location: "NYC",
    match: 94,
    visaFit: 92,
    matching: ["Docker", "TypeScript", "PostgreSQL"],
    missing: ["Kubernetes"],
    warning: "",
  },
  {
    company: "Linear",
    role: "Software Engineer Intern",
    location: "Remote",
    match: 91,
    visaFit: 89,
    matching: ["React", "TypeScript", "Node.js"],
    missing: ["GraphQL"],
    warning: "",
  },
  {
    company: "Anthropic",
    role: "SRE Intern",
    location: "San Francisco",
    match: 83,
    visaFit: 46,
    matching: ["Docker", "Python"],
    missing: ["Kubernetes", "Security clearance"],
    warning: "Low visa compatibility: sponsorship and clearance language detected.",
  },
  {
    company: "Federal Research Lab",
    role: "Platform Engineering Intern",
    location: "Boston",
    match: 72,
    visaFit: 18,
    matching: ["Linux", "Python"],
    missing: ["Security clearance"],
    warning: "Security clearance warning: likely U.S. citizens only.",
  },
];

export const applications = [
  ["Stripe", "Backend Engineer Intern", "Interview", "Resume v4", "Tailored", "Prep system design loop"],
  ["Linear", "Software Engineer Intern", "Applied", "Resume v3", "Sent", "Follow up Friday"],
  ["Vercel", "Full-stack Intern", "Prepared", "Resume v5", "Draft ready", "Needs project proof"],
  ["Figma", "Platform Intern", "Saved", "Not selected", "Not started", "Review visa wording"],
  ["Netflix", "Tools Intern", "Offer", "Resume v4", "Sent", "Outcome tracking pending"],
  ["Datadog", "Backend Intern", "Rejected", "Resume v2", "Sent", "Missing observability proof"],
];

export const skillGaps = [
  {
    skill: "Kubernetes",
    impact: 68,
    plan: "Build a small Kubernetes project this week",
    readiness: 42,
  },
  {
    skill: "System Design Interview",
    impact: 59,
    plan: "Complete 3 backend architecture mocks",
    readiness: 48,
  },
  {
    skill: "GraphQL",
    impact: 42,
    plan: "Add GraphQL endpoint to project-flux",
    readiness: 55,
  },
  {
    skill: "Observability",
    impact: 36,
    plan: "Instrument Docker app with metrics and logs",
    readiness: 51,
  },
];

export const evidence = [
  {
    skill: "Docker",
    status: "Verified",
    chain: ["Docker", "GitHub repo", "Deployed app", "CS 4515 project proof"],
    artifacts: [
      "veribridge-eval · Production Docker app · 4.2k LOC",
      "project-flux.app · Live deploy · 90-day uptime",
      "CS 4515 · Distributed Systems · A",
    ],
  },
  {
    skill: "React & TypeScript",
    status: "Verified",
    chain: ["React", "Component library", "Coursework", "Portfolio proof"],
    artifacts: [
      "flux-ui · Component library · TS strict",
      "Meta React Specialization · issued Nov 2024",
    ],
  },
  {
    skill: "PostgreSQL",
    status: "Pending",
    chain: ["SQL schema", "Migration notes", "Query tests"],
    artifacts: ["application-tracker schema · 18 queries reviewed"],
  },
];

export const visaSignals = [
  ["Current status", "F-1 student · CPT eligible Spring 2026"],
  ["OPT", "Post-completion OPT planned · June 2026"],
  ["STEM OPT", "Eligible major · 24-month extension likely"],
  ["H-1B", "Needs sponsor after OPT/STEM OPT period"],
];

export const candidates = [
  {
    name: "Maya Reyes",
    school: "WPI · CS '26",
    score: 94,
    proof: ["Docker", "React", "PostgreSQL"],
    optInVisa: true,
    visa: "F-1 OK",
  },
  {
    name: "Jordan Chen",
    school: "MIT · CS '26",
    score: 91,
    proof: ["Distributed Systems", "Go", "gRPC"],
    optInVisa: false,
    visa: "Student-controlled",
  },
  {
    name: "Amara Patel",
    school: "CMU · CS '26",
    score: 89,
    proof: ["Docker", "AWS", "Terraform"],
    optInVisa: true,
    visa: "F-1 OK",
  },
  {
    name: "Sara Okonkwo",
    school: "Brown · CS '26",
    score: 85,
    proof: ["Python", "PyTorch", "Docker"],
    optInVisa: false,
    visa: "Student-controlled",
  },
];

export const universityMetrics = [
  ["Cohort size", "1,284", "Class of 2026"],
  ["Avg. readiness", "73.4", "+6.2 vs 2025"],
  ["Verified profiles", "847", "66% adoption"],
  ["Placed by graduation", "71%", "+8 pts vs peer R1"],
];

export const departments = [
  ["Computer Science", "78%", "Cloud / Docker gap narrowing"],
  ["Data Science", "74%", "Distributed systems gap"],
  ["Robotics Engineering", "69%", "Security proof gap"],
  ["Electrical & Computer", "67%", "System design gap"],
  ["Bioinformatics", "61%", "Small cohort warnings active"],
];
