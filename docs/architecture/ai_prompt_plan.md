# VeriBridge AI Student MVP Prompt Plan

## Scope

This document defines the AI prompt strategy for the VeriBridge AI student MVP. It covers resume parsing, job description parsing, match analysis, student-safe resume tailoring, cover letter drafting, project suggestions, and hallucination safety checks.

The critical product rule is absolute:

> The AI must never invent fake experience, fake projects, fake skills, fake education, fake companies, fake certifications, or fake work history.

The AI may rephrase, organize, summarize, and explain information supplied by the student or sourced from the job description. It may suggest future learning projects only when clearly labeled as suggested future work, not past experience.

## Global Prompt Principles

All prompts must follow these shared principles:

- Treat the student's source profile and resume as the only source of truth for their actual experience.
- Treat the job description as the source of truth for employer requirements.
- Do not infer unstated credentials, certifications, degrees, employers, dates, tools, metrics, or accomplishments.
- Distinguish between verified facts, inferred fit, missing evidence, and recommended next actions.
- Return structured JSON only, with no markdown prose unless a schema field explicitly allows formatted text.
- Prefer conservative uncertainty over confident unsupported claims.
- Flag ambiguous or low-confidence extracted data instead of filling gaps.
- Require human review before any generated material is used in an application.

## Prompt 1: Resume Parsing

### Purpose

Extract structured student profile data from an uploaded resume. This prompt normalizes the resume into data the matching, tailoring, and safety systems can use.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["resume_text", "source_metadata"],
  "properties": {
    "resume_text": {
      "type": "string",
      "description": "Plain text extracted from the student's resume."
    },
    "source_metadata": {
      "type": "object",
      "required": ["file_name", "uploaded_at"],
      "properties": {
        "file_name": { "type": "string" },
        "uploaded_at": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": [
    "contact",
    "education",
    "experience",
    "projects",
    "skills",
    "certifications",
    "awards",
    "unknown_or_ambiguous_items",
    "safety_flags"
  ],
  "properties": {
    "contact": {
      "type": "object",
      "properties": {
        "name": { "type": ["string", "null"] },
        "email": { "type": ["string", "null"] },
        "phone": { "type": ["string", "null"] },
        "location": { "type": ["string", "null"] },
        "links": { "type": "array", "items": { "type": "string" } }
      }
    },
    "education": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["institution", "degree_or_program", "dates", "evidence"],
        "properties": {
          "institution": { "type": "string" },
          "degree_or_program": { "type": "string" },
          "dates": { "type": ["string", "null"] },
          "gpa": { "type": ["string", "null"] },
          "coursework": { "type": "array", "items": { "type": "string" } },
          "evidence": { "type": "string" }
        }
      }
    },
    "experience": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["organization", "role", "dates", "bullets", "evidence"],
        "properties": {
          "organization": { "type": "string" },
          "role": { "type": "string" },
          "dates": { "type": ["string", "null"] },
          "bullets": { "type": "array", "items": { "type": "string" } },
          "skills_observed": { "type": "array", "items": { "type": "string" } },
          "evidence": { "type": "string" }
        }
      }
    },
    "projects": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "description", "technologies", "evidence"],
        "properties": {
          "name": { "type": "string" },
          "description": { "type": "string" },
          "technologies": { "type": "array", "items": { "type": "string" } },
          "links": { "type": "array", "items": { "type": "string" } },
          "evidence": { "type": "string" }
        }
      }
    },
    "skills": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["skill", "evidence", "confidence"],
        "properties": {
          "skill": { "type": "string" },
          "evidence": { "type": "string" },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 }
        }
      }
    },
    "certifications": { "type": "array", "items": { "type": "string" } },
    "awards": { "type": "array", "items": { "type": "string" } },
    "unknown_or_ambiguous_items": { "type": "array", "items": { "type": "string" } },
    "safety_flags": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Safety Rules

- Extract only what appears in the resume text.
- Do not convert coursework into professional experience.
- Do not convert class projects into employment.
- Do not assume proficiency from a single mention unless the resume supports it.
- Preserve uncertainty in `unknown_or_ambiguous_items`.

### Example Response

