"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  CLOUD_PROVIDER_OPTIONS,
  ALL_ROLE_OPTIONS,
  ALL_SKILL_OPTIONS,
  PROOF_EVIDENCE_ACCESS_METHODS,
  PROOF_EVIDENCE_SOURCE_TYPES,
  INDUSTRY_OPTIONS,
  UPLOAD_EVIDENCE_FILE_ACCEPT,
  detectSkillCategory,
  getSkillProofHint,
  getSuggestedIndustriesForMajor,
  getSuggestedRolesForMajor,
  getSuggestedSkillsForContext,
  isCodeLikeFilePath,
  getProofVisibilityLabel,
} from "./taxonomy";

type Mode = "signup" | "edit";
type FormState = {
  universityCountry: string;
  degreeLevel: string;
  major: string;
  customMajor: string;
  graduationYear: string;
  targetRoles: string[];
  customRole: string;
  targetIndustries: string[];
  skills: string[];
  selectedSkills: string[];
  customSkill: string;
  targetLocations: string[];
  customLocation: string;
  workModes: string[];
  globalSearch: boolean;
  relocate: boolean;
  authorizationType: string;
  authorizationCountries: string[];
  sponsorshipNeeded: string;
  authNotes: string;
  salaryMin: string;
  salaryMax: string;
  minimumSalary: string;
  currency: string;
  customCurrency: string;
  salaryPeriod: string;
  negotiable: string;
  proofSkill: string;
  proofEvidenceType: string;
  proofEvidenceAccessMethod: string;
  proofRepositoryUrl: string;
  proofEvidenceUrl: string;
  proofLinkedInPostUrl: string;
  proofRelatedProjectUrl: string;
  proofKeyFiles: string;
  proofEvidenceTitle: string;
  proofVisibilityNote: string;
  proofIsRecruiterVisible: boolean;
  proofRequiresApproval: boolean;
  proofCloudProvider: string;
  proofConfigFile: string;
  proofDiagramUrl: string;
  proofCertificateIssuer: string;
  proofCompletionDate: string;
  proofRoleTitle: string;
  proofToolUsed: string;
  proofDataset: string;
  proofMetrics: string;
  proofFilePath: string;
  proofLineStart: string;
  proofLineEnd: string;
  proofExactCodeLocation: boolean;
  proofEvidenceDescription: string;
  proofUploadedFileName: string;
  proofUploadedFileType: string;
  proofUploadedFileSize: string;
  proofUploadedFileUrl: string;
  proofUploadedFileId: string;
  proofEvidence: ProofEvidenceEntry[];
};

const steps = [
  "Academic Profile",
  "Target Roles & Industries",
  "Skills & Proof Evidence",
  "Global Locations & Work Mode",
  "Work Authorization",
  "Compensation Preferences",
  "Opportunity & Salary Heatmap Review",
];

type ProofVerificationStatus =
  | "Pending verification"
  | "Verified"
  | "Skill usage not found"
  | "Needs review";

type ProofEvidenceEntry = {
  skill: string;
  sourceType: string;
  evidenceAccessMethod: "public_link" | "upload_file";
  evidenceUrl: string;
  repositoryUrl: string;
  linkedInPostUrl: string;
  relatedProjectUrl: string;
  keyFiles: string;
  evidenceTitle: string;
  visibilityNote: string;
  isRecruiterVisible: boolean;
  requiresApproval: boolean;
  uploadedFileName: string;
  uploadedFileType: string;
  uploadedFileSize: string;
  uploadedFileUrl: string;
  uploadedFileId: string;
  filePath: string;
  startLine: string;
  endLine: string;
  description: string;
  cloudProvider: string;
  configFile: string;
  diagramUrl: string;
  certificateIssuer: string;
  completionDate: string;
  roleTitle: string;
  toolUsed: string;
  dataset: string;
  metrics: string;
  exactCodeLocation: boolean;
  verificationStatus: ProofVerificationStatus;
  verificationSummary: string;
  // legacy aliases for older reads/tests during transition
  skill_name?: string;
  evidence_type?: string;
  evidence_access_method?: "public_link" | "upload_file";
  evidence_url?: string;
  linked_in_post_url?: string;
  related_project_url?: string;
  evidence_title?: string;
  visibility_note?: string;
  is_recruiter_visible?: boolean;
  requires_approval?: boolean;
  uploaded_file_name?: string;
  uploaded_file_type?: string;
  uploaded_file_size?: string;
  uploaded_file_url?: string;
  uploaded_file_id?: string;
  file_path?: string;
  line_start?: string;
  line_end?: string;
  evidence_description?: string;
  verification_status?: ProofVerificationStatus;
  verification_summary?: string;
};

const countryOptions = [
  "Afghanistan",
  "Albania",
  "Algeria",
  "Andorra",
  "Angola",
  "Antigua and Barbuda",
  "Argentina",
  "Armenia",
  "Australia",
  "Austria",
  "Azerbaijan",
  "Bahamas",
  "Bahrain",
  "Bangladesh",
  "Barbados",
  "Belarus",
  "Belgium",
  "Belize",
  "Benin",
  "Bhutan",
  "Bolivia",
  "Bosnia and Herzegovina",
  "Botswana",
  "Brazil",
  "Brunei",
  "Bulgaria",
  "Burkina Faso",
  "Burundi",
  "Cabo Verde",
  "Cambodia",
  "Cameroon",
  "Canada",
  "Central African Republic",
  "Chad",
  "Chile",
  "China",
  "Colombia",
  "Comoros",
  "Congo",
  "Costa Rica",
  "Cote d'Ivoire",
  "Croatia",
  "Cuba",
  "Cyprus",
  "Czech Republic",
  "Democratic Republic of the Congo",
  "Denmark",
  "Djibouti",
  "Dominica",
  "Dominican Republic",
  "Ecuador",
  "Egypt",
  "El Salvador",
  "Equatorial Guinea",
  "Eritrea",
  "Estonia",
  "Eswatini",
  "Ethiopia",
  "Fiji",
  "Finland",
  "France",
  "Gabon",
  "Gambia",
  "Georgia",
  "Germany",
  "Ghana",
  "Greece",
  "Grenada",
  "Guatemala",
  "Guinea",
  "Guinea-Bissau",
  "Guyana",
  "Haiti",
  "Honduras",
  "Hungary",
  "Iceland",
  "India",
  "Indonesia",
  "Iran",
  "Iraq",
  "Ireland",
  "Israel",
  "Italy",
  "Jamaica",
  "Japan",
  "Jordan",
  "Kazakhstan",
  "Kenya",
  "Kiribati",
  "Kuwait",
  "Kyrgyzstan",
  "Laos",
  "Latvia",
  "Lebanon",
  "Lesotho",
  "Liberia",
  "Libya",
  "Liechtenstein",
  "Lithuania",
  "Luxembourg",
  "Madagascar",
  "Malawi",
  "Malaysia",
  "Maldives",
  "Mali",
  "Malta",
  "Marshall Islands",
  "Mauritania",
  "Mauritius",
  "Mexico",
  "Micronesia",
  "Moldova",
  "Monaco",
  "Mongolia",
  "Montenegro",
  "Morocco",
  "Mozambique",
  "Myanmar",
  "Namibia",
  "Nauru",
  "Nepal",
  "Netherlands",
  "New Zealand",
  "Nicaragua",
  "Niger",
  "Nigeria",
  "North Korea",
  "North Macedonia",
  "Norway",
  "Oman",
  "Pakistan",
  "Palau",
  "Palestine",
  "Panama",
  "Papua New Guinea",
  "Paraguay",
  "Peru",
  "Philippines",
  "Poland",
  "Portugal",
  "Qatar",
  "Romania",
  "Russia",
  "Rwanda",
  "Saint Kitts and Nevis",
  "Saint Lucia",
  "Saint Vincent and the Grenadines",
  "Samoa",
  "San Marino",
  "Sao Tome and Principe",
  "Saudi Arabia",
  "Senegal",
  "Serbia",
  "Seychelles",
  "Sierra Leone",
  "Singapore",
  "Slovakia",
  "Slovenia",
  "Solomon Islands",
  "Somalia",
  "South Africa",
  "South Korea",
  "South Sudan",
  "Spain",
  "Sri Lanka",
  "Sudan",
  "Suriname",
  "Sweden",
  "Switzerland",
  "Syria",
  "Taiwan",
  "Tajikistan",
  "Tanzania",
  "Thailand",
  "Timor-Leste",
  "Togo",
  "Tonga",
  "Trinidad and Tobago",
  "Tunisia",
  "Turkey",
  "Turkmenistan",
  "Tuvalu",
  "Uganda",
  "Ukraine",
  "United Arab Emirates",
  "United Kingdom",
  "United States",
  "Uruguay",
  "Uzbekistan",
  "Vanuatu",
  "Vatican City",
  "Venezuela",
  "Vietnam",
  "Yemen",
  "Zambia",
  "Zimbabwe",
  "Other",
];

const degreeOptions = [
  "Associate",
  "Bachelor's",
  "Master's",
  "MBA",
  "PhD",
  "Diploma",
  "Certificate",
  "Other",
];

const majorOptions = [
  "Computer Science",
  "Artificial Intelligence",
  "Data Science",
  "Mechanical Engineering",
  "Electrical Engineering",
  "Civil Engineering",
  "Robotics",
  "Business Administration",
  "Finance",
  "Accounting",
  "Marketing",
  "Healthcare",
  "Biology",
  "Psychology",
  "Architecture",
  "Design",
  "Education",
  "Law/Policy",
  "Environmental Science",
  "Supply Chain",
  "Media/Journalism",
  "Other",
];

const careerFields = [
  "Technology & Software",
  "AI & Data",
  "Business & Management",
  "Finance & Accounting",
  "Healthcare & Life Sciences",
  "Mechanical/Electrical/Civil Engineering",
  "Robotics & Manufacturing",
  "Design & Architecture",
  "Marketing & Communications",
  "Education",
  "Law & Policy",
  "Psychology & Social Sciences",
  "Research / Academia",
  "Entrepreneurship",
  "Environmental Science",
  "Supply Chain & Operations",
  "Media / Journalism",
  "Other",
];

const rolesByField: Record<string, string[]> = {
  "Technology & Software": ["Software Engineer", "Product Manager", "QA Analyst", "Solutions Engineer"],
  "AI & Data": ["Data Analyst", "Machine Learning Engineer", "Data Scientist", "Analytics Consultant"],
  "Business & Management": ["Business Analyst", "Operations Associate", "Management Consultant", "Project Coordinator"],
  "Finance & Accounting": ["Financial Analyst", "Audit Associate", "Investment Analyst", "Accounting Associate"],
  "Healthcare & Life Sciences": ["Clinical Research Coordinator", "Healthcare Analyst", "Lab Technician", "Biotech Associate"],
  "Mechanical/Electrical/Civil Engineering": ["Mechanical Engineer", "Electrical Engineer", "Civil Engineer", "Field Engineer"],
  "Robotics & Manufacturing": ["Robotics Engineer", "Manufacturing Engineer", "Process Engineer", "Automation Technician"],
  "Design & Architecture": ["UX Designer", "Architectural Designer", "Product Designer", "Design Researcher"],
  "Marketing & Communications": ["Marketing Associate", "Communications Specialist", "Content Strategist", "Brand Analyst"],
  Education: ["Teacher", "Instructional Designer", "Student Success Coordinator", "Education Program Associate"],
  "Law & Policy": ["Policy Analyst", "Legal Assistant", "Compliance Analyst", "Public Affairs Associate"],
  "Psychology & Social Sciences": ["Research Assistant", "Behavioral Health Assistant", "Program Coordinator", "Survey Analyst"],
  "Research / Academia": ["Research Assistant", "Lab Manager", "Graduate Researcher", "Academic Program Assistant"],
  Entrepreneurship: ["Founder Associate", "Venture Analyst", "Growth Associate", "Startup Operator"],
  "Environmental Science": ["Environmental Analyst", "Sustainability Associate", "Field Researcher", "Climate Analyst"],
  "Supply Chain & Operations": ["Supply Chain Analyst", "Logistics Coordinator", "Procurement Analyst", "Operations Analyst"],
  "Media / Journalism": ["Reporter", "Editorial Assistant", "Producer", "Social Media Analyst"],
  Other: ["Intern", "Associate", "Coordinator", "Analyst"],
};

