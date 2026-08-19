"use client"

/**
 * Interactive Work Passport representation. Hover/tap a skill to illuminate
 * the projects and evidence that support it; hover a project to illuminate
 * the skills it demonstrates. Presentation fixture data only — mirrors the
 * real passport's claim → project → evidence structure.
 */

import { useState } from "react"
import { ProofDiamond } from "./brand"

type SkillId = "python" | "fastapi" | "ml" | "nlp"

const SKILLS: { id: SkillId; label: string; state: "verified" | "claimed" }[] = [
  { id: "python", label: "Python", state: "verified" },
  { id: "fastapi", label: "FastAPI", state: "verified" },
  { id: "ml", label: "Machine Learning", state: "verified" },
  { id: "nlp", label: "NLP", state: "claimed" },
]

const PROJECTS: {
  id: string
  name: string
  desc: string
  skills: SkillId[]
  evidence: string[]
}[] = [
  {
    id: "slt",
    name: "sign-language-translator",
    desc: "Real-time gesture recognition with a trained CNN and a FastAPI inference service.",
    skills: ["python", "ml", "fastapi"],
    evidence: ["GitHub code", "Project defense", "Live site"],
  },
  {
    id: "events",
    name: "campus-events-api",
    desc: "Production-style REST API with auth, background jobs, and full test suite.",
    skills: ["python", "fastapi"],
    evidence: ["GitHub code", "Documents"],
  },
]

export function PassportDemo() {
  const [activeSkill, setActiveSkill] = useState<SkillId | null>(null)
  const [activeProject, setActiveProject] = useState<string | null>(null)

  const skillDims = (id: SkillId) => {
    if (activeSkill) return activeSkill !== id
    if (activeProject)
      return !PROJECTS.find((p) => p.id === activeProject)?.skills.includes(id)
    return false
  }
  const projectDims = (id: string) => {
    if (activeProject) return activeProject !== id
    if (activeSkill)
      return !PROJECTS.find((p) => p.id === id)?.skills.includes(activeSkill)
    return false
  }

  return (
    <div className="lv-passport" data-testid="passport-demo">
      <div className="lv-passport-head">
        <div className="lv-passport-id">
          <span className="lv-demo-avatar" aria-hidden="true">MC</span>
          <div>
            <div className="lv-demo-name">Maya Chen</div>
            <div className="lv-demo-role">AI/ML Engineer · fixture profile</div>
          </div>
        </div>
        <span className="lv-passport-badge">Verified Work Passport</span>
      </div>

      <div className="lv-passport-hint" aria-hidden="true">
        Hover or tap a skill — see exactly what supports it.
      </div>

      <div className="lv-passport-skills" role="list" aria-label="Skills on this passport">
        {SKILLS.map((skill) => (
          <button
            key={skill.id}
            type="button"
            role="listitem"
            className="lv-skill-pill"
            data-dim={skillDims(skill.id) || undefined}
            data-active={activeSkill === skill.id || undefined}
            data-claimed={skill.state === "claimed" || undefined}
            onMouseEnter={() => setActiveSkill(skill.id)}
            onMouseLeave={() => setActiveSkill(null)}
            onFocus={() => setActiveSkill(skill.id)}
            onBlur={() => setActiveSkill(null)}
            onClick={() => setActiveSkill(skill.id)}
          >
            <ProofDiamond state={skill.state} size={9} />
            {skill.label}
            <span className="lv-skill-pill-state">
              {skill.state === "verified" ? "published evidence" : "claimed only"}
            </span>
          </button>
        ))}
      </div>

      <div className="lv-passport-projects">
        {PROJECTS.map((project) => (
          <div
            key={project.id}
            className="lv-passport-project"
            data-dim={projectDims(project.id) || undefined}
            onMouseEnter={() => setActiveProject(project.id)}
            onMouseLeave={() => setActiveProject(null)}
          >
            <div className="lv-passport-project-name">{project.name}</div>
            <p className="lv-passport-project-desc">{project.desc}</p>
            <div className="lv-passport-evidence">
              {project.evidence.map((ev) => (
                <span className="lv-evidence-chip" key={ev}>
                  <ProofDiamond state="verified" size={7} />
                  {ev}
                </span>
              ))}
              <span className="lv-evidence-view">View Proof →</span>
            </div>
          </div>
        ))}
      </div>

      <div className="lv-passport-foot">
        NLP stays <b>claimed only</b> until evidence is published — the passport
        never pretends otherwise.
      </div>
    </div>
  )
}