```json
{
  "contact": {
    "name": "Avery Chen",
    "email": "avery@example.com",
    "phone": null,
    "location": "Austin, TX",
    "links": ["https://github.com/averychen"]
  },
  "education": [
    {
      "institution": "University of Texas at Austin",
      "degree_or_program": "B.S. Computer Science",
      "dates": "Expected May 2027",
      "gpa": "3.7",
      "coursework": ["Data Structures", "Databases"],
      "evidence": "B.S. Computer Science, Expected May 2027"
    }
  ],
  "experience": [],
  "projects": [
    {
      "name": "Campus Study Planner",
      "description": "Built a React app for scheduling study sessions.",
      "technologies": ["React", "Firebase"],
      "links": [],
      "evidence": "Campus Study Planner - React, Firebase"
    }
  ],
  "skills": [
    {
      "skill": "React",
      "evidence": "Campus Study Planner - React, Firebase",
      "confidence": 0.9
    }
  ],
  "certifications": [],
  "awards": [],
  "unknown_or_ambiguous_items": [],
  "safety_flags": []
}
```

### Evaluation Criteria

- Extracted facts must be traceable to exact resume text.
- No invented skills, dates, companies, certifications, or projects.
- Ambiguous data is flagged instead of completed.
- Skills confidence reflects evidence strength.
- Output validates against schema.

## Prompt 2: Job Description Parsing

### Purpose

Extract structured requirements, responsibilities, qualifications, and keywords from a job description.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["job_description_text", "source_metadata"],
  "properties": {
    "job_description_text": { "type": "string" },
    "source_metadata": {
      "type": "object",
      "required": ["source_url", "captured_at"],
      "properties": {
        "source_url": { "type": ["string", "null"] },
        "captured_at": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": [
    "job_title",
    "company",
    "location",
    "employment_type",
    "responsibilities",
    "required_qualifications",
    "preferred_qualifications",
    "skills",
    "keywords",
    "experience_level",
    "ambiguities"
  ],
  "properties": {
    "job_title": { "type": ["string", "null"] },
    "company": { "type": ["string", "null"] },
    "location": { "type": ["string", "null"] },
    "employment_type": { "type": ["string", "null"] },
    "responsibilities": { "type": "array", "items": { "type": "string" } },
    "required_qualifications": { "type": "array", "items": { "type": "string" } },
    "preferred_qualifications": { "type": "array", "items": { "type": "string" } },
    "skills": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "category", "importance"],
        "properties": {
          "name": { "type": "string" },
          "category": { "type": "string" },
          "importance": { "type": "string", "enum": ["required", "preferred", "mentioned"] }
        }
      }
    },
    "keywords": { "type": "array", "items": { "type": "string" } },
    "experience_level": { "type": ["string", "null"] },
    "ambiguities": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Safety Rules

- Extract only requirements present in the job description.
- Do not infer hidden requirements from company name or job title.
- Keep required and preferred qualifications separate.
- Preserve vague wording as ambiguity instead of strengthening it.

### Example Response

```json
{
  "job_title": "Software Engineering Intern",
  "company": "ExampleTech",
  "location": "Remote",
  "employment_type": "Internship",
  "responsibilities": ["Build and test frontend features", "Collaborate with product and design"],
  "required_qualifications": ["Currently pursuing a degree in Computer Science or related field", "Experience with JavaScript"],
  "preferred_qualifications": ["Experience with React", "Familiarity with REST APIs"],
  "skills": [
    { "name": "JavaScript", "category": "programming_language", "importance": "required" },
    { "name": "React", "category": "framework", "importance": "preferred" }
  ],
  "keywords": ["frontend", "testing", "collaboration"],
  "experience_level": "student internship",
  "ambiguities": []
}
```

### Evaluation Criteria

- Required and preferred qualifications are accurately separated.
- Extracted skills match job description language.
- No employer requirements are invented.
- Output validates against schema.

## Prompt 3: Match Score Explanation

### Purpose