const rolesByMajor: Record<string, string[]> = {
  "Computer Science": [
    "Software Engineer",
    "Backend Engineer",
    "Frontend Engineer",
    "Full-stack Engineer",
    "Data Engineer",
    "Cloud Engineer",
    "DevOps Engineer",
    "Cybersecurity Analyst",
    "QA Engineer",
    "Product Manager",
    "Technical Program Manager",
  ],
  "Artificial Intelligence": [
    "AI Engineer",
    "Machine Learning Engineer",
    "Data Scientist",
    "Data Analyst",
    "MLOps Engineer",
    "NLP Engineer",
    "Computer Vision Engineer",
    "Research Assistant",
    "Analytics Engineer",
  ],
  "Data Science": [
    "AI Engineer",
    "Machine Learning Engineer",
    "Data Scientist",
    "Data Analyst",
    "MLOps Engineer",
    "NLP Engineer",
    "Computer Vision Engineer",
    "Research Assistant",
    "Analytics Engineer",
  ],
  "Mechanical Engineering": [
    "Mechanical Engineer",
    "Manufacturing Engineer",
    "Product Design Engineer",
    "CAD Engineer",
    "Quality Engineer",
    "Process Engineer",
    "Robotics Engineer",
    "Maintenance Engineer",
  ],
  "Electrical Engineering": [
    "Electrical Engineer",
    "Embedded Systems Engineer",
    "Controls Engineer",
    "Hardware Engineer",
    "Power Systems Engineer",
    "Electronics Engineer",
    "Test Engineer",
  ],
  "Civil Engineering": [
    "Civil Engineer",
    "Structural Engineer",
    "Construction Project Engineer",
    "Transportation Engineer",
    "Environmental Engineer",
    "Site Engineer",
  ],
  "Business Administration": [
    "Business Analyst",
    "Operations Analyst",
    "Product Manager",
    "Consultant",
    "Strategy Analyst",
    "Project Coordinator",
    "Sales Development Representative",
  ],
  Finance: [
    "Financial Analyst",
    "Investment Analyst",
    "Risk Analyst",
    "Corporate Finance Analyst",
    "Accounting Associate",
    "Audit Associate",
    "Credit Analyst",
  ],
  Accounting: [
    "Financial Analyst",
    "Investment Analyst",
    "Risk Analyst",
    "Corporate Finance Analyst",
    "Accounting Associate",
    "Audit Associate",
    "Credit Analyst",
  ],
  Healthcare: [
    "Clinical Research Assistant",
    "Lab Technician",
    "Research Assistant",
    "Public Health Analyst",
    "Healthcare Analyst",
    "Medical Assistant",
    "Regulatory Affairs Associate",
  ],
  Biology: [
    "Clinical Research Assistant",
    "Lab Technician",
    "Research Assistant",
    "Public Health Analyst",
    "Healthcare Analyst",
    "Medical Assistant",
    "Regulatory Affairs Associate",
  ],
  Psychology: [
    "Research Assistant",
    "Behavioral Health Technician",
    "HR Associate",
    "UX Research Assistant",
    "Case Manager",
    "Program Coordinator",
  ],
  Architecture: [
    "Architecture Intern",
    "Junior Architect",
    "Interior Designer",
    "UX Designer",
    "Graphic Designer",
    "Product Designer",
    "Design Researcher",
  ],
  Design: [
    "Architecture Intern",
    "Junior Architect",
    "Interior Designer",
    "UX Designer",
    "Graphic Designer",
    "Product Designer",
    "Design Researcher",
  ],
  Marketing: [
    "Marketing Associate",
    "Digital Marketing Specialist",
    "Content Strategist",
    "Social Media Coordinator",
    "Brand Associate",
    "Market Research Analyst",
  ],
  Education: [
    "Teaching Assistant",
    "Curriculum Developer",
    "Education Coordinator",
    "Instructional Designer",
    "Academic Advisor",
  ],
  "Law/Policy": [
    "Policy Analyst",
    "Legal Assistant",
    "Compliance Analyst",
    "Government Affairs Intern",
    "Research Assistant",
  ],
  "Supply Chain": [
    "Supply Chain Analyst",
    "Logistics Coordinator",
    "Procurement Analyst",
    "Operations Analyst",
    "Inventory Analyst",
  ],
  "Media/Journalism": [
    "Journalist",
    "Content Writer",
    "Video Producer",
    "Media Coordinator",
    "Communications Associate",
  ],
};

const defaultRoleSuggestions = [
  "Business Analyst",
  "Project Coordinator",
  "Research Assistant",
  "Operations Analyst",
  "Associate Consultant",
  "Program Coordinator",
];

const careerFieldsByMajor: Record<string, string[]> = {
  "Computer Science": ["Technology & Software", "AI & Data"],
  "Artificial Intelligence": ["Technology & Software", "AI & Data"],
  "Data Science": ["Technology & Software", "AI & Data"],
  Finance: ["Finance & Accounting", "Business & Management"],
  Accounting: ["Finance & Accounting", "Business & Management"],
  "Mechanical Engineering": ["Mechanical/Electrical/Civil Engineering", "Robotics & Manufacturing"],
  "Electrical Engineering": ["Mechanical/Electrical/Civil Engineering", "Robotics & Manufacturing"],
  "Civil Engineering": ["Mechanical/Electrical/Civil Engineering"],
  Healthcare: ["Healthcare & Life Sciences", "Research / Academia"],
  Biology: ["Healthcare & Life Sciences", "Research / Academia"],
  Design: ["Design & Architecture"],
  Architecture: ["Design & Architecture"],
  Marketing: ["Marketing & Communications"],
  Education: ["Education"],
  "Law/Policy": ["Law & Policy"],
  Psychology: ["Psychology & Social Sciences"],
  "Environmental Science": ["Environmental Science"],
  "Supply Chain": ["Supply Chain & Operations"],
  "Media/Journalism": ["Media / Journalism"],
};

const evidenceOptions = [
  "GitHub repository",
  "GitHub file",
  "Deployed app",
  "Portfolio link",
  "Coursework project",
  "Lab report",
  "Design portfolio",
  "Figma file",
  "CAD file",
  "Financial model",
  "Research paper",
  "Presentation deck",
  "Certificate",
  "Internship letter",
  "Demo video",
  "LinkedIn post",
  "Case competition",
  "Capstone project",
  "Other",
];

const locationOptions = [
  "Boston, Massachusetts",
  "New York",
  "California",
  "Toronto",
  "London",
  "Dubai",
  "Hyderabad",
  "Bengaluru",
  "Sydney",
  "Singapore",
  "Remote Worldwide",
  "Remote US",
  "Remote Canada",
  "Remote Europe",
  "Other",
];

const locationGroups = [
  {
    country: "United States",
    searchPlaceholder: "Search for other regions in United States",
    locations: [
      ["Remote in USA", "Remote friendly"],
      ["New York City", "Finance, media, startup density"],
      ["San Francisco Bay Area", "High opportunity · high competition"],
      ["Los Angeles", "Media, aerospace, design"],
      ["Boston", "AI/biotech hub"],
      ["Seattle", "Cloud and enterprise tech"],
      ["Chicago", "Business, finance, logistics"],
      ["Austin", "Tech growth · strong salary"],
      ["Raleigh", "Research triangle · lower cost"],
      ["Washington DC", "Policy, security, government"],
    ],
  },
  {
    country: "Canada",
    searchPlaceholder: "Search for other regions in Canada",
    locations: [
      ["Remote in Canada", "Remote friendly"],
      ["Toronto", "Finance, tech, healthcare"],
      ["Vancouver", "Tech, design, media"],
      ["Montreal", "AI, games, research"],
      ["Ottawa", "Government and tech"],
      ["Calgary", "Energy and operations"],
    ],
  },
  {
    country: "United Kingdom",
    searchPlaceholder: "Search for other regions in United Kingdom",
    locations: [
      ["Remote in UK", "Remote friendly"],
      ["London", "Finance, AI, consulting"],
      ["Manchester", "Digital and media growth"],
      ["Birmingham", "Business and manufacturing"],
      ["Edinburgh", "Finance and research"],
      ["Cambridge", "Research and biotech"],
    ],
  },
  {
    country: "India",
    searchPlaceholder: "Search for other regions in India",
    locations: [
      ["Remote in India", "Remote friendly"],
      ["Bengaluru", "High tech volume"],
      ["Hyderabad", "High tech volume · lower cost of living"],
      ["Mumbai", "Finance and media hub"],
      ["Delhi NCR", "Policy, business, startups"],
      ["Chennai", "Manufacturing and technology"],
      ["Pune", "Automotive and software"],
    ],
  },
  {
    country: "Australia",
    searchPlaceholder: "Search for other regions in Australia",
    locations: [
      ["Remote in Australia", "Remote friendly"],
      ["Sydney", "Finance and tech"],
      ["Melbourne", "Healthcare, design, education"],
      ["Brisbane", "Energy and operations"],
      ["Perth", "Mining, energy, engineering"],
    ],
  },
  {
    country: "Germany",
    searchPlaceholder: "Search for other regions in Germany",
    locations: [
      ["Remote in Germany", "Remote friendly"],
      ["Berlin", "Startups and AI"],
      ["Munich", "Automotive and engineering"],
      ["Frankfurt", "Finance and consulting"],
      ["Hamburg", "Logistics and media"],
    ],
  },
  {
    country: "France",
    searchPlaceholder: "Search for other regions in France",
    locations: [
      ["Remote in France", "Remote friendly"],
      ["Paris", "AI, finance, luxury, policy"],
      ["Lyon", "Healthcare and manufacturing"],
      ["Toulouse", "Aerospace and engineering"],
    ],
  },
  {
    country: "United Arab Emirates",
    searchPlaceholder: "Search for other regions in United Arab Emirates",
    locations: [
      ["Remote in UAE", "Remote friendly"],
      ["Dubai", "Business/finance hub"],
      ["Abu Dhabi", "Energy, government, AI"],
      ["Sharjah", "Education and culture"],
    ],
  },
  {
    country: "Singapore",
    searchPlaceholder: "Search for other regions in Singapore",
    locations: [
      ["Singapore", "Finance, logistics, APAC HQs"],
      ["Remote in Singapore", "Remote friendly"],
    ],
  },
  {
    country: "Remote Worldwide",
    searchPlaceholder: "Search remote regions",
    locations: [
      ["Remote Worldwide", "Flexible · authorization varies"],
      ["Remote US Time Zones", "US collaboration hours"],
      ["Remote Europe Time Zones", "Europe collaboration hours"],
      ["Remote Asia-Pacific Time Zones", "APAC collaboration hours"],
    ],
  },
  {
    country: "Other regions",
    searchPlaceholder: "Search or add any city, country, or region",
    locations: [
      ["Tokyo", "Enterprise and robotics"],
      ["Lagos", "Fintech and growth markets"],
      ["Riyadh", "Business transformation"],
      ["Paris", "AI, finance, design"],
    ],
  },
] as const;

const industryOptions = [
  "Technology",
  "Artificial Intelligence",
  "Finance",
  "Banking",
  "Consulting",
  "Healthcare",
  "Biotechnology",
  "Pharmaceuticals",
  "Manufacturing",
  "Automotive",
  "Aerospace",
  "Robotics",
  "Construction",
  "Architecture",
  "Education",
  "Government",
  "Public Policy",
  "Nonprofit",
  "Climate / Sustainability",
  "Energy",
  "Retail",
  "E-commerce",
  "Media",
  "Entertainment",
  "Telecommunications",
  "Supply Chain / Logistics",
  "Real Estate",
  "Hospitality",
  "Other",
];

const authorizationTypes = [
  "Citizen/Permanent Resident",
  "Student Visa",
  "F-1",
  "CPT",
  "OPT",
  "STEM OPT",
  "H-1B sponsorship needed",
  "Graduate Visa",
  "Work Permit",
  "Employer Sponsorship Needed",
  "No Sponsorship Needed",
  "Other",
];

const currencyOptions = ["USD", "CAD", "GBP", "EUR", "INR", "AUD", "AED", "SGD", "Other"];
const salaryPeriods = ["Hourly", "Monthly", "Yearly"];
const sponsorshipOptions = ["Yes", "No", "Later", "Not sure"];
const negotiationOptions = ["Yes", "No", "Depends on role/location"];

const recommendations = [
  ["California, USA", "18,400", "$95k-$154k", "High", "High", "Medium", "Strong", 91],
  ["Remote worldwide", "15,200", "$65k-$132k", "Medium", "High", "High", "Aligned", 88],
  ["Toronto, Canada", "7,600", "CAD 72k-118k", "Medium", "High", "High", "Aligned", 84],
  ["Massachusetts, USA", "8,300", "$78k-$128k", "Medium", "Medium", "High", "Aligned", 81],
] as const;

const inputStyle = {
  border: "1px solid var(--line)",
  borderRadius: 12,
  boxSizing: "border-box",
  minHeight: 46,
  padding: "12px 13px",
  fontSize: 14,
  color: "var(--ink)",
  background: "#fff",
  outline: "none",
} as const;

function TextField({
  label,
  name,
  placeholder,
  value,
  onChange,
  type = "text",
  helper,
}: {
  label: string;
  name: keyof FormState;
  placeholder: string;
  value: string;
  onChange: (name: keyof FormState, value: string) => void;
  type?: string;
  helper?: string;
}) {
  return (
    <label style={{ display: "grid", gap: 6, fontSize: 12, fontWeight: 650, color: "var(--ink)" }}>
      {label}
      <input
        aria-label={label}
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(name, event.target.value)}
        style={inputStyle}
      />
      {helper && <span style={{ color: "var(--muted)", fontSize: 11, lineHeight: 1.4 }}>{helper}</span>}
    </label>
  );
}

function TextAreaField({
  label,
  name,
  placeholder,
  value,
  onChange,
  rows = 3,
  helper,
}: {
  label: string;
  name: keyof FormState;
  placeholder: string;
  value: string;
  onChange: (name: keyof FormState, value: string) => void;
  rows?: number;
  helper?: string;
}) {
  return (
    <label style={{ display: "grid", gap: 6, fontSize: 12, fontWeight: 650, color: "var(--ink)" }}>
      {label}
      <textarea
        aria-label={label}
        rows={rows}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(name, event.target.value)}
        style={{
          ...inputStyle,
          minHeight: rows * 26 + 18,
          resize: "vertical",
          width: "100%",
        }}
      />
      {helper && <span style={{ color: "var(--muted)", fontSize: 11, lineHeight: 1.4 }}>{helper}</span>}
    </label>
  );
}

function matchesOption(option: string, searchTerm: string) {
  const normalized = option.toLowerCase();
  return (
    normalized.includes(searchTerm) ||
    (searchTerm.length > 1 && searchTerm.length <= 2 && normalized.startsWith(searchTerm[0]))
  );
}

