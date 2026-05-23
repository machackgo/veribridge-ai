/**
 * workflow-blueprints.ts
 * Website/App Type definitions and dynamic Workflow Blueprint config.
 *
 * Each blueprint drives:
 * - Placeholder text for the Functional Test Plan form fields
 * - Output indicators used to enrich backend detection
 * - Likely skills for display/mapping guidance
 * - Whether checkpoint tracking is supported
 */

export type WorkflowCheckpoint = {
  title: string
  expected: string
}

export type WorkflowBlueprint = {
  id: string
  label: string
  icon: string
  objectivePlaceholder: string
  inputPlaceholder: string
  expectedOutputPlaceholder: string
  workflowPlaceholder: string
  outputIndicators: string[]
  likelySkills: string[]
  githubHints: string[]
  supportsCheckpoints: boolean
  defaultCheckpoints?: WorkflowCheckpoint[]
}

export const WORKFLOW_BLUEPRINTS: WorkflowBlueprint[] = [
  {
    id: "ml_predictor",
    label: "ML Predictor / Classifier",
    icon: "🧠",
    objectivePlaceholder:
      "Verify the app accepts input features and displays a prediction result with a confidence score or risk label.",
    inputPlaceholder:
      "age=45; glucose=130; bmi=28\nor: origin=Fenway Park, Boston, MA; destination=Harvard University, Cambridge, MA; num_segments=5",
    expectedOutputPlaceholder:
      "Prediction label, confidence score, risk level, route cards, or recommendation should appear after submitting inputs.",
    workflowPlaceholder:
      "Fill the input fields with the test values.\nClick Predict / Analyze / Submit.\nWait for prediction result to appear.\nCapture screenshot after output shows.",
    outputIndicators: [
      "prediction", "confidence", "score", "label", "class", "probability",
      "risk", "recommended", "classification", "result", "accuracy",
    ],
    likelySkills: [
      "Machine Learning Engineering", "Model Serving",
      "Backend/API Engineering", "AI Product Deployment",
    ],
    githubHints: [
      "model files", "predictor.py", "api.py", "feature engineering",
      "training pipeline", "model weights", "inference",
    ],
    supportsCheckpoints: false,
  },
  {
    id: "chatbot_llm",
    label: "Chatbot / LLM App",
    icon: "💬",
    objectivePlaceholder:
      "Verify the chatbot accepts a prompt and returns a generated answer in the chat window.",
    inputPlaceholder:
      "prompt=Explain logistic regression in simple terms\nor: question=What are the main causes of road accidents in Boston?",
    expectedOutputPlaceholder:
      "A generated answer should appear in the chat window after sending the prompt.",
    workflowPlaceholder:
      "Fill the chat input with the prompt.\nClick Send / Ask / Submit.\nWait for the assistant answer to appear.\nCapture screenshot after the answer renders.",
    outputIndicators: [
      "answer", "response", "assistant", "generated", "reply",
      "message", "chat", "output", "result", "thinking",
    ],
    likelySkills: [
      "LLM Engineering", "Prompt Engineering", "Conversational AI",
      "Backend/API Engineering", "AI Product Deployment",
    ],
    githubHints: [
      "llm", "chatbot", "prompt", "openai", "anthropic", "langchain",
      "chain", "conversation", "rag", "embeddings",
    ],
    supportsCheckpoints: false,
  },
  {
    id: "search_recommender",
    label: "Search / Recommendation App",
    icon: "🔍",
    objectivePlaceholder:
      "Verify the app accepts a search query and displays ranked results or personalized recommendations.",
    inputPlaceholder:
      "query=AI internships for international students\nor: user_id=123; category=machine learning",
    expectedOutputPlaceholder:
      "Recommendation cards, ranked results, matching items, or filters should appear after submitting the query.",
    workflowPlaceholder:
      "Fill the search box with the query.\nClick Search / Recommend / Find.\nWait for result cards to appear.\nCapture screenshot after results render.",
    outputIndicators: [
      "results", "recommended", "matches", "ranked", "found",
      "suggestions", "similar", "relevant", "score", "items", "cards",
    ],
    likelySkills: [
      "Recommendation Systems", "Search Engineering",
      "Data Engineering", "Backend/API Engineering",
    ],
    githubHints: [
      "recommender", "similarity", "embedding", "search", "ranking",
      "collaborative filtering", "content-based", "index", "retrieval",
    ],
    supportsCheckpoints: false,
  },
  {
    id: "dashboard_analytics",
    label: "Dashboard / Analytics App",
    icon: "📊",
    objectivePlaceholder:
      "Verify the dashboard loads metrics and charts, and responds correctly to applied filters.",
    inputPlaceholder:
      "filter=Boston; date_range=last_30_days\nor: region=Northeast; metric=accident_rate",
    expectedOutputPlaceholder:
      "Charts, tables, KPI cards, or filtered analytics data should appear or update after filters are applied.",
    workflowPlaceholder:
      "Open the dashboard.\nApply the provided filters if any.\nWait for charts, KPI cards, or tables to update.\nCapture screenshot of updated dashboard state.",
    outputIndicators: [
      "chart", "table", "kpi", "metric", "dashboard", "analytics",
      "trend", "filter", "total", "average", "updated", "rate", "percentage",
    ],
    likelySkills: [
      "Data Visualization", "Analytics Engineering",
      "Data Engineering", "Frontend Engineering",
    ],
    githubHints: [
      "dashboard", "visualization", "chart", "plotly", "d3",
      "streamlit", "tableau", "metrics", "kpi", "aggregation", "pipeline",
    ],
    supportsCheckpoints: false,
  },
  {
    id: "saas_workflow",
    label: "SaaS / Multi-step Workflow",
    icon: "⚙",
    objectivePlaceholder:
      "Verify a complete multi-step product workflow from start to final output, including intermediate states and checkpoints.",
    inputPlaceholder:
      "user_goal=Add GitHub proof and save detected skills\nor: task=Submit request and verify confirmation",
    expectedOutputPlaceholder:
      "Progress appears at each step, final output state shows, and the dashboard or confirmation updates.",
    workflowPlaceholder:
      "Open the app.\nComplete each workflow step in sequence.\nVerify each checkpoint state appears before proceeding.\nCapture screenshots at key checkpoints and the final state.",
    outputIndicators: [
      "saved", "completed", "created", "updated", "success", "submitted",
      "progress", "done", "confirmation", "dashboard", "workflow",
    ],
    likelySkills: [
      "Full-stack Engineering", "Product Engineering",
      "Backend/API Engineering", "Frontend Engineering", "Workflow Automation",
    ],
    githubHints: [
      "workflow", "state machine", "steps", "multi-step", "form",
      "wizard", "progress", "pipeline", "orchestration",
    ],
    supportsCheckpoints: true,
    defaultCheckpoints: [
      { title: "Step 1 initiated", expected: "First step visible or loading state appears" },
      { title: "Intermediate state confirmed", expected: "Progress indicator or intermediate output visible" },
      { title: "Final output appears", expected: "Completion state, confirmation, or updated dashboard visible" },
    ],
  },
  {
    id: "portfolio_demo",
    label: "Portfolio / Product Demo",
    icon: "🌐",
    objectivePlaceholder:
      "Verify the live page displays project evidence, demo links, and key product sections visible to a recruiter.",
    inputPlaceholder:
      "none — page loads automatically without input\nor: section=machine-learning-projects",
    expectedOutputPlaceholder:
      "Project sections, demo links, screenshots, live product evidence, or case-study content should be visible.",
    workflowPlaceholder:
      "Open the page.\nScroll to the project or demo section if needed.\nCapture screenshot of visible project evidence and proof sections.",
    outputIndicators: [
      "project", "demo", "portfolio", "case study", "github", "live",
      "deployed", "results", "screenshot", "repository", "achieved",
    ],
    likelySkills: [
      "AI Product Deployment", "Frontend/Web Development",
      "Technical Communication", "Full-stack Engineering",
    ],
    githubHints: ["portfolio", "readme", "demo", "projects", "showcase", "homepage", "landing"],
    supportsCheckpoints: false,
  },
  {
    id: "custom_workflow",
    label: "Custom Workflow",
    icon: "✏",
    objectivePlaceholder:
      "Describe the specific workflow this website should complete and what proof it should generate.",
    inputPlaceholder:
      "key=value pairs, JSON input, or natural language description of test data",
    expectedOutputPlaceholder:
      "Describe what should appear after the workflow completes — visible text, cards, metrics, or confirmation states.",
    workflowPlaceholder:
      "Describe visible steps a human would take:\nfill input fields, click the action button,\nwait for result to appear, capture screenshot of the output state.",
    outputIndicators: [
      "result", "output", "success", "completed", "generated",
      "detected", "analysis", "response", "data",
    ],
    likelySkills: [],
    githubHints: [],
    supportsCheckpoints: false,
  },
]

export function getBlueprintById(id: string): WorkflowBlueprint | null {
  return WORKFLOW_BLUEPRINTS.find((b) => b.id === id) ?? null
}

/** Append blueprint output indicators to user-provided expected output before sending to backend. */
export function buildEnrichedExpectedOutput(
  userExpected: string,
  blueprint: WorkflowBlueprint | null,
): string {
  if (!blueprint || !blueprint.outputIndicators.length) return userExpected
  const lower = userExpected.toLowerCase()
  const missing = blueprint.outputIndicators
    .filter((t) => !lower.includes(t))
    .slice(0, 5)
  if (missing.length === 0) return userExpected
  const suffix = `Output should also include: ${missing.join(", ")}.`
  return userExpected ? `${userExpected}. ${suffix}` : suffix
}