Explain how well a student's verified profile matches a job description using evidence-based reasoning.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["parsed_resume", "parsed_job", "scoring_context"],
  "properties": {
    "parsed_resume": { "type": "object" },
    "parsed_job": { "type": "object" },
    "scoring_context": {
      "type": "object",
      "required": ["score"],
      "properties": {
        "score": { "type": "number", "minimum": 0, "maximum": 100 },
        "score_method_version": { "type": "string" }
      }
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": ["score", "summary", "strengths", "gaps", "evidence_map", "confidence", "student_next_steps"],
  "properties": {
    "score": { "type": "number", "minimum": 0, "maximum": 100 },
    "summary": { "type": "string" },
    "strengths": { "type": "array", "items": { "type": "string" } },
    "gaps": { "type": "array", "items": { "type": "string" } },
    "evidence_map": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["job_requirement", "resume_evidence", "match_status"],
        "properties": {
          "job_requirement": { "type": "string" },
          "resume_evidence": { "type": ["string", "null"] },
          "match_status": { "type": "string", "enum": ["matched", "partial", "missing"] }
        }
      }
    },
    "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
    "student_next_steps": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Safety Rules

- Explain the score; do not recalculate it unless explicitly asked.
- Only cite resume evidence that exists in parsed resume data.
- Mark missing evidence as missing.
- Do not encourage the student to claim missing qualifications.

### Example Response

```json
{
  "score": 72,
  "summary": "The student has a solid fit for a frontend internship because their resume shows React and JavaScript project experience, but there is limited evidence of testing or API integration.",
  "strengths": ["React appears in a completed project", "JavaScript is supported by project evidence"],
  "gaps": ["No explicit testing experience found", "REST API experience is not supported by resume evidence"],
  "evidence_map": [
    {
      "job_requirement": "Experience with JavaScript",
      "resume_evidence": "Campus Study Planner - React, Firebase",
      "match_status": "matched"
    },
    {
      "job_requirement": "Familiarity with REST APIs",
      "resume_evidence": null,
      "match_status": "missing"
    }
  ],
  "confidence": 0.84,
  "student_next_steps": ["Add verified testing experience if completed", "Build a small API project if interested in improving fit"]
}
```

### Evaluation Criteria

- Explanation aligns with score and evidence.
- Every strength maps to verified resume data.
- Missing qualifications remain clearly labeled as missing.
- Recommendations are ethical and action-oriented.

## Prompt 4: Missing Skills Analysis

### Purpose

Identify skills and qualifications required or preferred by the job that are not supported by the student's verified resume.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["parsed_resume", "parsed_job"],
  "properties": {
    "parsed_resume": { "type": "object" },
    "parsed_job": { "type": "object" }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": ["missing_required", "missing_preferred", "partial_matches", "learning_plan"],
  "properties": {
    "missing_required": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["skill_or_qualification", "why_missing", "importance"],
        "properties": {
          "skill_or_qualification": { "type": "string" },
          "why_missing": { "type": "string" },
          "importance": { "type": "string", "enum": ["required", "preferred"] }
        }
      }
    },
    "missing_preferred": { "type": "array", "items": { "type": "string" } },
    "partial_matches": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["job_skill", "student_evidence", "limitation"],
        "properties": {
          "job_skill": { "type": "string" },
          "student_evidence": { "type": "string" },
          "limitation": { "type": "string" }
        }
      }
    },
    "learning_plan": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["skill", "suggested_action", "resume_claim_allowed_now"],
        "properties": {
          "skill": { "type": "string" },
          "suggested_action": { "type": "string" },
          "resume_claim_allowed_now": { "type": "boolean" }
        }
      }
    }
  }
}
```

### Safety Rules

- A missing skill must not be included in generated resume bullets as existing experience.
- Future learning actions must be labeled as future actions.
- Do not imply the student has a skill because it is adjacent to another skill.
- If evidence is weak, mark it as partial.

### Example Response

```json
{
  "missing_required": [
    {
      "skill_or_qualification": "JavaScript",
      "why_missing": "The parsed resume lists React but does not explicitly list JavaScript.",
      "importance": "required"
    }
  ],
  "missing_preferred": ["REST APIs"],
  "partial_matches": [
    {
      "job_skill": "Frontend development",
      "student_evidence": "Campus Study Planner built with React",
      "limitation": "The resume does not describe testing, accessibility, or deployment."
    }
  ],
  "learning_plan": [
    {
      "skill": "REST APIs",
      "suggested_action": "Build a small project that fetches and displays data from a public API.",
      "resume_claim_allowed_now": false
    }
  ]
}
```

### Evaluation Criteria

- Missing skills are correctly distinguished from partial matches.
- Learning plan does not authorize unsupported resume claims.
- Required gaps are prioritized above preferred gaps.
- Output validates against schema.

## Prompt 5: Tailored Resume Bullet Generation

### Purpose

Generate revised resume bullets that better align verified student experience with a target job while preserving truthfulness.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["source_experience_or_project", "parsed_job", "constraints"],
  "properties": {
    "source_experience_or_project": {
      "type": "object",
      "description": "One verified resume experience or project entry."
    },
    "parsed_job": { "type": "object" },
    "constraints": {
      "type": "object",
      "properties": {
        "max_bullets": { "type": "integer", "minimum": 1, "maximum": 5 },
        "tone": { "type": "string", "enum": ["student", "professional", "concise"] },
        "must_preserve_facts": { "type": "boolean" }
      }
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": ["generated_bullets", "unsupported_claims_removed", "human_review_notes"],
  "properties": {
    "generated_bullets": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["bullet", "source_evidence", "targeted_keywords", "risk_level"],
        "properties": {
          "bullet": { "type": "string" },
          "source_evidence": { "type": "string" },
          "targeted_keywords": { "type": "array", "items": { "type": "string" } },
          "risk_level": { "type": "string", "enum": ["low", "medium", "high"] }
        }
      }
    },
    "unsupported_claims_removed": { "type": "array", "items": { "type": "string" } },
    "human_review_notes": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Safety Rules

- Do not add tools, metrics, outcomes, users, team size, revenue, grades, awards, dates, or impact not present in the source evidence.
- Do not turn coursework or project work into employment.
- Do not upgrade "exposure" into "expertise."
- If the job requires a missing skill, do not insert that skill into a bullet.
- Every generated bullet must include `source_evidence`.

### Example Response

```json
{
  "generated_bullets": [
    {
      "bullet": "Built a React study planner to help students organize study sessions, applying frontend development concepts from coursework.",
      "source_evidence": "Campus Study Planner - Built a React app for scheduling study sessions.",
      "targeted_keywords": ["React", "frontend development"],
      "risk_level": "low"
    }
  ],
  "unsupported_claims_removed": ["REST API integration", "unit testing"],
  "human_review_notes": ["Confirm whether the project included JavaScript explicitly before adding JavaScript as a keyword."]
}
```

### Evaluation Criteria

- Bullets are faithful to the supplied source entry.
- No unsupported metrics or technologies are added.
- Generated bullets improve relevance to job keywords without deception.
- Human review notes identify any unresolved factual checks.

## Prompt 6: Cover Letter Generation

### Purpose

Draft a student-safe cover letter grounded in verified resume data and the job description.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["parsed_resume", "parsed_job", "student_preferences"],
  "properties": {
    "parsed_resume": { "type": "object" },
    "parsed_job": { "type": "object" },
    "student_preferences": {
      "type": "object",
      "properties": {
        "tone": { "type": "string", "enum": ["warm", "direct", "enthusiastic", "formal"] },
        "length": { "type": "string", "enum": ["short", "medium"] },
        "focus_areas": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": ["cover_letter", "evidence_used", "claims_requiring_review", "omitted_due_to_missing_evidence"],
  "properties": {
    "cover_letter": { "type": "string" },
    "evidence_used": { "type": "array", "items": { "type": "string" } },
    "claims_requiring_review": { "type": "array", "items": { "type": "string" } },
    "omitted_due_to_missing_evidence": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Safety Rules

- Do not claim the student has worked at the target company.
- Do not claim professional experience unless resume evidence supports it.
- Do not invent personal motivation, life story, referrals, awards, or company-specific knowledge.
- Use cautious language for emerging skills, such as "I have begun building experience with..." only when supported.
- Require human approval before submission.

### Example Response

```json
{
  "cover_letter": "Dear Hiring Team,\n\nI am applying for the Software Engineering Intern role at ExampleTech. My computer science coursework and React project experience have helped me build a foundation in frontend development, including creating a study planner that helps students organize study sessions. I am especially interested in this internship because the role emphasizes building and testing user-facing features in collaboration with product and design teams.\n\nI would welcome the opportunity to contribute, learn from experienced engineers, and continue developing practical software engineering skills.\n\nSincerely,\nAvery Chen",
  "evidence_used": [
    "B.S. Computer Science, Expected May 2027",
    "Campus Study Planner - Built a React app for scheduling study sessions"
  ],
  "claims_requiring_review": [],
  "omitted_due_to_missing_evidence": ["REST API experience", "testing experience"]
}
```

### Evaluation Criteria

- Letter is grounded in verified student evidence.
- Company and role details come from the parsed job description.
- Unsupported job requirements are not claimed.
- Tone is appropriate for a student applicant.

## Prompt 7: Project Suggestion

### Purpose

Suggest future projects that could help the student build missing skills for a target job. These suggestions must never be represented as completed work.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["parsed_resume", "parsed_job", "missing_skills_analysis"],
  "properties": {
    "parsed_resume": { "type": "object" },
    "parsed_job": { "type": "object" },
    "missing_skills_analysis": { "type": "object" },
    "constraints": {
      "type": "object",
      "properties": {
        "time_budget": { "type": "string" },
        "difficulty": { "type": "string", "enum": ["beginner", "intermediate", "advanced"] },
        "preferred_stack": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": ["suggested_projects", "resume_usage_rules"],
  "properties": {
    "suggested_projects": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "purpose", "skills_targeted", "deliverables", "steps", "completion_criteria"],
        "properties": {
          "title": { "type": "string" },
          "purpose": { "type": "string" },
          "skills_targeted": { "type": "array", "items": { "type": "string" } },
          "deliverables": { "type": "array", "items": { "type": "string" } },
          "steps": { "type": "array", "items": { "type": "string" } },
          "completion_criteria": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "resume_usage_rules": {
      "type": "array",
      "items": { "type": "string" }
    }
  }
}
```