function formatFileSize(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function inferUploadedFileLabel(fileName: string, mimeType: string) {
  const normalized = `${fileName} ${mimeType}`.toLowerCase();
  if (/(mp4|mov|webm|video)/.test(normalized)) return "Recorded demo / presentation video";
  if (/(png|jpg|jpeg|webp|gif|image)/.test(normalized)) return "Uploaded image evidence";
  if (/(pdf|doc|docx|txt|md|ppt|pptx|csv|xlsx|ipynb)/.test(normalized)) return "Uploaded document evidence";
  return "Uploaded evidence file";
}

function isPreviewableImage(fileName: string, mimeType: string) {
  return /\.(png|jpg|jpeg|webp|gif)$/i.test(fileName) || mimeType.startsWith("image/");
}

function isPreviewableVideo(fileName: string, mimeType: string) {
  return /\.(mp4|mov|webm)$/i.test(fileName) || mimeType.startsWith("video/");
}

function isPreviewablePdf(fileName: string, mimeType: string) {
  return /\.pdf$/i.test(fileName) || mimeType === "application/pdf";
}

function SelectDropdown({
  label,
  name,
  value,
  options,
  onChange,
}: {
  label: string;
  name: keyof FormState;
  value: string;
  options: string[];
  onChange: (name: keyof FormState, value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function close(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div ref={ref} style={{ display: "grid", gap: 6, fontSize: 12, fontWeight: 650, color: "var(--ink)" }}>
      <div style={{ position: "relative", display: "grid", gap: 6 }}>
        <label htmlFor={`${String(name)}-dropdown`}>{label}</label>
        <button
          id={`${String(name)}-dropdown`}
          type="button"
          aria-label={label}
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
            if (event.key === "Enter" || event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
            }
          }}
          style={{
            ...inputStyle,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            textAlign: "left",
            width: "100%",
          }}
        >
          <span style={{ color: value ? "var(--ink)" : "var(--muted)" }}>{value || "Select an option"}</span>
          <span aria-hidden="true" style={{ color: "var(--muted)" }}>⌄</span>
        </button>
        {open && (
          <DropdownPanel>
            {options.map((option, index) => (
              <DropdownOption
                key={`${option}-${index}`}
                selected={option === value}
                onSelect={() => {
                  onChange(name, option);
                  setOpen(false);
                }}
              >
                {option}
              </DropdownOption>
            ))}
          </DropdownPanel>
        )}
      </div>
    </div>
  );
}

function SearchableDropdown({
  label,
  name,
  value,
  options,
  onChange,
  placeholder,
  allowCustom = false,
  helper,
  disabled = false,
}: {
  label: string;
  name: keyof FormState;
  value: string;
  options: string[];
  onChange: (name: keyof FormState, value: string) => void;
  placeholder: string;
  allowCustom?: boolean;
  helper?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(value);
  const ref = useRef<HTMLDivElement | null>(null);
  const normalizedOptions = useMemo(() => Array.from(new Set(options)), [options]);
  const searchTerm = query.trim().toLowerCase();
  const shouldFilter = searchTerm.length > 0 && query !== value;
  const filtered = shouldFilter ? normalizedOptions.filter((option) => matchesOption(option, searchTerm)) : normalizedOptions;
  const visibleOptions = shouldFilter ? filtered : normalizedOptions;
  const customValue = query.trim();
  const canUseCustom =
    allowCustom &&
    customValue.length > 0 &&
    !normalizedOptions.some((option) => option.toLowerCase() === customValue.toLowerCase());

  useEffect(() => setQuery(value), [value]);

  useEffect(() => {
    function close(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div ref={ref} style={{ display: "grid", gap: 6, fontSize: 12, fontWeight: 650, color: "var(--ink)" }}>
      <div style={{ position: "relative", display: "grid", gap: 6 }}>
        <label htmlFor={`${String(name)}-search`}>{label}</label>
        <input
          id={`${String(name)}-search`}
          aria-label={label}
          value={query}
          placeholder={placeholder}
          disabled={disabled}
          onFocus={() => !disabled && setOpen(true)}
          onClick={() => !disabled && setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            if (!disabled) setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
            if (event.key === "Enter" && (canUseCustom || filtered[0])) {
              event.preventDefault();
              const nextValue = canUseCustom ? customValue : filtered[0];
              onChange(name, nextValue);
              setQuery(nextValue);
              setOpen(false);
            }
          }}
          style={{ ...inputStyle, width: "100%" }}
        />
        {open && (
          <DropdownPanel>
            {visibleOptions.map((option, index) => (
              <DropdownOption
                key={`${option}-${index}`}
                selected={option === value}
                onSelect={() => {
                  onChange(name, option);
                  setQuery(option);
                  setOpen(false);
                }}
              >
                {option}
              </DropdownOption>
            ))}
            {canUseCustom && (
              <DropdownOption
                key={`custom-${customValue}`}
                selected={false}
                onSelect={() => {
                  onChange(name, customValue);
                  setQuery(customValue);
                  setOpen(false);
                }}
              >
                {`Use custom: ${customValue}`}
              </DropdownOption>
            )}
          </DropdownPanel>
        )}
      </div>
    </div>
  );
}

function MultiSelectDropdown({
  label,
  options,
  searchOptions,
  selected,
  onToggle,
  allowCustom = false,
  maxDefaultOptions = 12,
  maxSearchOptions = 20,
  showSelectedChips = true,
  helper,
}: {
  label: string;
  options: string[];
  searchOptions?: string[];
  selected: string[];
  onToggle: (option: string) => void;
  allowCustom?: boolean;
  maxDefaultOptions?: number;
  maxSearchOptions?: number;
  showSelectedChips?: boolean;
  helper?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement | null>(null);
  const normalizedOptions = useMemo(() => Array.from(new Set(options)), [options]);
  const normalizedSearchOptions = useMemo(() => Array.from(new Set(searchOptions ?? options)), [options, searchOptions]);
  const searchTerm = query.trim().toLowerCase();
  const filtered = normalizedSearchOptions.filter((option) => matchesOption(option, searchTerm));
  const visibleOptions = (searchTerm ? filtered : normalizedOptions).slice(0, searchTerm ? maxSearchOptions : maxDefaultOptions);
  const customValue = query.trim();
  const canUseCustom =
    allowCustom &&
    customValue.length > 0 &&
    !normalizedSearchOptions.some((option) => option.toLowerCase() === customValue.toLowerCase()) &&
    !selected.some((option) => option.toLowerCase() === customValue.toLowerCase());

  useEffect(() => {
    function close(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div ref={ref} style={{ display: "grid", gap: 8 }}>
      <div style={{ position: "relative", display: "grid", gap: 8 }}>
        <label htmlFor={`${label.replace(/\W+/g, "-").toLowerCase()}-multi`} style={{ fontSize: 13, fontWeight: 750 }}>
          {label}
        </label>
        <input
          id={`${label.replace(/\W+/g, "-").toLowerCase()}-multi`}
          aria-label={label}
          value={query}
          placeholder={selected.length ? `${selected.length} selected - search or add more` : "Search options"}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
            if (event.key === "Enter" && (canUseCustom || filtered[0])) {
              event.preventDefault();
              onToggle(canUseCustom ? customValue : filtered[0]);
              setQuery("");
              setOpen(false);
            }
          }}
          style={{ ...inputStyle, width: "100%" }}
        />
        {helper && <span style={{ color: "var(--muted)", fontSize: 11, lineHeight: 1.4 }}>{helper}</span>}
        {open && (
          <DropdownPanel>
            {visibleOptions.map((option, index) => (
              <DropdownOption
                key={`${option}-${index}`}
                selected={selected.includes(option)}
                onSelect={() => {
                  onToggle(option);
                  setQuery("");
                  setOpen(false);
                }}
              >
                {option}
              </DropdownOption>
            ))}
            {canUseCustom && (
              <DropdownOption
                selected={false}
                onSelect={() => {
                  onToggle(customValue);
                  setQuery("");
                  setOpen(false);
                }}
              >
                {`Use custom: ${customValue}`}
              </DropdownOption>
            )}
          </DropdownPanel>
        )}
      </div>
      {showSelectedChips && selected.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
          {selected.map((option, index) => (
            <button
              key={`${option}-${index}`}
              type="button"
              onClick={() => onToggle(option)}
              style={{
                border: "1px solid var(--ink)",
                borderRadius: 999,
                background: "var(--ink)",
                color: "#fff",
                padding: "6px 9px",
                fontSize: 11,
                fontWeight: 750,
              }}
            >
              {option} ×
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function OptionDropdown({
  label,
  options,
  selected,
  onToggle,
  multi = true,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
  multi?: boolean;
}) {
  return (
    <div>
      <MultiSelectDropdown
        label={label}
        options={options}
        selected={selected}
        onToggle={(option) => {
          if (multi) onToggle(option);
          else if (!selected.includes(option)) onToggle(option);
        }}
      />
    </div>
  );
}

function LocationPreferenceSelector({
  selected,
  workModes,
  relocate,
  globalSearch,
  onToggleLocation,
  onToggleWorkMode,
  onToggleRelocate,
  onToggleGlobalSearch,
}: {
  selected: string[];
  workModes: string[];
  relocate: boolean;
  globalSearch: boolean;
  onToggleLocation: (location: string) => void;
  onToggleWorkMode: (mode: string) => void;
  onToggleRelocate: () => void;
  onToggleGlobalSearch: () => void;
}) {
  const [queries, setQueries] = useState<Record<string, string>>({});
  const remoteFirst = workModes.includes("Remote-first roles");

  function setQuery(country: string, value: string) {
    setQueries((prev) => ({ ...prev, [country]: value }));
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div style={{ border: "1px solid var(--line)", borderRadius: 18, padding: 18, background: "linear-gradient(135deg,#fff,#f8fafc)" }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 18 }}>Global location preferences</h3>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
          Choose where you are open to working. VeriBridge will later compare these locations with opportunity volume, salary signals, remote availability, and work authorization fit.
        </p>
        {selected.length === 0 ? (
          <p style={{ margin: "10px 0 0", color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
            No preferences selected yet. Add your preferred locations, work type, or salary expectations when ready.
          </p>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
            {selected.map((location) => (
              <button
                key={location}
                type="button"
                onClick={() => onToggleLocation(location)}
                style={{
                  border: "1px solid var(--ink)",
                  borderRadius: 999,
                  background: "var(--ink)",
                  color: "#fff",
                  padding: "7px 10px",
                  fontSize: 12,
                  fontWeight: 750,
                }}
              >
                {location} ×
              </button>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: "grid", gap: 12 }}>
        {locationGroups.map((group, index) => {
          const locations = group.locations.map(([name]) => name);
          const query = queries[group.country] ?? "";
          const customLocation = query.trim();
          const canAddCustom = customLocation.length > 0 && !selected.includes(customLocation);

          return (
            <details
              key={group.country}
              open={index < 2}
              style={{
                border: "1px solid var(--line)",
                borderRadius: 16,
                background: "#fff",
                overflow: "hidden",
              }}
            >
              <summary
                style={{
                  cursor: "pointer",
                  listStyle: "none",
                  padding: "15px 16px",
                  fontSize: 14,
                  fontWeight: 850,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <span>{group.country}</span>
                <span style={{ color: "var(--muted)", fontSize: 12, fontWeight: 700 }}>{locations.length} regions</span>
              </summary>
              <div style={{ borderTop: "1px solid var(--line)", padding: 16, display: "grid", gap: 14 }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  <button type="button" onClick={() => locations.forEach((location) => !selected.includes(location) && onToggleLocation(location))} style={smallButtonStyle}>
                    Select all
                  </button>
                  <button type="button" onClick={() => locations.forEach((location) => selected.includes(location) && onToggleLocation(location))} style={smallButtonStyle}>
                    Clear country
                  </button>
                </div>
                <label style={{ display: "grid", gap: 6, fontSize: 12, fontWeight: 700 }}>
                  {group.searchPlaceholder}
                  <input
                    aria-label={group.searchPlaceholder}
                    value={query}
                    onChange={(event) => setQuery(group.country, event.target.value)}
                    placeholder={group.searchPlaceholder}
                    style={{ ...inputStyle, width: "100%" }}
                  />
                </label>
                {canAddCustom && (
                  <button
                    type="button"
                    onClick={() => {
                      onToggleLocation(customLocation);
                      setQuery(group.country, "");
                    }}
                    style={{
                      justifySelf: "start",
                      border: "1px dashed var(--indigo)",
                      borderRadius: 999,
                      background: "var(--indigo-soft)",
                      color: "var(--ink)",
                      padding: "8px 11px",
                      fontSize: 12,
                      fontWeight: 800,
                    }}
                  >
                    Add custom location: {customLocation}
                  </button>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
                  {group.locations.map(([location, signal]) => {
                    const active = selected.includes(location);
                    return (
                      <button
                        key={location}
                        type="button"
                        onClick={() => onToggleLocation(location)}
                        aria-pressed={active}
                        style={{
                          minHeight: 86,
                          border: active ? "1px solid var(--ink)" : "1px solid var(--line)",
                          borderRadius: 14,
                          background: active ? "linear-gradient(135deg,var(--ink),#29304d)" : "#fff",
                          color: active ? "#fff" : "var(--ink)",
                          padding: 13,
                          textAlign: "left",
                          display: "grid",
                          gap: 8,
                        }}
                      >
                        <strong style={{ fontSize: 13 }}>{location}</strong>
                        <span style={{ color: active ? "rgba(255,255,255,.78)" : "var(--muted)", fontSize: 11, lineHeight: 1.35 }}>
                          {signal}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </details>
          );
        })}
      </div>

      <div style={{ border: "1px solid var(--line)", borderRadius: 18, padding: 18, background: "#fff", display: "grid", gap: 14 }}>
        <div>
          <h3 style={{ margin: "0 0 4px", fontSize: 17 }}>Work mode</h3>
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 13 }}>Choose the work styles that fit your search.</p>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
          {["On-site", "Hybrid", "Remote", "Remote worldwide", "Flexible"].map((mode) => {
            const active = workModes.includes(mode);
            return (
              <button
                key={mode}
                type="button"
                aria-pressed={active}
                onClick={() => onToggleWorkMode(mode)}
                style={{
                  minHeight: 54,
                  border: active ? "1px solid var(--ink)" : "1px solid var(--line)",
                  borderRadius: 14,
                  background: active ? "var(--ink)" : "#fff",
                  color: active ? "#fff" : "var(--ink)",
                  fontWeight: 800,
                }}
              >
                {mode}
              </button>
            );
          })}
        </div>
        {workModes.length === 0 && (
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
            No work mode selected yet. Add the work styles you prefer for your search.
          </p>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10 }}>
        <PreferenceToggle label="Open to relocate" active={relocate} onToggle={onToggleRelocate} />
        <PreferenceToggle label="Open to global opportunities" active={globalSearch} onToggle={onToggleGlobalSearch} />
        <PreferenceToggle label="Include remote-first roles" active={remoteFirst} onToggle={() => onToggleWorkMode("Remote-first roles")} />
      </div>
    </div>
  );
}

function PreferenceToggle({ label, active, onToggle }: { label: string; active: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onToggle}
      style={{
        border: active ? "1px solid var(--ink)" : "1px solid var(--line)",
        borderRadius: 15,
        background: active ? "var(--ink)" : "#fff",
        color: active ? "#fff" : "var(--ink)",
        padding: 14,
        textAlign: "left",
        fontWeight: 800,
      }}
    >
      {label}
    </button>
  );
}

function renderProofEvidenceFieldGroup(form: FormState, update: (name: keyof FormState, value: string | boolean | string[]) => void) {
  const sourceType = form.proofEvidenceType.trim();
  const accessMethod = form.proofEvidenceAccessMethod === "upload_file" ? "upload_file" : "public_link";
  const showExactCodeLocation = sourceType === "GitHub code file" || form.proofExactCodeLocation;
  const uploadedFileLabel = inferUploadedFileLabel(form.proofUploadedFileName, form.proofUploadedFileType);
  const uploadedFileSize = form.proofUploadedFileSize || "";
  const uploadedPreviewKind = isPreviewableVideo(form.proofUploadedFileName, form.proofUploadedFileType)
    ? "video"
    : isPreviewableImage(form.proofUploadedFileName, form.proofUploadedFileType)
      ? "image"
      : isPreviewablePdf(form.proofUploadedFileName, form.proofUploadedFileType)
        ? "pdf"
        : "file";

  if (accessMethod === "upload_file") {
    return (
      <div style={{ display: "grid", gap: 16 }}>
        <div style={{ border: "1px solid var(--line)", borderRadius: 16, background: "#fff", padding: 16, display: "grid", gap: 12 }}>
          <label
            style={{
              display: "grid",
              gap: 6,
              fontSize: 12,
              fontWeight: 650,
              color: "var(--ink)",
            }}
          >
            Upload evidence file
            <input
              aria-label="Upload evidence file"
              type="file"
              accept={UPLOAD_EVIDENCE_FILE_ACCEPT}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                const nextUrl = URL.createObjectURL(file);
                update("proofUploadedFileName", file.name);
                update("proofUploadedFileType", file.type || inferUploadedFileLabel(file.name, file.type));
                update("proofUploadedFileSize", formatFileSize(file.size));
                update("proofUploadedFileUrl", nextUrl);
                update("proofUploadedFileId", `${file.name}-${file.size}-${Date.now()}`);
              }}
              style={{
                ...inputStyle,
                padding: "10px 12px",
                cursor: "pointer",
              }}
            />
            <span style={{ color: "var(--muted)", fontSize: 11, lineHeight: 1.4 }}>
              Upload a report, diagram, certificate, screenshot, slide deck, notebook, text file, or recorded demo that proves this skill.
            </span>
          </label>

          {form.proofUploadedFileName && (
            <div
              style={{
                border: "1px solid var(--line)",
                borderRadius: 14,
                background: "var(--bg)",
                padding: 14,
                display: "grid",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                <div>
                  <div style={{ fontWeight: 800, color: "var(--ink)" }}>{uploadedFileLabel}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                    {form.proofUploadedFileName}
                    {uploadedFileSize ? ` · ${uploadedFileSize}` : ""}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                    File type: {form.proofUploadedFileType || "unknown"}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    update("proofUploadedFileName", "");
                    update("proofUploadedFileType", "");
                    update("proofUploadedFileSize", "");
                    update("proofUploadedFileUrl", "");
                    update("proofUploadedFileId", "");
                  }}
                  style={{
                    border: "1px solid var(--line)",
                    borderRadius: 10,
                    background: "#fff",
                    padding: "7px 10px",
                    fontWeight: 750,
                    color: "var(--ink)",
                  }}
                >
                  Remove file
                </button>
              </div>

              {uploadedPreviewKind === "image" && form.proofUploadedFileUrl ? (
                <img
                  src={form.proofUploadedFileUrl}
                  alt={form.proofUploadedFileName}
                  style={{ width: "100%", maxHeight: 220, objectFit: "cover", borderRadius: 12, border: "1px solid var(--line)" }}
                />
              ) : uploadedPreviewKind === "video" && form.proofUploadedFileUrl ? (
                <video controls src={form.proofUploadedFileUrl} style={{ width: "100%", maxHeight: 240, borderRadius: 12, border: "1px solid var(--line)" }} />
              ) : uploadedPreviewKind === "pdf" && form.proofUploadedFileUrl ? (
                <div
                  style={{
                    border: "1px dashed var(--line)",
                    borderRadius: 12,
                    background: "#fff",
                    padding: 14,
                    color: "var(--muted)",
                    fontSize: 12,
                    lineHeight: 1.55,
                  }}
                >
                  PDF preview available in browser or recruiter viewer. The uploaded file metadata is stored for review.
                </div>
              ) : (
                <div
                  style={{
                    border: "1px dashed var(--line)",
                    borderRadius: 12,
                    background: "#fff",
                    padding: 14,
                    color: "var(--muted)",
                    fontSize: 12,
                    lineHeight: 1.55,
                  }}
                >
                  Preview unavailable for this file type. Recruiters will still see the uploaded file metadata and sharing note.
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: 16, background: "#fff", padding: 16, display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gap: 4 }}>
            <div style={{ fontSize: 12, fontWeight: 750, color: "var(--ink)" }}>Recruiter visibility</div>
            <div style={{ color: "var(--muted)", fontSize: 11, lineHeight: 1.45 }}>
              Private uploads are not public. They are shown only according to your sharing settings.
            </div>
          </div>

          <button
            type="button"
            role="switch"
            aria-checked={form.proofIsRecruiterVisible}
            aria-label="Recruiter visibility"
            onClick={() => {
              const next = !form.proofIsRecruiterVisible;
              update("proofIsRecruiterVisible", next);
              if (!next) update("proofRequiresApproval", false);
            }}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              width: "100%",
              border: "1px solid var(--line)",
              borderRadius: 14,
              background: form.proofIsRecruiterVisible ? "var(--indigo-soft)" : "var(--bg-2)",
              padding: "12px 14px",
              textAlign: "left",
              cursor: "pointer",
            }}
          >
            <div>
              <div style={{ fontSize: 13, fontWeight: 800, color: "var(--ink)" }}>Recruiter visibility</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                {form.proofIsRecruiterVisible ? "Share with authorized recruiters" : "Private — only I can see this evidence"}
              </div>
            </div>
            <div
              style={{
                width: 42,
                height: 24,
                borderRadius: 999,
                background: form.proofIsRecruiterVisible ? "var(--indigo)" : "var(--line)",
                position: "relative",
                flexShrink: 0,
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: 3,
                  left: form.proofIsRecruiterVisible ? 21 : 3,
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: "#fff",
                  boxShadow: "0 1px 3px rgba(0,0,0,.2)",
                }}
              />
            </div>
          </button>

          <button
            type="button"
            role="switch"
            aria-checked={form.proofRequiresApproval}
            aria-label="Require my approval before each recruiter can view this evidence"
            disabled={!form.proofIsRecruiterVisible}
            onClick={() => {
              if (!form.proofIsRecruiterVisible) return;
              update("proofRequiresApproval", !form.proofRequiresApproval);
            }}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              width: "100%",
              border: "1px solid var(--line)",
              borderRadius: 14,
              background: !form.proofIsRecruiterVisible ? "var(--bg-2)" : form.proofRequiresApproval ? "#fffbeb" : "#fff",
              padding: "12px 14px",
              textAlign: "left",
              cursor: form.proofIsRecruiterVisible ? "pointer" : "not-allowed",
              opacity: form.proofIsRecruiterVisible ? 1 : 0.6,
            }}
          >
            <div>
              <div style={{ fontSize: 13, fontWeight: 800, color: "var(--ink)" }}>Require my approval before each recruiter can view this evidence</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                {form.proofIsRecruiterVisible
                  ? form.proofRequiresApproval
                    ? "Recruiters must request access first."
                    : "Recruiters can view this evidence directly."
                  : "Enable recruiter visibility to turn this on."}
              </div>
            </div>
            <div
              style={{
                width: 42,
                height: 24,
                borderRadius: 999,
                background: form.proofRequiresApproval ? "var(--indigo)" : "var(--line)",
                position: "relative",
                flexShrink: 0,
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: 3,
                  left: form.proofRequiresApproval ? 21 : 3,
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: "#fff",
                  boxShadow: "0 1px 3px rgba(0,0,0,.2)",
                }}
              />
            </div>
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
          <TextField label="Evidence title" name="proofEvidenceTitle" placeholder="FastAPI prediction endpoint proof" value={form.proofEvidenceTitle} onChange={update} />
          <TextField label="Related project/repository URL (optional)" name="proofRelatedProjectUrl" placeholder="https://github.com/user/project" value={form.proofRelatedProjectUrl} onChange={update} />
        </div>

        <TextField
          label="Visibility note for recruiters"
          name="proofVisibilityNote"
          placeholder="Visible only after I approve recruiter sharing"
          value={form.proofVisibilityNote}
          onChange={update}
          helper="Private uploads are only shown to authorized reviewers/recruiters based on your sharing settings."
        />

        <TextAreaField
          label="Evidence description"
          name="proofEvidenceDescription"
          placeholder="Built FastAPI prediction endpoint using Python."
          value={form.proofEvidenceDescription}
          onChange={update}
          helper="Explain what this uploaded file proves for the selected skill."
        />
      </div>
    );
  }

  if (accessMethod === "public_link") {
    return (
      <>
        {sourceType === "GitHub repository" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Repository URL (optional)" name="proofRepositoryUrl" placeholder="https://github.com/user/project" value={form.proofRepositoryUrl} onChange={update} />
            <TextField label="Optional key files" name="proofKeyFiles" placeholder="app/main.py, workflows/ci.yml, README.md" value={form.proofKeyFiles} onChange={update} helper="Comma-separated files or folders." />
          </div>
        )}

        {sourceType === "GitHub code file" && (
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
              <TextField label="Repository URL" name="proofRepositoryUrl" placeholder="https://github.com/user/project" value={form.proofRepositoryUrl} onChange={update} />
              <TextField label="File path" name="proofFilePath" placeholder="app/main.py" value={form.proofFilePath} onChange={update} />
            </div>
            {showExactCodeLocation ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
                <TextField label="Start line" name="proofLineStart" placeholder="20" value={form.proofLineStart} onChange={update} />
                <TextField label="End line" name="proofLineEnd" placeholder="95" value={form.proofLineEnd} onChange={update} />
              </div>
            ) : (
              <button
                type="button"
                onClick={() => update("proofExactCodeLocation", true)}
                style={{
                  justifySelf: "start",
                  border: "1px solid var(--line)",
                  borderRadius: 999,
                  background: "#fff",
                  color: "var(--ink)",
                  padding: "8px 12px",
                  fontSize: 12,
                  fontWeight: 750,
                }}
              >
                Add exact code location
              </button>
            )}
          </div>
        )}

        {sourceType === "Deployed app / live demo" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Live demo URL" name="proofEvidenceUrl" placeholder="https://demo.example.com" value={form.proofEvidenceUrl} onChange={update} />
            <TextField label="Repository URL (optional)" name="proofRepositoryUrl" placeholder="https://github.com/user/project" value={form.proofRepositoryUrl} onChange={update} />
          </div>
        )}

        {sourceType === "Cloud deployment proof" && (
          <div style={{ display: "grid", gap: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
              <SelectDropdown label="Cloud provider" name="proofCloudProvider" value={form.proofCloudProvider} options={[...CLOUD_PROVIDER_OPTIONS] as string[]} onChange={update} />
              <TextField label="Deployment URL (optional)" name="proofEvidenceUrl" placeholder="https://app.example.com" value={form.proofEvidenceUrl} onChange={update} />
              <TextField label="Repository URL (optional)" name="proofRepositoryUrl" placeholder="https://github.com/user/project" value={form.proofRepositoryUrl} onChange={update} />
              <TextField label="Config / workflow file (optional)" name="proofConfigFile" placeholder="infra/main.tf or .github/workflows/deploy.yml" value={form.proofConfigFile} onChange={update} />
              <TextField label="Architecture diagram URL (optional)" name="proofDiagramUrl" placeholder="https://drive.google.com/..." value={form.proofDiagramUrl} onChange={update} />
            </div>
          </div>
        )}

        {sourceType === "Architecture diagram" && (
          <TextField label="Diagram URL (optional)" name="proofDiagramUrl" placeholder="https://drive.google.com/..." value={form.proofDiagramUrl} onChange={update} />
        )}

        {(sourceType === "Project report" || sourceType === "Coursework project") && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField
              label={sourceType === "Project report" ? "Report URL (optional)" : "Project artifact URL (optional)"}
              name="proofEvidenceUrl"
              placeholder={sourceType === "Project report" ? "https://drive.google.com/..." : "https://github.com/user/project"}
              value={form.proofEvidenceUrl}
              onChange={update}
            />
            <TextField label="Repository URL (optional)" name="proofRepositoryUrl" placeholder="https://github.com/user/project" value={form.proofRepositoryUrl} onChange={update} />
          </div>
        )}

        {sourceType === "Certificate" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Certificate URL (optional)" name="proofEvidenceUrl" placeholder="https://credential.example.com/..." value={form.proofEvidenceUrl} onChange={update} />
            <TextField label="Issuer" name="proofCertificateIssuer" placeholder="AWS, Coursera, university, employer" value={form.proofCertificateIssuer} onChange={update} />
            <TextField label="Completion date (optional)" name="proofCompletionDate" placeholder="2026-05-08" type="date" value={form.proofCompletionDate} onChange={update} />
          </div>
        )}

        {sourceType === "Dashboard / analytics report" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Dashboard/report URL (optional)" name="proofEvidenceUrl" placeholder="https://lookerstudio.google.com/..." value={form.proofEvidenceUrl} onChange={update} />
            <TextField label="Tool used (optional)" name="proofToolUsed" placeholder="Excel, Tableau, Power BI, Looker" value={form.proofToolUsed} onChange={update} />
          </div>
        )}

        {sourceType === "Notebook / experiment" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Notebook URL or file path (optional)" name="proofEvidenceUrl" placeholder="https://colab.research.google.com/..." value={form.proofEvidenceUrl} onChange={update} />
            <TextField label="Repository URL (optional)" name="proofRepositoryUrl" placeholder="https://github.com/user/project" value={form.proofRepositoryUrl} onChange={update} />
            <TextField label="Dataset (optional)" name="proofDataset" placeholder="Kaggle, internal, public dataset" value={form.proofDataset} onChange={update} />
            <TextField label="Metrics / results (optional)" name="proofMetrics" placeholder="Accuracy 92%, F1 0.88" value={form.proofMetrics} onChange={update} />
            {showExactCodeLocation && (
              <>
                <TextField label="Start line" name="proofLineStart" placeholder="20" value={form.proofLineStart} onChange={update} />
                <TextField label="End line" name="proofLineEnd" placeholder="95" value={form.proofLineEnd} onChange={update} />
              </>
            )}
          </div>
        )}

        {sourceType === "Presentation / slides" && (
          <TextField label="Slides URL (optional)" name="proofEvidenceUrl" placeholder="https://docs.google.com/presentation/..." value={form.proofEvidenceUrl} onChange={update} />
        )}

        {sourceType === "Portfolio link" && (
          <TextField label="Portfolio URL (optional)" name="proofEvidenceUrl" placeholder="https://yourportfolio.com/..." value={form.proofEvidenceUrl} onChange={update} />
        )}

        {sourceType === "Team / leadership evidence" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Project/team artifact URL (optional)" name="proofEvidenceUrl" placeholder="https://docs.google.com/..." value={form.proofEvidenceUrl} onChange={update} />
            <TextField label="Role / title" name="proofRoleTitle" placeholder="Team lead, project manager, organizer" value={form.proofRoleTitle} onChange={update} />
          </div>
        )}

        {sourceType === "LinkedIn post" && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="LinkedIn post URL" name="proofLinkedInPostUrl" placeholder="https://www.linkedin.com/posts/..." value={form.proofLinkedInPostUrl} onChange={update} />
            <TextField label="Related project/repository URL (optional)" name="proofRelatedProjectUrl" placeholder="https://github.com/user/project" value={form.proofRelatedProjectUrl} onChange={update} />
          </div>
        )}

        {sourceType === "Other" && showExactCodeLocation && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <TextField label="Start line" name="proofLineStart" placeholder="20" value={form.proofLineStart} onChange={update} />
            <TextField label="End line" name="proofLineEnd" placeholder="95" value={form.proofLineEnd} onChange={update} />
          </div>
        )}

        {sourceType === "Other" && !showExactCodeLocation && (
          <button
            type="button"
            onClick={() => update("proofExactCodeLocation", true)}
            style={{
              justifySelf: "start",
              border: "1px solid var(--line)",
              borderRadius: 999,
              background: "#fff",
              color: "var(--ink)",
              padding: "8px 12px",
              fontSize: 12,
              fontWeight: 750,
            }}
          >
            Add exact code location
          </button>
        )}

        <TextAreaField label="Evidence description" name="proofEvidenceDescription" placeholder="Describe the evidence and what it demonstrates." value={form.proofEvidenceDescription} onChange={update} />
      </>
    );
  }
}

const smallButtonStyle = {
  border: "1px solid var(--line)",
  borderRadius: 999,
  background: "#fff",
  color: "var(--ink)",
  padding: "7px 10px",
  fontSize: 12,
  fontWeight: 800,
} as const;

function DropdownPanel({ children }: { children: ReactNode }) {
  return (
    <div
      role="listbox"
      style={{
        position: "absolute",
        zIndex: 80,
        top: "calc(100% + 6px)",
        left: 0,
        right: 0,
        maxHeight: 240,
        overflowY: "auto",
        border: "1px solid var(--line)",
        borderRadius: 14,
        background: "#fff",
        boxShadow: "0 18px 42px rgba(10,14,26,.16)",
        padding: 6,
      }}
    >
      {children}
    </div>
  );
}

function DropdownOption({
  children,
  selected,
  onSelect,
}: {
  children: string;
  selected?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onSelect}
      style={{
        display: "flex",
        justifyContent: "space-between",
        width: "100%",
        border: 0,
        borderRadius: 10,
        background: selected ? "var(--indigo-soft)" : "#fff",
        color: "var(--ink)",
        padding: "10px 11px",
        fontSize: 13,
        fontWeight: selected ? 750 : 600,
        textAlign: "left",
      }}
    >
      <span>{children}</span>
      {selected && <span aria-hidden="true">✓</span>}
    </button>
  );
}

function VerificationBadge({ status }: { status: ProofVerificationStatus }) {
  const styles: Record<ProofVerificationStatus, { background: string; color: string; border: string }> = {
    Verified: { background: "#ecfdf5", color: "#065f46", border: "#a7f3d0" },
    "Pending verification": { background: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
    "Skill usage not found": { background: "#fef2f2", color: "#b91c1c", border: "#fecaca" },
    "Needs review": { background: "#fffbeb", color: "#92400e", border: "#fde68a" },
  };

  const style = styles[status];

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        border: `1px solid ${style.border}`,
        borderRadius: 999,
        background: style.background,
        color: style.color,
        padding: "6px 9px",
        fontSize: 11,
        fontWeight: 800,
      }}
    >
      {status}
    </span>
  );
}

function ProofEvidenceCard({
  entry,
  onRemove,
  viewerRole = "student_owner",
}: {
  entry: ProofEvidenceEntry;
  onRemove: () => void;
  viewerRole?: "student_owner" | "recruiter";
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const skill = entry.skill ?? entry.skill_name ?? "";
  const sourceType = entry.sourceType ?? entry.evidence_type ?? "";
  const accessMethod = entry.evidenceAccessMethod ?? entry.evidence_access_method ?? "public_link";
  const evidenceUrl = entry.evidenceUrl ?? entry.evidence_url ?? "";
  const repositoryUrl = entry.repositoryUrl || "";
  const linkedInPostUrl = entry.linkedInPostUrl ?? entry.linked_in_post_url ?? "";
  const relatedProjectUrl = entry.relatedProjectUrl ?? entry.related_project_url ?? "";
  const evidenceTitle = entry.evidenceTitle ?? entry.evidence_title ?? "";
  const visibilityNote = entry.visibilityNote ?? entry.visibility_note ?? "";
  const isRecruiterVisible = entry.isRecruiterVisible ?? entry.is_recruiter_visible ?? false;
  const requiresApproval = entry.requiresApproval ?? entry.requires_approval ?? false;
  const uploadedFileName = entry.uploadedFileName ?? entry.uploaded_file_name ?? "";
  const uploadedFileType = entry.uploadedFileType ?? entry.uploaded_file_type ?? "";
  const uploadedFileSize = entry.uploadedFileSize ?? entry.uploaded_file_size ?? "";
  const uploadedFileUrl = entry.uploadedFileUrl ?? entry.uploaded_file_url ?? "";
  const uploadedFileId = entry.uploadedFileId ?? entry.uploaded_file_id ?? "";
  const filePath = entry.filePath ?? entry.file_path ?? "";
  const lineStart = entry.startLine ?? entry.line_start ?? "";
  const lineEnd = entry.endLine ?? entry.line_end ?? "";
  const description = entry.description ?? entry.evidence_description ?? "";
  const verificationStatus = entry.verificationStatus ?? entry.verification_status ?? "Pending verification";
  const verificationSummary = entry.verificationSummary ?? entry.verification_summary ?? "Pending verification";
  const visibilityLabel = getProofVisibilityLabel(isRecruiterVisible, requiresApproval, accessMethod, viewerRole);
  const previewKind = isPreviewableVideo(uploadedFileName, uploadedFileType)
    ? "video"
    : isPreviewableImage(uploadedFileName, uploadedFileType)
      ? "image"
      : isPreviewablePdf(uploadedFileName, uploadedFileType)
        ? "pdf"
        : "file";
  const details: Array<[string, string]> = [
    ["Skill", skill],
    ["Evidence source", sourceType],
    ["Evidence access", accessMethod === "upload_file" ? "Upload file" : "Public link"],
    ["Visibility", visibilityLabel],
    evidenceTitle ? ["Evidence title", evidenceTitle] : null,
    repositoryUrl ? ["Repository URL", repositoryUrl] : null,
    evidenceUrl ? ["Evidence URL", evidenceUrl] : null,
    linkedInPostUrl ? ["LinkedIn post URL", linkedInPostUrl] : null,
    relatedProjectUrl ? ["Related project/repository URL", relatedProjectUrl] : null,
    filePath ? ["File path", filePath] : null,
    lineStart || lineEnd ? ["Lines", `${lineStart || "?"}–${lineEnd || "?"}`] : null,
    uploadedFileName ? ["Uploaded file", uploadedFileName] : null,
    uploadedFileType ? ["File type", uploadedFileType] : null,
    uploadedFileSize ? ["File size", uploadedFileSize] : null,
    uploadedFileId ? ["File ID", uploadedFileId] : null,
    entry.keyFiles ? ["Key files", entry.keyFiles] : null,
    entry.cloudProvider ? ["Cloud provider", entry.cloudProvider] : null,
    entry.configFile ? ["Config / workflow file", entry.configFile] : null,
    entry.diagramUrl ? ["Architecture diagram URL", entry.diagramUrl] : null,
    entry.certificateIssuer ? ["Issuer", entry.certificateIssuer] : null,
    entry.completionDate ? ["Completion date", entry.completionDate] : null,
    entry.roleTitle ? ["Role / title", entry.roleTitle] : null,
    entry.toolUsed ? ["Tool used", entry.toolUsed] : null,
    entry.dataset ? ["Dataset", entry.dataset] : null,
    entry.metrics ? ["Metrics / results", entry.metrics] : null,
    visibilityNote ? ["Visibility note for recruiters", visibilityNote] : null,
    description ? ["Evidence description", description] : null,
  ].filter(Boolean) as Array<[string, string]>;

  return (
    <article
      className="vb-card-hover"
      style={{
        border: "1px solid var(--line)",
        borderRadius: 16,
        background: "#fff",
        padding: 16,
        display: "grid",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
        <div style={{ display: "grid", gap: 6 }}>
          <h4 style={{ margin: 0, fontSize: 16 }}>{skill}</h4>
          <p style={{ margin: "4px 0 0", color: "var(--muted)", fontSize: 12 }}>
            {accessMethod === "upload_file"
              ? !isRecruiterVisible
                ? "Private upload attached. Only you can preview it until you share it."
                : requiresApproval
                  ? "Recruiters must request approval before viewing this evidence."
                  : "Shared with authorized recruiters."
              : "Exact proof attached for recruiter review later."}
          </p>
        </div>
        <div style={{ display: "grid", justifyItems: "end", gap: 6 }}>
          <VerificationBadge status={verificationStatus} />
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              border: `1px solid ${!isRecruiterVisible ? "#cbd5e1" : requiresApproval ? "#fde68a" : "#a7f3d0"}`,
              borderRadius: 999,
              background: !isRecruiterVisible ? "#f8fafc" : requiresApproval ? "#fffbeb" : "#ecfdf5",
              color: !isRecruiterVisible ? "#475569" : requiresApproval ? "#92400e" : "#065f46",
              padding: "6px 9px",
              fontSize: 11,
              fontWeight: 800,
            }}
          >
            {visibilityLabel}
          </span>
        </div>
      </div>

          {accessMethod === "upload_file" && (
            <div style={{ display: "grid", gap: 10, border: "1px solid var(--line)", borderRadius: 14, padding: 12, background: "var(--bg)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                <div style={{ fontWeight: 800, color: "var(--ink)" }}>Uploaded evidence</div>
            <button
              type="button"
              onClick={() => setShowEvidence((current) => !current)}
              style={{
                border: "1px solid var(--line)",
                borderRadius: 10,
                background: "#fff",
                padding: "7px 10px",
                color: "var(--ink)",
                fontWeight: 750,
              }}
            >
              {showEvidence ? "Hide evidence" : "Show evidence"}
            </button>
          </div>
          {viewerRole === "recruiter" ? (
            isRecruiterVisible ? (
              requiresApproval ? (
                <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                  Request access to view this evidence.
                </div>
              ) : (
                <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                  Private uploads are only shown to authorized reviewers/recruiters based on your sharing settings.
                </div>
              )
            ) : (
              <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
                Evidence exists, but the student has not shared this private file.
              </div>
            )
          ) : (
            <div style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
              {isRecruiterVisible
                ? requiresApproval
                  ? "Recruiters must request approval before viewing this evidence."
                  : "Shared with authorized recruiters."
                : "Private uploads are not public. They are shown only according to your sharing settings."}
            </div>
          )}
          {showEvidence && viewerRole === "student_owner" && (
            <div style={{ display: "grid", gap: 10 }}>
              {evidenceTitle && <div><strong>Evidence title:</strong> {evidenceTitle}</div>}
              {uploadedFileName && <div><strong>Uploaded file:</strong> {uploadedFileName}</div>}
              {uploadedFileType && <div><strong>File type:</strong> {uploadedFileType}</div>}
              {uploadedFileSize && <div><strong>File size:</strong> {uploadedFileSize}</div>}
              {uploadedFileUrl && isPreviewableImage(uploadedFileName, uploadedFileType) && (
                <img src={uploadedFileUrl} alt={uploadedFileName} style={{ width: "100%", maxHeight: 240, objectFit: "cover", borderRadius: 12, border: "1px solid var(--line)" }} />
              )}
              {uploadedFileUrl && isPreviewableVideo(uploadedFileName, uploadedFileType) && (
                <video controls src={uploadedFileUrl} style={{ width: "100%", maxHeight: 260, borderRadius: 12, border: "1px solid var(--line)" }} />
              )}
              {uploadedFileUrl && isPreviewablePdf(uploadedFileName, uploadedFileType) && (
                <div style={{ border: "1px dashed var(--line)", borderRadius: 12, background: "#fff", padding: 12, color: "var(--muted)", fontSize: 12, lineHeight: 1.5 }}>
                  PDF preview available to authorized reviewers. Use the file metadata below for review.
                </div>
              )}
              {uploadedFileUrl && !isPreviewableImage(uploadedFileName, uploadedFileType) && !isPreviewableVideo(uploadedFileName, uploadedFileType) && !isPreviewablePdf(uploadedFileName, uploadedFileType) && (
                <div style={{ border: "1px dashed var(--line)", borderRadius: 12, background: "#fff", padding: 12, color: "var(--muted)", fontSize: 12, lineHeight: 1.5 }}>
                  Preview unavailable for this file type. Authorized recruiters can review the uploaded evidence metadata and open the stored file.
                </div>
              )}
              {uploadedFileUrl && (
                <button
                  type="button"
                  onClick={() => window.open(uploadedFileUrl, "_blank", "noopener,noreferrer")}
                  style={{
                    justifySelf: "start",
                    border: "1px solid var(--line)",
                    borderRadius: 10,
                    background: "#fff",
                    padding: "7px 10px",
                    fontWeight: 750,
                    color: "var(--ink)",
                  }}
                >
                  Open file
                </button>
              )}
            </div>
          )}
          {showEvidence && viewerRole === "recruiter" && !isRecruiterVisible && (
            <div
              style={{
                border: "1px dashed var(--line)",
                borderRadius: 10,
                background: "#fff",
                padding: 12,
                color: "var(--muted)",
                fontSize: 12,
                lineHeight: 1.5,
              }}
            >
              Evidence exists, but the student has not shared this private file.
            </div>
          )}
          {showEvidence && viewerRole === "recruiter" && isRecruiterVisible && requiresApproval && (
            <div
              style={{
                border: "1px dashed var(--line)",
                borderRadius: 10,
                background: "#fff",
                padding: 12,
                color: "var(--muted)",
                fontSize: 12,
                lineHeight: 1.5,
              }}
            >
              Request access to view this evidence.
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gap: 8, fontSize: 13, color: "var(--ink)" }}>
        {details.map(([label, value]) => (
          <div key={`${label}-${value}`}>
            <strong>{label}:</strong> {value}
          </div>
        ))}
        <div>
          <strong>Verification:</strong> {verificationSummary}
        </div>
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={onRemove}
          style={{
            border: "1px solid var(--line)",
            borderRadius: 10,
            background: "#fff",
            padding: "8px 11px",
            color: "var(--ink)",
            fontWeight: 750,
          }}
        >
          Remove
        </button>
      </div>
    </article>
  );
}

function MultiSelectChips({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
}) {
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 750, marginBottom: 10 }}>{label}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {options.map((option, index) => {
          const active = selected.includes(option);
          return (
            <button
              key={`${option}-${index}`}
              type="button"
              onClick={() => onToggle(option)}
              aria-pressed={active}
              style={{
                border: active ? "1px solid var(--ink)" : "1px solid var(--line)",
                borderRadius: 999,
                background: active ? "var(--ink)" : "#fff",
                color: active ? "#fff" : "var(--ink-2)",
                padding: "9px 12px",
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function OptionCardGroup({
  label,
  options,
  selected,
  onToggle,
  multi = true,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
  multi?: boolean;
}) {
  return (
    <div>
      <div style={{ fontSize: 13, fontWeight: 750, marginBottom: 10 }}>{label}</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
        {options.map((option, index) => {
          const active = selected.includes(option);
          return (
            <button
              key={`${option}-${index}`}
              type="button"
              aria-pressed={active}
              onClick={() => onToggle(option)}
              style={{
                minHeight: 48,
                border: active ? "1px solid var(--ink)" : "1px solid var(--line)",
                borderRadius: 13,
                background: active ? "linear-gradient(135deg,var(--ink),#29304d)" : "#fff",
                color: active ? "#fff" : "var(--ink)",
                padding: "10px 12px",
                fontSize: 13,
                fontWeight: 750,
                textAlign: "left",
              }}
            >
              {option}
              {!multi && active && <span style={{ display: "block", marginTop: 4, fontSize: 10, opacity: 0.75 }}>Selected</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function OnboardingFlow({ mode = "signup" }: { mode?: Mode }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>({
    universityCountry: "",
    degreeLevel: "",
    major: "",
    customMajor: "",
    graduationYear: "",
    targetRoles: [],
    customRole: "",
    targetIndustries: [],
    skills: [],
    selectedSkills: [],
    customSkill: "",
    targetLocations: [],
    customLocation: "",
    workModes: [],
    globalSearch: false,
    relocate: false,
    authorizationType: "",
    authorizationCountries: [],
    sponsorshipNeeded: "",
    authNotes: "",
    salaryMin: "",
    salaryMax: "",
    minimumSalary: "",
    currency: "",
    customCurrency: "",
    salaryPeriod: "",
    negotiable: "",
    proofSkill: "",
    proofEvidenceType: "",
    proofEvidenceAccessMethod: "public_link",
    proofRepositoryUrl: "",
    proofEvidenceUrl: "",
    proofLinkedInPostUrl: "",
    proofRelatedProjectUrl: "",
    proofKeyFiles: "",
    proofEvidenceTitle: "",
    proofVisibilityNote: "",
    proofIsRecruiterVisible: false,
    proofRequiresApproval: false,
    proofCloudProvider: "",
    proofConfigFile: "",
    proofDiagramUrl: "",
    proofCertificateIssuer: "",
    proofCompletionDate: "",
    proofRoleTitle: "",
    proofToolUsed: "",
    proofDataset: "",
    proofMetrics: "",
    proofFilePath: "",
    proofLineStart: "",
    proofLineEnd: "",
    proofExactCodeLocation: false,
    proofEvidenceDescription: "",
    proofUploadedFileName: "",
    proofUploadedFileType: "",
    proofUploadedFileSize: "",
    proofUploadedFileUrl: "",
    proofUploadedFileId: "",
    proofEvidence: [],
  });

  const derivedCareerFields = useMemo(
    () => (form.major ? careerFieldsByMajor[form.major] ?? [] : []),
    [form.major]
  );

  const skillSuggestions = useMemo(
    () => getSuggestedSkillsForContext(form.major, form.targetRoles),
    [form.major, form.targetRoles]
  );

  const proofSkillHint = useMemo(
    () => getSkillProofHint(form.proofSkill || form.selectedSkills[0] || ""),
    [form.proofSkill, form.selectedSkills]
  );

  const roleSuggestions = useMemo(
    () => Array.from(new Set([...getSuggestedRolesForMajor(form.major), ...form.targetRoles])),
    [form.major, form.targetRoles]
  );

  const industrySuggestions = useMemo(
    () => Array.from(new Set([...getSuggestedIndustriesForMajor(form.major), ...form.targetIndustries])),
    [form.major, form.targetIndustries]
  );

  const title = steps[step];
  const progress = ((step + 1) / steps.length) * 100;
  const isSignup = mode === "signup";

  function update(name: keyof FormState, value: string | boolean | string[] | ProofEvidenceEntry[]) {
    setForm((prev) => {
      if (name === "skills" || name === "selectedSkills") {
        const selectedSkills = Array.isArray(value) ? (value as string[]) : prev.selectedSkills;
        return { ...prev, skills: selectedSkills, selectedSkills };
      }

      if (name === "proofEvidence") {
        const proofEvidence = Array.isArray(value) ? (value as ProofEvidenceEntry[]) : prev.proofEvidence;
        return { ...prev, proofEvidence };
      }

      return { ...prev, [name]: value };
    });
  }

  function toggleList(name: keyof FormState, option: string) {
    const current = form[name] as unknown;
    const selected = Array.isArray(current) ? (current as string[]) : [];
    const next = selected.includes(option) ? selected.filter((item) => item !== option) : [...selected, option];
    update(name, next);
  }

  function deriveProofVerification(
    skillName: string,
    sourceType: string,
    accessMethod: string,
    repositoryUrl: string,
    evidenceUrl: string,
    filePath: string,
    lineStart: string,
    lineEnd: string,
    evidenceDescription: string,
    cloudProvider: string,
    configFile: string,
    uploadedFileName: string,
    uploadedFileType: string
  ): Pick<ProofEvidenceEntry, "verificationStatus" | "verificationSummary"> {
    const skill = skillName.trim().toLowerCase();
    const source = sourceType.trim().toLowerCase();
    const method = accessMethod.trim().toLowerCase();
    const repository = repositoryUrl.trim().toLowerCase();
    const url = evidenceUrl.trim().toLowerCase();
    const path = filePath.trim().toLowerCase();
    const description = evidenceDescription.trim().toLowerCase();
    const config = configFile.trim().toLowerCase();
    const provider = cloudProvider.trim().toLowerCase();
    const uploadedName = uploadedFileName.trim().toLowerCase();
    const uploadedMime = uploadedFileType.trim().toLowerCase();
    const uploadedLooksLikeVideo = /\.(mp4|mov|webm)$/i.test(uploadedName) || uploadedMime.startsWith("video/");
    const uploadedLooksLikeImage = /\.(png|jpg|jpeg|webp)$/i.test(uploadedName) || uploadedMime.startsWith("image/");
    const uploadedLooksLikePdf = /\.pdf$/i.test(uploadedName) || uploadedMime === "application/pdf";
    const hasUploadedEvidence = Boolean(uploadedName || uploadedMime);
    const hasAnyEvidence = Boolean(repository || url || path || description || config || provider || hasUploadedEvidence);
    const hasMeaningfulDetail = Boolean(repository || url || path || description || config);
    const hasCodePath = Boolean(path && isCodeLikeFilePath(path));
    const hasDocumentArtifact = /\.(pdf|ppt|pptx|doc|docx|txt)$/i.test(path) || /\.(pdf|ppt|pptx|doc|docx|txt)$/i.test(url);
    const lineText = lineStart.trim() || lineEnd.trim() ? ` Lines ${lineStart || "?"}-${lineEnd || "?"}.` : "";
    const skillCategory = detectSkillCategory(skillName);

    function verifiedSummary(label: string) {
      return {
        verificationStatus: "Verified" as const,
        verificationSummary: `${label} usage likely found ✅`,
      };
    }

    if (!hasAnyEvidence) {
      return {
        verificationStatus: "Pending verification",
        verificationSummary: "Pending review until a repository link, evidence URL, file path, or description is added.",
      };
    }

    if (method === "upload_file") {
      if (source === "github code file") {
        if (uploadedName && isCodeLikeFilePath(uploadedName) && skillCategory === "code") {
          if (skill.includes("python") && uploadedName.endsWith(".py")) return verifiedSummary("Python");
          if ((skill.includes("javascript") || skill.includes("typescript") || skill.includes("react") || skill.includes("node")) && /\.(js|jsx|ts|tsx|mjs|cjs)$/.test(uploadedName))
            return verifiedSummary("JavaScript/TypeScript");
          if (skill.includes("sql") && uploadedName.endsWith(".sql")) return verifiedSummary("SQL");
          if ((skill.includes("java") && uploadedName.endsWith(".java")) || (skill.includes("c++") && /\.(cpp|cc|cxx|hpp|h)$/.test(uploadedName)))
            return verifiedSummary(skill.includes("java") ? "Java" : "C++");
        }
        if (uploadedName && !isCodeLikeFilePath(uploadedName) && skillCategory === "code") {
          return {
            verificationStatus: "Skill usage not found",
            verificationSummary:
              "Skill usage not found in the provided file path. Please provide a file or link that clearly demonstrates this skill.",
          };
        }
        return {
          verificationStatus: "Pending verification",
          verificationSummary: "Uploaded evidence saved for recruiter review.",
        };
      }

      if (uploadedLooksLikeVideo) {
        return {
          verificationStatus: "Pending verification",
          verificationSummary: "Uploaded evidence saved for recruiter review.",
        };
      }

      if (uploadedLooksLikeImage || uploadedLooksLikePdf || uploadedMime || uploadedName) {
        return {
          verificationStatus: "Pending verification",
          verificationSummary: "Uploaded evidence saved for recruiter review.",
        };
      }
    }

    if (source === "github code file") {
      if (skill.includes("python") && path.endsWith(".py")) return verifiedSummary("Python");
      if ((skill.includes("javascript") || skill.includes("typescript") || skill.includes("react") || skill.includes("node")) && /\.(js|jsx|ts|tsx|mjs|cjs)$/.test(path))
        return verifiedSummary("JavaScript/TypeScript");
      if (skill.includes("sql") && path.endsWith(".sql")) return verifiedSummary("SQL");
      if ((skill.includes("java") && path.endsWith(".java")) || (skill.includes("c++") && /\.(cpp|cc|cxx|hpp|h)$/.test(path)))
        return verifiedSummary(skill.includes("java") ? "Java" : "C++");
      if (skillCategory === "cloud" && /\.(tf|yml|yaml|sh|json)$/.test(path)) return verifiedSummary("Cloud");
      if (skillCategory === "data" && /\.(sql|ipynb|csv|xlsx|xls|json)$/.test(path)) return verifiedSummary("Data");
      if (skillCategory === "ai" && /\.(py|ipynb|json|yml|yaml)$/.test(path)) return verifiedSummary("AI/ML");

      if (hasDocumentArtifact) {
        return {
          verificationStatus: "Skill usage not found",
          verificationSummary:
            "Skill usage not found in the provided file path. Please provide a file or link that clearly demonstrates this skill.",
        };
      }

      if (hasCodePath || repository) {
        return {
          verificationStatus: "Needs review",
          verificationSummary: `Code file recorded.${lineText} Please confirm the file path and lines clearly support this skill.`,
        };
      }
    }

    if (source === "github repository") {
      return {
        verificationStatus: "Pending verification",
        verificationSummary: hasMeaningfulDetail
          ? "Repository recorded. VeriBridge will verify the supporting files later."
          : "Pending review until repository details are added.",
      };
    }

    if (source === "cloud deployment proof") {
      return {
        verificationStatus: "Pending verification",
        verificationSummary:
          "Cloud proof recorded. VeriBridge will verify deployment, config, and infrastructure evidence later.",
      };
    }

    if (source === "certificate") {
      return {
        verificationStatus: "Pending verification",
        verificationSummary: "Certificate recorded. VeriBridge will verify issuer details later.",
      };
    }

    if (source === "architecture diagram" || source === "project report" || source === "presentation / slides" || source === "dashboard / analytics report") {
      return {
        verificationStatus: "Pending verification",
        verificationSummary: "Supporting evidence recorded. VeriBridge will verify this artifact later.",
      };
    }

    if (source === "notebook / experiment") {
      if (path && isCodeLikeFilePath(path) && skillCategory !== "soft") {
        return {
          verificationStatus: "Needs review",
          verificationSummary: `Notebook recorded.${lineText} Add a clear notebook or code path if you want line-level verification later.`,
        };
      }
      return {
        verificationStatus: "Pending verification",
        verificationSummary: "Notebook or experiment recorded. VeriBridge will verify this artifact later.",
      };
    }

    if (source === "team / leadership evidence") {
      return {
        verificationStatus: "Pending verification",
        verificationSummary: "Team or leadership evidence recorded. VeriBridge will verify outcomes later.",
      };
    }

  if (source === "deployed app / live demo") {
    return {
      verificationStatus: "Pending verification",
      verificationSummary: "Live demo recorded. VeriBridge will verify the deployed proof later.",
    };
  }

  if (source === "linkedin post") {
    return {
      verificationStatus: "Pending verification",
      verificationSummary: "LinkedIn post recorded for recruiter review.",
    };
  }

  if (source === "coursework project" || source === "portfolio link" || source === "other") {
      return {
        verificationStatus: hasMeaningfulDetail ? "Pending verification" : "Pending verification",
        verificationSummary: hasMeaningfulDetail
          ? "Evidence recorded. VeriBridge will verify this proof later."
          : "Pending review until a proof URL or description is added.",
      };
    }

    if (skillCategory === "code" && hasDocumentArtifact) {
      return {
        verificationStatus: "Skill usage not found",
        verificationSummary:
          "Skill usage not found in the provided file path. Please provide a file or link that clearly demonstrates this skill.",
      };
    }

    return {
      verificationStatus: hasMeaningfulDetail ? "Pending verification" : "Pending verification",
      verificationSummary: hasMeaningfulDetail
        ? "Proof recorded. VeriBridge will verify this evidence later."
        : "Pending review until a repository link, evidence URL, file path, or description is added.",
    };
  }

  function addSelectedSkill(skill: string) {
    const trimmed = skill.trim();
    if (!trimmed) return;
    if (!form.selectedSkills.includes(trimmed)) {
      update("selectedSkills", [...form.selectedSkills, trimmed]);
    }
    update("customSkill", "");
  }

  function removeSelectedSkill(skill: string) {
    const nextSkills = form.selectedSkills.filter((item) => item !== skill);
    update("selectedSkills", nextSkills);
    update("proofSkill", form.proofSkill === skill ? nextSkills[0] ?? "" : form.proofSkill);
  }

  function addProofEvidence() {
    const skill = form.proofSkill.trim();
    if (!skill || !form.selectedSkills.includes(skill)) return;

    const sourceType = form.proofEvidenceType.trim();
    if (!sourceType) return;
    const evidenceAccessMethod = form.proofEvidenceAccessMethod === "upload_file" ? "upload_file" : "public_link";
    if (evidenceAccessMethod === "upload_file" && !form.proofUploadedFileName.trim()) return;
    const isRecruiterVisible = Boolean(form.proofIsRecruiterVisible);
    const requiresApproval = isRecruiterVisible ? Boolean(form.proofRequiresApproval) : false;
    const repositoryUrl = form.proofRepositoryUrl.trim();
    const evidenceUrl = form.proofEvidenceUrl.trim();
    const linkedInPostUrl = form.proofLinkedInPostUrl.trim();
    const relatedProjectUrl = form.proofRelatedProjectUrl.trim();
    const keyFiles = form.proofKeyFiles.trim();
    const cloudProvider = form.proofCloudProvider.trim();
    const configFile = form.proofConfigFile.trim();
    const diagramUrl = form.proofDiagramUrl.trim();
    const certificateIssuer = form.proofCertificateIssuer.trim();
    const completionDate = form.proofCompletionDate.trim();
    const roleTitle = form.proofRoleTitle.trim();
    const toolUsed = form.proofToolUsed.trim();
    const dataset = form.proofDataset.trim();
    const metrics = form.proofMetrics.trim();
    const filePath = form.proofFilePath.trim();
    const lineStart = form.proofLineStart.trim();
    const lineEnd = form.proofLineEnd.trim();
    const evidenceDescription = form.proofEvidenceDescription.trim();
    const { verificationStatus, verificationSummary } = deriveProofVerification(
      skill,
      sourceType,
      evidenceAccessMethod,
      repositoryUrl,
      evidenceUrl,
      filePath,
      lineStart,
      lineEnd,
      evidenceDescription,
      cloudProvider,
      configFile,
      form.proofUploadedFileName,
      form.proofUploadedFileType
    );

    setForm((prev) => ({
      ...prev,
      proofEvidence: [
        ...prev.proofEvidence,
        {
          skill,
          sourceType,
          evidenceAccessMethod,
          isRecruiterVisible,
          requiresApproval,
          evidenceUrl,
          repositoryUrl,
          linkedInPostUrl,
          relatedProjectUrl,
          keyFiles,
          filePath,
          startLine: lineStart,
          endLine: lineEnd,
          description: evidenceDescription,
          evidenceTitle: form.proofEvidenceTitle.trim(),
          visibilityNote: form.proofVisibilityNote.trim(),
          cloudProvider,
          configFile,
          diagramUrl,
          certificateIssuer,
          completionDate,
          roleTitle,
          toolUsed,
          dataset,
          metrics,
          exactCodeLocation: prev.proofExactCodeLocation,
          verificationStatus,
          verificationSummary,
          uploadedFileName: form.proofUploadedFileName.trim(),
          uploadedFileType: form.proofUploadedFileType.trim(),
          uploadedFileSize: form.proofUploadedFileSize.trim(),
          uploadedFileUrl: form.proofUploadedFileUrl.trim(),
          uploadedFileId: form.proofUploadedFileId.trim(),
          skill_name: skill,
          evidence_type: sourceType,
          evidence_access_method: evidenceAccessMethod,
          evidence_url: evidenceUrl || repositoryUrl || linkedInPostUrl || diagramUrl,
          evidence_title: form.proofEvidenceTitle.trim(),
          visibility_note: form.proofVisibilityNote.trim(),
          is_recruiter_visible: isRecruiterVisible,
          requires_approval: requiresApproval,
          uploaded_file_name: form.proofUploadedFileName.trim(),
          uploaded_file_type: form.proofUploadedFileType.trim(),
          uploaded_file_size: form.proofUploadedFileSize.trim(),
          uploaded_file_url: form.proofUploadedFileUrl.trim(),
          uploaded_file_id: form.proofUploadedFileId.trim(),
          related_project_url: relatedProjectUrl,
          file_path: filePath,
          line_start: lineStart,
          line_end: lineEnd,
          evidence_description: evidenceDescription,
          verification_status: verificationStatus,
          verification_summary: verificationSummary,
        },
      ],
      proofRepositoryUrl: "",
      proofEvidenceUrl: "",
      proofLinkedInPostUrl: "",
      proofRelatedProjectUrl: "",
      proofKeyFiles: "",
      proofCloudProvider: "",
      proofConfigFile: "",
      proofDiagramUrl: "",
      proofCertificateIssuer: "",
      proofCompletionDate: "",
      proofRoleTitle: "",
      proofToolUsed: "",
      proofDataset: "",
      proofMetrics: "",
      proofFilePath: "",
      proofLineStart: "",
      proofLineEnd: "",
      proofExactCodeLocation: false,
      proofEvidenceDescription: "",
      proofEvidenceTitle: "",
      proofVisibilityNote: "",
      proofIsRecruiterVisible: false,
      proofRequiresApproval: false,
      proofEvidenceAccessMethod: "public_link",
      proofUploadedFileName: "",
      proofUploadedFileType: "",
      proofUploadedFileSize: "",
      proofUploadedFileUrl: "",
      proofUploadedFileId: "",
      proofEvidenceType: "",
      proofSkill: prev.selectedSkills.includes(skill) ? skill : prev.selectedSkills[0] ?? skill,
    }));
  }

  function removeProofEvidence(index: number) {
    setForm((prev) => ({
      ...prev,
      proofEvidence: prev.proofEvidence.filter((_, currentIndex) => currentIndex !== index),
    }));
  }

  useEffect(() => {
    setForm((prev) => {
      if (prev.proofSkill && prev.selectedSkills.includes(prev.proofSkill)) return prev;
      const fallbackSkill = prev.selectedSkills[0] ?? "";
      if (fallbackSkill === prev.proofSkill) return prev;
      return { ...prev, proofSkill: fallbackSkill };
    });
  }, [form.selectedSkills]);

  function complete() {
    window.localStorage.setItem("veribridge:onboarding-completed", "true");
    router.push("/dashboard");
    router.refresh();
  }

  const shellStyle = isSignup
    ? {
        minHeight: "100vh",
        background:
          "radial-gradient(900px 480px at 15% 0%, rgba(79,70,229,.13), transparent 60%), radial-gradient(700px 420px at 85% 10%, rgba(16,185,129,.10), transparent 60%), var(--bg)",
        padding: "28px 18px 48px",
      }
    : { display: "grid", gap: 20 };

  const innerStyle = isSignup
    ? { maxWidth: 980, margin: "0 auto", display: "grid", gap: 18 }
    : { display: "grid", gap: 18 };

  return (
    <div style={shellStyle}>
      <div style={innerStyle}>
        <header className="vb-card-lg" style={{ padding: isSignup ? 30 : 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 18, alignItems: "flex-start" }}>
            <div>
              <div className="vb-eyebrow">VeriBridge Career Graph</div>
              <h1 style={{ margin: "8px 0 8px", fontSize: isSignup ? 38 : 34, letterSpacing: "-0.035em" }}>
                {isSignup ? "Set up your Career Graph" : "Career Preferences"}
              </h1>
              <p style={{ margin: 0, color: "var(--muted)", maxWidth: 760, lineHeight: 1.65 }}>
                {isSignup
                  ? "Choose from guided options so VeriBridge can shape your target roles, locations, Compensation Fit, and Opportunity & Salary Heatmap before you reach the dashboard."
                  : "Update your Career Graph. You can revise your target roles, locations, salary expectations, and work authorization anytime."}
              </p>
              <p style={{ margin: "10px 0 0", color: "var(--ink-2)", fontSize: 13, fontWeight: 650 }}>
                You can update these preferences anytime from your dashboard.
              </p>
            </div>
            {isSignup && (
              <div className="vb-mono" style={{ color: "var(--muted)", fontSize: 12, whiteSpace: "nowrap" }}>
                Step {step + 1} of {steps.length}
              </div>
            )}
          </div>
        </header>

        <section className="vb-card" style={{ padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 14, alignItems: "center", marginBottom: 12 }}>
            <strong style={{ fontSize: 13 }}>Step {step + 1} of {steps.length}</strong>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>{title}</span>
          </div>
          <div style={{ height: 8, background: "var(--bg-2)", borderRadius: 999, overflow: "hidden" }}>
            <div style={{ width: `${progress}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg,var(--indigo),var(--emerald))", transition: "width 180ms ease" }} />
          </div>
        </section>

        <section className="vb-card-lg" style={{ padding: isSignup ? 32 : 28 }}>
          <div className="vb-eyebrow">{isSignup ? "Focused onboarding" : "Preferences editor"}</div>
          <h2 style={{ margin: "8px 0 22px", fontSize: 27 }}>{title}</h2>
          {renderStep(
            step,
            form,
            update,
            toggleList,
            derivedCareerFields,
            roleSuggestions,
            industrySuggestions,
            skillSuggestions,
            proofSkillHint,
            addSelectedSkill,
            removeSelectedSkill,
            addProofEvidence,
            removeProofEvidence
          )}

          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 28, gap: 12 }}>
            <button
              type="button"
              onClick={() => setStep(Math.max(0, step - 1))}
              disabled={step === 0}
              style={{ border: "1px solid var(--line)", borderRadius: 11, background: "#fff", padding: "12px 16px", color: step === 0 ? "var(--muted)" : "var(--ink)", fontWeight: 700 }}
            >
              Back
            </button>
            <button
              type="button"
              onClick={() => (step === steps.length - 1 ? complete() : setStep(step + 1))}
              style={{ border: 0, borderRadius: 11, background: "var(--ink)", color: "#fff", padding: "12px 18px", fontWeight: 800 }}
            >
              {step === steps.length - 1 ? (isSignup ? "Complete onboarding" : "Save preferences") : "Continue"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function renderStep(
  step: number,
  form: FormState,
  update: (name: keyof FormState, value: string | boolean | string[]) => void,
  toggleList: (name: keyof FormState, option: string) => void,
  derivedCareerFields: string[],
  roleSuggestions: string[],
  industrySuggestions: string[],
  skillSuggestions: string[],
  proofSkillHint: string,
  addSelectedSkill: (skill: string) => void,
  removeSelectedSkill: (skill: string) => void,
  addProofEvidence: () => void,
  removeProofEvidence: (index: number) => void
) {
  if (step === 0) {
    return (
      <div style={{ display: "grid", gap: 16 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
          <SearchableDropdown label="University country" name="universityCountry" placeholder="Search country" value={form.universityCountry} options={countryOptions} onChange={update} />
          <SelectDropdown label="Degree level" name="degreeLevel" value={form.degreeLevel} options={degreeOptions} onChange={update} />
          <SearchableDropdown label="Major / field of study" name="major" placeholder="Search major or enter your field" value={form.major} options={majorOptions} onChange={update} allowCustom />
          <TextField label="Graduation year" name="graduationYear" placeholder="2027" type="number" value={form.graduationYear} onChange={update} />
        </div>
        {form.major === "Other" && (
          <TextField label="Custom major / field" name="customMajor" placeholder="Enter your field of study" value={form.customMajor} onChange={update} />
        )}
      </div>
    );
  }

  if (step === 1) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <div style={{ border: "1px solid var(--line)", borderRadius: 16, background: "#fff", padding: 16 }}>
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
            Based on your major, VeriBridge suggests common roles companies hire for globally. Search across all roles or add your own.
          </p>
          {derivedCareerFields.length > 0 ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
              {derivedCareerFields.map((field) => (
                <span
                  key={field}
                  style={{
                    border: "1px solid var(--line)",
                    borderRadius: 999,
                    background: "var(--bg)",
                    color: "var(--ink-2)",
                    padding: "6px 9px",
                    fontSize: 11,
                    fontWeight: 750,
                  }}
                >
                  {field}
                </span>
              ))}
            </div>
          ) : (
            <p style={{ margin: "10px 0 0", color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
              Pick a major in Step 1 to see major-aware role and industry suggestions here.
            </p>
          )}
        </div>
        <MultiSelectDropdown
          label="Target roles"
          options={[
            ...roleSuggestions,
            ...form.targetRoles.filter((role) => !roleSuggestions.includes(role)),
          ]}
          searchOptions={ALL_ROLE_OPTIONS}
          selected={form.targetRoles}
          onToggle={(role) => toggleList("targetRoles", role)}
          allowCustom
        />
        {form.targetRoles.length === 0 && (
          <p style={{ margin: "-4px 0 0", color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
            No target roles selected yet. Add the roles you want to apply for.
          </p>
        )}
        <MultiSelectDropdown
          label="Target industries"
          options={industrySuggestions}
          searchOptions={INDUSTRY_OPTIONS}
          selected={form.targetIndustries}
          onToggle={(industry) => toggleList("targetIndustries", industry)}
          allowCustom
        />
        {form.targetIndustries.length === 0 && (
          <p style={{ margin: "-4px 0 0", color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
            No target industries selected yet. Add the industries you are interested in.
          </p>
        )}
      </div>
    );
  }

  if (step === 2) {
    const sourceType = form.proofEvidenceType.trim();
    const accessMethod = form.proofEvidenceAccessMethod === "upload_file" ? "upload_file" : "public_link";
    const proofSkillHelper =
      form.selectedSkills.length === 0 ? "Add a skill to your inventory before attaching proof." : proofSkillHint;
    const hasProofDescription = form.proofEvidenceDescription.trim().length > 0;
    const hasProofTitle = form.proofEvidenceTitle.trim().length > 0;
    const canAddProof = Boolean(
      form.proofSkill &&
        form.selectedSkills.includes(form.proofSkill) &&
        sourceType &&
        (accessMethod === "public_link" || form.proofUploadedFileName) &&
        (accessMethod === "public_link" || hasProofTitle || hasProofDescription)
    );

    return (
      <div style={{ display: "grid", gap: 18 }}>
        <section style={{ border: "1px solid var(--line)", borderRadius: 18, background: "#fff", padding: 18, display: "grid", gap: 14 }}>
          <div>
            <div className="vb-eyebrow">Skills to prove</div>
            <h3 style={{ margin: "6px 0 6px", fontSize: 20 }}>Build your full skill inventory</h3>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
              Add every skill you want VeriBridge to use for resume tailoring, recruiter proof, job matching, and skill-gap analysis. You can add proof now or later.
            </p>
            <p style={{ margin: "8px 0 0", color: "var(--ink-2)", fontSize: 12, fontWeight: 700 }}>
              {form.selectedSkills.length} skills in inventory · {form.proofEvidence.length} proof items added
            </p>
          </div>
          <MultiSelectDropdown
            label="Suggested skills"
            options={skillSuggestions}
            searchOptions={ALL_SKILL_OPTIONS}
            selected={form.selectedSkills}
            onToggle={(skill) => toggleList("skills", skill)}
            allowCustom
            showSelectedChips={false}
          />
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "end" }}>
            <TextField
              label="Add a skill"
              name="customSkill"
              placeholder="Example: Python, FastAPI, AWS, LightGBM, RAG"
              value={form.customSkill}
              onChange={update}
              helper="Search the full global skill library or add your own skill."
            />
            <button
              type="button"
              onClick={() => addSelectedSkill(form.customSkill)}
              style={{
                border: "1px solid var(--line)",
                borderRadius: 10,
                background: "#fff",
                padding: "12px 14px",
                fontWeight: 750,
                height: 46,
              }}
            >
              Add skill to inventory
            </button>
          </div>
          <div style={{ border: "1px solid var(--line)", borderRadius: 16, background: "var(--bg)", padding: 14, display: "grid", gap: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
              <strong style={{ fontSize: 13 }}>Your skill inventory</strong>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{form.selectedSkills.length} total</span>
            </div>
            {form.selectedSkills.length === 0 ? (
              <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
                No skills added yet. Start with your strongest technical, AI, data, cloud, or project skills.
              </p>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {form.selectedSkills.map((skill) => (
                  <button
                    key={skill}
                    type="button"
                    onClick={() => removeSelectedSkill(skill)}
                    style={{
                      border: "1px solid var(--ink)",
                      borderRadius: 999,
                      background: "var(--ink)",
                      color: "#fff",
                      padding: "8px 11px",
                      fontSize: 12,
                      fontWeight: 800,
                    }}
                  >
                    {skill} ×
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        <section style={{ border: "1px solid var(--line)", borderRadius: 18, background: "linear-gradient(135deg,#fff,#f8fafc)", padding: 18, display: "grid", gap: 16 }}>
          <div>
            <div className="vb-eyebrow">Proof evidence builder</div>
            <h3 style={{ margin: "6px 0 6px", fontSize: 20 }}>Attach exact proof to a skill</h3>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
              AI verification and line highlighting will be enabled after GitHub/file integration. For now, VeriBridge records exact evidence locations and performs basic validation.
            </p>
            <p style={{ margin: "8px 0 0", color: "var(--ink-2)", fontSize: 12, fontWeight: 700 }}>{proofSkillHint}</p>
            {form.selectedSkills.length === 0 && (
              <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
                Add a skill to your inventory before attaching proof.
              </p>
            )}
          </div>

          <div style={{ display: "grid", gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 750, color: "var(--ink)" }}>Evidence access method</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
              {PROOF_EVIDENCE_ACCESS_METHODS.map((method) => {
                const active = accessMethod === (method === "Upload file" ? "upload_file" : "public_link");
                return (
                  <button
                    key={method}
                    type="button"
                    aria-pressed={active}
                    onClick={() => update("proofEvidenceAccessMethod", method === "Upload file" ? "upload_file" : "public_link")}
                    style={{
                      minHeight: 48,
                      border: active ? "1px solid var(--ink)" : "1px solid var(--line)",
                      borderRadius: 12,
                      background: active ? "var(--ink)" : "#fff",
                      color: active ? "#fff" : "var(--ink)",
                      fontWeight: 800,
                      textAlign: "left",
                      padding: "10px 12px",
                    }}
                  >
                    {method}
                  </button>
                );
              })}
            </div>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
              Public links stay visible as before. Private uploads are only shown to authorized reviewers/recruiters based on your sharing settings.
            </p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <SearchableDropdown
              label="Choose skill to attach proof"
              name="proofSkill"
              placeholder={form.selectedSkills.length === 0 ? "Add a skill to your inventory first" : "Choose from your skill inventory"}
              value={form.proofSkill}
              options={form.selectedSkills}
              onChange={update}
              disabled={form.selectedSkills.length === 0}
              helper={proofSkillHelper}
            />
            <SearchableDropdown
              label="Evidence source type"
              name="proofEvidenceType"
              placeholder="Select a proof source"
              value={sourceType}
              options={[...PROOF_EVIDENCE_SOURCE_TYPES]}
              onChange={update}
              helper="Choose the artifact type that best fits the proof."
            />
          </div>

          {renderProofEvidenceFieldGroup(form, update)}

          <div style={{ display: "grid", gap: 12 }}>
            <button
              type="button"
              onClick={addProofEvidence}
              disabled={!canAddProof}
              style={{
                border: 0,
                borderRadius: 12,
                background: canAddProof ? "linear-gradient(135deg,var(--ink),#29304d)" : "var(--bg-2)",
                color: canAddProof ? "#fff" : "var(--muted)",
                padding: "12px 16px",
                fontWeight: 800,
                justifySelf: "start",
                cursor: canAddProof ? "pointer" : "not-allowed",
              }}
            >
              Add proof evidence
            </button>
            <p style={{ margin: 0, color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
              Skill proof items are stored with the selected skill, evidence source, URLs, file path, line range, evidence description, verification status, and verification summary for future recruiter viewing.
            </p>
          </div>

          {form.proofEvidence.length === 0 ? (
            <div style={{ border: "1px dashed var(--line-2)", borderRadius: 14, background: "var(--bg)", padding: 14, color: "var(--muted)", fontSize: 13, lineHeight: 1.6 }}>
              No proof evidence added yet. Attach proof such as GitHub, LinkedIn, certificates, reports, demos, or dashboards.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 14 }}>
              <h4 style={{ margin: 0, fontSize: 16 }}>Proof evidence cards</h4>
              <div style={{ display: "grid", gap: 12 }}>
                {form.proofEvidence.map((entry, index) => (
                  <ProofEvidenceCard
                    key={`${entry.skill ?? entry.skill_name ?? index}`}
                    entry={entry}
                    viewerRole="student_owner"
                    onRemove={() => removeProofEvidence(index)}
                  />
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    );
  }

  if (step === 3) {
    return (
      <LocationPreferenceSelector
        selected={form.targetLocations}
        workModes={form.workModes}
        relocate={form.relocate}
        globalSearch={form.globalSearch}
        onToggleLocation={(location) => toggleList("targetLocations", location)}
        onToggleWorkMode={(mode) => toggleList("workModes", mode)}
        onToggleRelocate={() => update("relocate", !form.relocate)}
        onToggleGlobalSearch={() => update("globalSearch", !form.globalSearch)}
      />
    );
  }

  if (step === 4) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <SearchableDropdown label="Authorization type" name="authorizationType" placeholder="Search or enter authorization type" value={form.authorizationType} options={authorizationTypes} onChange={update} allowCustom />
        <MultiSelectDropdown label="Work authorization countries" options={countryOptions} selected={form.authorizationCountries} onToggle={(country) => toggleList("authorizationCountries", country)} allowCustom />
        <OptionDropdown label="Sponsorship needed" options={sponsorshipOptions} selected={[form.sponsorshipNeeded]} onToggle={(value) => update("sponsorshipNeeded", value)} multi={false} />
        <TextField label="Custom explanation" name="authNotes" placeholder="Only show to recruiters when I opt in" value={form.authNotes} onChange={update} />
      </div>
    );
  }

  if (step === 5) {
    return (
      <div style={{ display: "grid", gap: 16 }}>
        {( !form.salaryMin && !form.salaryMax && !form.minimumSalary && !form.currency && !form.salaryPeriod && !form.negotiable ) && (
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12, lineHeight: 1.55 }}>
            No compensation preferences selected yet. Add your preferred salary range, currency, and negotiation preferences when ready.
          </p>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
          <TextField label="Expected salary min" name="salaryMin" placeholder="70000" type="number" value={form.salaryMin} onChange={update} />
          <TextField label="Expected salary max" name="salaryMax" placeholder="95000" type="number" value={form.salaryMax} onChange={update} />
          <TextField label="Minimum acceptable salary" name="minimumSalary" placeholder="65000" type="number" value={form.minimumSalary} onChange={update} />
          <SearchableDropdown label="Currency" name="currency" placeholder="Search or enter currency" value={form.currency} options={currencyOptions} onChange={update} allowCustom />
          <SelectDropdown label="Salary period" name="salaryPeriod" value={form.salaryPeriod} options={salaryPeriods} onChange={update} />
          <SelectDropdown label="Open to negotiation" name="negotiable" value={form.negotiable} options={negotiationOptions} onChange={update} />
        </div>
        {(form.currency === "Other" || !currencyOptions.includes(form.currency)) && (
          <TextField label="Custom currency" name="customCurrency" placeholder="Example: JPY" value={form.customCurrency} onChange={update} />
        )}
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 13, lineHeight: 1.55 }}>
          This helps VeriBridge compare your expectations with market ranges and recruiter budgets. You can update this anytime.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div style={{ border: "1px solid var(--line)", borderRadius: 18, padding: 20, background: "linear-gradient(135deg,#fff,#f8fafc)" }}>
        <h3 style={{ margin: 0, fontSize: 21 }}>Opportunity & Salary Heatmap</h3>
        <p style={{ color: "var(--muted)", lineHeight: 1.65 }}>
          You selected Massachusetts, but California, Remote Worldwide, and Toronto currently show stronger market signals for your selected roles. Would you like to expand your search?
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
          {["Keep selected locations", "Add recommended regions", "Compare salary-adjusted value", "Show remote opportunities", "Show only work-authorization compatible regions"].map((item, index) => (
            <button key={`${item}-${index}`} type="button" className="vb-btn-lift" style={{ border: "1px solid var(--line)", borderRadius: 11, padding: "10px 12px", background: item === "Add recommended regions" ? "var(--ink)" : "#fff", color: item === "Add recommended regions" ? "#fff" : "var(--ink)", fontWeight: 700 }}>
              {item}
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 14 }}>
        {recommendations.map(([location, roles, salary, competition, remote, auth, fit, score]) => (
          <article key={location} className="vb-card-hover" style={{ position: "relative", overflow: "hidden", border: "1px solid var(--line)", borderRadius: 16, padding: 18, background: "#fff" }}>
            <div style={{ position: "absolute", inset: "auto 0 0", height: 5, background: "linear-gradient(90deg,var(--indigo),var(--emerald))", width: `${score}%` }} />
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <h3 style={{ margin: 0, fontSize: 17 }}>{location}</h3>
              <strong className="vb-mono">{score}</strong>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
              {[
                ["Open roles", roles],
                ["Salary range", salary],
                ["Competition", competition],
                ["Remote availability", remote],
                ["Work authorization fit", auth],
                ["Compensation fit", fit],
              ].map(([label, value], index) => (
                <span key={`${label}-${index}`} style={{ border: "1px solid var(--line)", borderRadius: 999, background: "var(--bg-2)", padding: "6px 8px", fontSize: 11, fontWeight: 700 }}>
                  {label}: {value}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
      <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
        MVP market data is sample/mock until Adzuna, JSearch, or BLS providers are connected.
      </p>
    </div>
  );
}
