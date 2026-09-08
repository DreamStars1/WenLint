export function normalizeDecisions(decisions) {
  return decisions.map((item, index) => ({ ...item, id: item.id ?? index }))
}

export function requiresSegmentedReview(text, threshold = 6000) {
  return Array.from(text).length > threshold
}

export function retainChangeChoices(previous, next, choices) {
  const byId = new Map(previous.map((item) => [item.id, item]))
  const retained = {}
  for (const item of next) {
    const old = byId.get(item.id)
    if (old && item.action === 'REWRITE' && ['action', 'before', 'after', 'source_start'].every((key) => old[key] === item[key])
      && ['accepted', 'rejected'].includes(choices[item.id])) retained[item.id] = choices[item.id]
  }
  return retained
}

export function reviewCompletionState(result) {
  if (result.reviewStatus === 'partial' || result.coverage?.status === 'partial') return 'partial'
  return result.reviewStatus === 'completed' ? 'complete' : 'error'
}

// Credentials remain transient and are excluded from this context identity.
export function reviewFingerprint(payload) {
  return JSON.stringify([payload.text, payload.profile, payload.filename, payload.baseUrl?.trim(), payload.model?.trim(), payload.workspaceRoot, payload.workspacePath, Boolean(payload.use_workspace_tools)])
}