### Safety Rules

- Label all project ideas as future or recommended projects.
- Do not generate resume bullets for the suggested project until the student confirms completion.
- Do not imply the student has already used missing skills.
- Include completion criteria so the student knows when a project can ethically be added to a resume.

### Example Response

```json
{
  "suggested_projects": [
    {
      "title": "Public API Frontend Dashboard",
      "purpose": "Build evidence for REST API and frontend data handling skills.",
      "skills_targeted": ["REST APIs", "JavaScript", "React"],
      "deliverables": ["GitHub repository", "Deployed demo", "README with setup instructions"],
      "steps": [
        "Choose a public API",
        "Build a React interface that fetches and displays API data",
        "Handle loading and error states",
        "Deploy the app"
      ],
      "completion_criteria": [
        "The repository contains working source code",
        "The deployed demo loads real API data",
        "The README explains the API and implementation choices"
      ]
    }
  ],
  "resume_usage_rules": [
    "Do not list this project on the resume until it is completed.",
    "After completion, describe only the features and tools actually used."
  ]
}
```

### Evaluation Criteria

- Suggestions target real gaps from the missing skills analysis.
- Projects are achievable for a student MVP audience.
- Resume usage rules prevent premature or false claims.
- Completion criteria are concrete and verifiable.

## Prompt 8: Hallucination/Fake-Experience Safety Check

