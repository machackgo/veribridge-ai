"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  ALL_ROLE_OPTIONS,
  INDUSTRY_OPTIONS,
  getSuggestedIndustriesForMajor,
  getSuggestedRolesForMajor,
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
  evidenceType: string;
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
};

const steps = [
  "Academic Profile",
  "Target Roles & Industries",
  "Skills & Evidence",
  "Global Locations & Work Mode",
  "Work Authorization",
  "Compensation Preferences",
  "Opportunity & Salary Heatmap Review",
];

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

const skillOptions = [
  "Python",
  "SQL",
  "Excel",
  "Financial Modeling",
  "CAD",
  "SolidWorks",
  "AutoCAD",
  "Lab Techniques",
  "Research Writing",
  "Public Speaking",
  "Project Management",
  "Market Research",
  "Data Analysis",
  "Machine Learning",
  "Cloud",
  "Docker",
  "Figma",
  "UX Research",
  "Policy Analysis",
  "Teaching",
  "Clinical Research",
  "Supply Chain Analytics",
  "Other",
];

const evidenceOptions = [
  "GitHub repo",
  "Deployed app",
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

function matchesOption(option: string, searchTerm: string) {
  const normalized = option.toLowerCase();
  return (
    normalized.includes(searchTerm) ||
    (searchTerm.length > 1 && searchTerm.length <= 2 && normalized.startsWith(searchTerm[0]))
  );
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
          <span>{value}</span>
          <span aria-hidden="true" style={{ color: "var(--muted)" }}>⌄</span>
        </button>
        {open && (
          <DropdownPanel>
            {options.map((option) => (
              <DropdownOption
                key={option}
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
}: {
  label: string;
  name: keyof FormState;
  value: string;
  options: string[];
  onChange: (name: keyof FormState, value: string) => void;
  placeholder: string;
  allowCustom?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState(value);
  const ref = useRef<HTMLDivElement | null>(null);
  const searchTerm = query.trim().toLowerCase();
  const shouldFilter = searchTerm.length > 0 && query !== value;
  const filtered = shouldFilter
    ? options.filter((option) => matchesOption(option, searchTerm))
    : options;
  const visibleOptions = shouldFilter ? filtered : options;
  const customValue = query.trim();
  const canUseCustom =
    allowCustom &&
    customValue.length > 0 &&
    !options.some((option) => option.toLowerCase() === customValue.toLowerCase());

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
          {visibleOptions.map((option) => (
              <DropdownOption
                key={option}
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
}: {
  label: string;
  options: string[];
  searchOptions?: string[];
  selected: string[];
  onToggle: (option: string) => void;
  allowCustom?: boolean;
  maxDefaultOptions?: number;
  maxSearchOptions?: number;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement | null>(null);
  const searchTerm = query.trim().toLowerCase();
  const searchableOptions = searchOptions ?? options;
  const filtered = searchableOptions.filter((option) => matchesOption(option, searchTerm));
  const visibleOptions = (searchTerm ? filtered : options).slice(0, searchTerm ? maxSearchOptions : maxDefaultOptions);
  const customValue = query.trim();
  const canUseCustom =
    allowCustom &&
    customValue.length > 0 &&
    !searchableOptions.some((option) => option.toLowerCase() === customValue.toLowerCase()) &&
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
        {open && (
          <DropdownPanel>
            {visibleOptions.map((option) => (
              <DropdownOption
                key={option}
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
      {selected.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
          {selected.map((option) => (
            <button
              key={option}
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
        {selected.length > 0 && (
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
        {options.map((option) => {
          const active = selected.includes(option);
          return (
            <button
              key={option}
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
        {options.map((option) => {
          const active = selected.includes(option);
          return (
            <button
              key={option}
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

function addCustomValue(value: string, selected: string[], onToggle: (option: string) => void) {
  const trimmed = value.trim();
  if (trimmed && !selected.includes(trimmed)) onToggle(trimmed);
}

export function OnboardingFlow({ mode = "signup" }: { mode?: Mode }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<FormState>({
    universityCountry: "United States",
    degreeLevel: "Bachelor's",
    major: "Business Administration",
    customMajor: "",
    graduationYear: "2027",
    targetRoles: ["Business Analyst"],
    customRole: "",
    targetIndustries: ["Healthcare", "Consulting"],
    skills: ["Excel", "Project Management"],
    evidenceType: "Coursework project",
    customSkill: "",
    targetLocations: ["Remote Worldwide"],
    customLocation: "",
    workModes: ["Hybrid", "Remote worldwide"],
    globalSearch: true,
    relocate: true,
    authorizationType: "Student Visa",
    authorizationCountries: ["United States"],
    sponsorshipNeeded: "Later",
    authNotes: "",
    salaryMin: "70000",
    salaryMax: "95000",
    minimumSalary: "65000",
    currency: "USD",
    customCurrency: "",
    salaryPeriod: "Yearly",
    negotiable: "Yes",
  });

  const derivedCareerFields = useMemo(
    () => careerFieldsByMajor[form.major] ?? ["Business & Management"],
    [form.major]
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

  function update(name: keyof FormState, value: string | boolean | string[]) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  function toggleList(name: keyof FormState, option: string) {
    const current = form[name];
    const selected = Array.isArray(current) ? current : [];
    update(name, selected.includes(option) ? selected.filter((item) => item !== option) : [...selected, option]);
  }

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
          {renderStep(step, form, update, toggleList, derivedCareerFields, roleSuggestions, industrySuggestions)}

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
  industrySuggestions: string[]
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
        <MultiSelectDropdown
          label="Target industries"
          options={industrySuggestions}
          searchOptions={INDUSTRY_OPTIONS}
          selected={form.targetIndustries}
          onToggle={(industry) => toggleList("targetIndustries", industry)}
          allowCustom
        />
      </div>
    );
  }

  if (step === 2) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <MultiSelectDropdown label="Suggested skills" options={skillOptions} selected={form.skills} onToggle={(skill) => toggleList("skills", skill)} allowCustom />
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "end" }}>
          <TextField label="Add custom skill" name="customSkill" placeholder="Example: Wet lab microscopy" value={form.customSkill} onChange={update} />
          <button type="button" onClick={() => addCustomValue(form.customSkill, form.skills, (skill) => toggleList("skills", skill))} style={{ border: "1px solid var(--line)", borderRadius: 10, background: "#fff", padding: "12px 14px", fontWeight: 750 }}>
            Add skill
          </button>
        </div>
        <SearchableDropdown label="Evidence type" name="evidenceType" placeholder="Search or enter evidence type" value={form.evidenceType} options={evidenceOptions} onChange={update} allowCustom />
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
          {["Keep selected locations", "Add recommended regions", "Compare salary-adjusted value", "Show remote opportunities", "Show only work-authorization compatible regions"].map((item) => (
            <button key={item} type="button" className="vb-btn-lift" style={{ border: "1px solid var(--line)", borderRadius: 11, padding: "10px 12px", background: item === "Add recommended regions" ? "var(--ink)" : "#fff", color: item === "Add recommended regions" ? "#fff" : "var(--ink)", fontWeight: 700 }}>
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
              ].map(([label, value]) => (
                <span key={label} style={{ border: "1px solid var(--line)", borderRadius: 999, background: "var(--bg-2)", padding: "6px 8px", fontSize: 11, fontWeight: 700 }}>
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
