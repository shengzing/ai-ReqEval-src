/**
 * Pure helpers for the Settings workspace state.
 *
 * Extracted from `settings-workspace.tsx` so they can be unit-tested in
 * the Node test runner without spinning up React or the browser. This
 * file is intentionally side-effect free.
 */

export interface ModelProfileLike {
  role: string
  model_name: string
  base_url?: string
  api_key?: string
  // Optional because older published settings may not persist this field.
  // Backend defaults missing value to True.
  reasoning_mode?: boolean
}

export interface PromptTemplateLike {
  id: string
  category: string
  body: string
}

export interface StageSkillProfileLike {
  stage_id: string
  primary_skill: string
  enabled_tools: string[]
  enabled_subagents: string[]
  enabled_skills: string[]
  auto_run_condition: string
  skill_versions: Record<string, string>
}

export interface RunPolicyLike {
  require_change_reason: boolean
  allow_locked_stage_rerun: boolean
  min_audit_requirements: string[]
}

export interface SettingsLike {
  models: ModelProfileLike[]
  prompts: PromptTemplateLike[]
  stage_skill_profiles: StageSkillProfileLike[]
  run_policy: RunPolicyLike
}

export interface RunLike {
  config_version_id?: string | null
}

const REQUIRED_VARIABLES = [
  'project_goal',
  'stage_objective',
  'evidence_summary',
  'previous_stage_result',
] as const

export function requiredPromptVariables(): string[] {
  return [...REQUIRED_VARIABLES]
}

export function ensureRequiredPromptVariables(prompt: PromptTemplateLike): string[] {
  if (prompt.category !== 'stage') return []
  return REQUIRED_VARIABLES.filter((variable) => !prompt.body.includes(`{{${variable}}}`))
}

export function collectEnabledToolsForStage(settings: SettingsLike, stageId: string): string[] {
  const profile = settings.stage_skill_profiles.find((item) => item.stage_id === stageId)
  return profile ? [...profile.enabled_tools] : []
}

export function collectEnabledSubagentsForStage(settings: SettingsLike, stageId: string): string[] {
  const profile = settings.stage_skill_profiles.find((item) => item.stage_id === stageId)
  return profile ? [...profile.enabled_subagents] : []
}

interface StageImpact {
  stage_id: string
  change_type: 'added' | 'removed' | 'modified'
}

export function collectStageImpact(base: SettingsLike, draft: SettingsLike): StageImpact[] {
  const baseMap = new Map(base.stage_skill_profiles.map((item) => [item.stage_id, item]))
  const draftMap = new Map(draft.stage_skill_profiles.map((item) => [item.stage_id, item]))
  const impacts: StageImpact[] = []
  const allIds = new Set<string>([...baseMap.keys(), ...draftMap.keys()])
  for (const stageId of allIds) {
    const baseProfile = baseMap.get(stageId)
    const draftProfile = draftMap.get(stageId)
    if (!baseProfile && draftProfile) {
      impacts.push({ stage_id: stageId, change_type: 'added' })
      continue
    }
    if (baseProfile && !draftProfile) {
      impacts.push({ stage_id: stageId, change_type: 'removed' })
      continue
    }
    if (!baseProfile || !draftProfile) continue
    const toolChanged = !arrayEqual(baseProfile.enabled_tools, draftProfile.enabled_tools)
    const subagentChanged = !arrayEqual(baseProfile.enabled_subagents, draftProfile.enabled_subagents)
    const enabledSkillsChanged = !arrayEqual(baseProfile.enabled_skills, draftProfile.enabled_skills)
    const primarySkillChanged = baseProfile.primary_skill !== draftProfile.primary_skill
    const autoRunChanged = baseProfile.auto_run_condition !== draftProfile.auto_run_condition
    const skillVersionsChanged = !recordEqual(baseProfile.skill_versions, draftProfile.skill_versions)
    if (toolChanged || subagentChanged || enabledSkillsChanged || primarySkillChanged || autoRunChanged || skillVersionsChanged) {
      impacts.push({ stage_id: stageId, change_type: 'modified' })
    }
  }
  return impacts
}

export interface ImpactSummary {
  stages: number
  models: number
  prompts: number
  policyKeys: number
}

interface ImpactPayload {
  impacted_stages: unknown[]
  impacted_models: unknown[]
  impacted_prompts: unknown[]
  impacted_policy_keys: string[]
}

export function buildSettingsImpactSummary(impact: ImpactPayload): ImpactSummary {
  return {
    stages: impact.impacted_stages.length,
    models: impact.impacted_models.length,
    prompts: impact.impacted_prompts.length,
    policyKeys: impact.impacted_policy_keys.length,
  }
}

export function settingsSnapshotAppliesToRun(run: RunLike, publishedVersionId: string): boolean {
  if (!run.config_version_id) return true
  return run.config_version_id === publishedVersionId
}

function arrayEqual(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false
  const leftSorted = [...left].sort()
  const rightSorted = [...right].sort()
  for (let index = 0; index < leftSorted.length; index += 1) {
    if (leftSorted[index] !== rightSorted[index]) return false
  }
  return true
}

function recordEqual(left: Record<string, string>, right: Record<string, string>): boolean {
  const leftKeys = Object.keys(left)
  const rightKeys = Object.keys(right)
  if (leftKeys.length !== rightKeys.length) return false
  for (const key of leftKeys) {
    if (left[key] !== right[key]) return false
  }
  return true
}