### Purpose

Review generated application content against verified student evidence and block unsupported claims before the student can use it.

### Input JSON Schema

```json
{
  "type": "object",
  "required": ["generated_content", "parsed_resume", "parsed_job", "content_type"],
  "properties": {
    "generated_content": { "type": "string" },
    "parsed_resume": { "type": "object" },
    "parsed_job": { "type": "object" },
    "content_type": {
      "type": "string",
      "enum": ["resume_bullet", "cover_letter", "profile_summary", "project_description"]
    }
  }
}
```

### Output JSON Schema

```json
{
  "type": "object",
  "required": ["approval_status", "unsupported_claims", "risky_claims", "safe_rewrite", "review_notes"],
  "properties": {
    "approval_status": {
      "type": "string",
      "enum": ["approved", "needs_human_review", "blocked"]
    },
    "unsupported_claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim", "reason", "severity"],
        "properties": {
          "claim": { "type": "string" },
          "reason": { "type": "string" },
          "severity": { "type": "string", "enum": ["medium", "high", "critical"] }
        }
      }
    },
    "risky_claims": { "type": "array", "items": { "type": "string" } },
    "safe_rewrite": { "type": ["string", "null"] },
    "review_notes": { "type": "array", "items": { "type": "string" } }
  }
}
```

### Safety Rules

- Block any generated content that invents fake experience, fake projects, fake skills, fake education, fake companies, fake certifications, or fake work history.
- Treat unsupported metrics and outcomes as high severity.
- Treat invented employers, roles, degrees, or certifications as critical severity.
- Provide a safe rewrite only when the unsupported claim can be removed without changing the meaning into another unsupported claim.
- Never approve content that has not been compared to verified student evidence.

### Example Response

