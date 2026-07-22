/** Persona displayed in the Student Shell — resolved from the real session, never hardcoded. */
export type StudentPersona = {
  name: string
  email: string
  initials: string
}

/** Derive display initials from a name (preferred) or email, never blank. */
export function studentPersonaInitials(name: string, email: string): string {
  const source = (name || email || "").trim()
  if (!source) return "ME"
  const words = source.split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  return source.slice(0, 2).toUpperCase()
}