```json
{
  "approval_status": "blocked",
  "unsupported_claims": [
    {
      "claim": "Integrated REST APIs into production systems",
      "reason": "The resume does not show REST API experience or production system work.",
      "severity": "critical"
    }
  ],
  "risky_claims": ["production systems"],
  "safe_rewrite": "Built a React study planner to help students organize study sessions.",
  "review_notes": ["The rewrite removes unsupported API and production claims."]
}
```

### Evaluation Criteria

- Unsupported claims are detected with high recall.
- Critical fake-experience claims are blocked.
- Safe rewrite preserves only verified facts.
- Approved content contains no unsupported claims.

## Prompt Versioning Strategy

Each prompt must have an explicit version identifier:

```text
careerproof.<prompt_name>.v<major>.<minor>.<patch>
```

Example:

```text
careerproof.resume_parsing.v1.0.0
```

Versioning rules:

- Major version changes when the input or output schema changes incompatibly.
- Minor version changes when prompt behavior changes while schemas remain compatible.
- Patch version changes for wording clarifications, safety rule additions, or evaluation fixes that do not alter expected structure.
- Every production prompt version must have a changelog entry.
- Prompt outputs must store the prompt version used for traceability.
- Deprecated prompts should remain available for replaying historical evaluations until migration is complete.

## Prompt Registry Plan

The MVP should maintain a prompt registry that records:

- Prompt ID and semantic version.
- Prompt purpose.
- System instructions.
- User message template.
- Input schema version.
- Output schema version.
- Safety rules.
- Owner.
- Created date and last modified date.
- Evaluation dataset version.
- Minimum passing evaluation thresholds.
- Deployment status: `draft`, `candidate`, `production`, `deprecated`, or `blocked`.

Registry requirements:

- Only `production` prompts can be used in student-facing application flows.
- `candidate` prompts must pass automated evaluation and human review before promotion.
- Prompt changes must be reviewed with special attention to fake-experience prevention.
- Registry entries should support rollback to a previous production version.

## Evaluation Dataset Plan

The prompt evaluation dataset should include representative student MVP cases:

- First-year student with coursework but no work experience.
- Student with class projects and no internships.
- Student with one internship.
- Career changer with non-technical work experience.
- Student with ambiguous resume formatting.
- Student with listed tools but weak evidence of usage.
- Job descriptions with clear requirements.
- Job descriptions with vague or inflated requirements.
- Jobs requiring skills the student does not have.
- Adversarial examples where generated content includes fake metrics, fake employers, fake certifications, or fake projects.

Each evaluation case should include:

- Resume input.
- Job description input.
- Expected parsed entities.
- Expected missing skills.
- Known unsupported claims.
- Approved safe examples.
- Blocked unsafe examples.
- Human-labeled pass/fail criteria.

Minimum evaluation dimensions:

- Schema validity.
- Extraction accuracy.
- Evidence traceability.
- Missing skill recall.
- Unsupported claim detection.
- False positive rate for safe claims.
- Student-appropriate tone.
- No fake-experience generation.

Recommended launch thresholds:

- 100% block rate for invented employers, degrees, certifications, companies, and work history in test cases.
- At least 95% detection of unsupported skills, projects, and metrics.
- At least 95% schema-valid outputs.
- Human review approval for all production prompt versions.

## Human Approval Requirement Before Application Submission

VeriBridge AI must require explicit human approval before any application material is submitted or used externally.

Required approval checkpoints:

- Student reviews parsed resume data and confirms it is accurate.
- Student reviews generated resume bullets before adding them to a resume.
- Student reviews generated cover letters before downloading, copying, or submitting.
- Student confirms that any listed project, skill, certification, education, company, role, date, or achievement is true.
- The hallucination safety check returns `approved` or a human reviewer resolves `needs_human_review`.

The product must not auto-submit job applications in the MVP. Generated content should be treated as a draft until the student approves it.

## Operational Flow

Recommended prompt order:

1. Parse resume.
2. Parse job description.
3. Analyze missing skills.
4. Explain match score.
5. Generate tailored resume bullets from verified entries only.
6. Generate cover letter from verified resume evidence and parsed job details.
7. Run hallucination safety check on every generated artifact.
8. Require student approval before use.
9. Suggest future projects for missing skills, clearly labeled as not yet completed.

This order keeps evidence extraction upstream and safety validation downstream, reducing the chance that unsupported claims enter student-facing application materials.
