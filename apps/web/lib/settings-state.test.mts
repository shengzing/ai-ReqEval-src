import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildSettingsImpactSummary,
  collectEnabledToolsForStage,
  collectStageImpact,
  ensureRequiredPromptVariables,
  requiredPromptVariables,
  settingsSnapshotAppliesToRun,
} from './settings-state.ts'

const baseSettings = {
  models: [
    { role: 'general', model_name: 'gpt-4o-mini', base_url: '', api_key: '' },
    { role: 'vision', model_name: 'gpt-4o', base_url: '', api_key: '' },
  ],
  prompts: [
    {
      id: 'prompt-system',
      category: 'system',
      body: 'system {{project_goal}}',
      required_variables: ['project_goal'],
    },
  ],
  stage_skill_profiles: [
    {
      stage_id: 'project-stage-1',
      primary_skill: 'scenario_risk_skill',
      enabled_skills: ['scenario_risk_skill'],
      enabled_tools: ['document_parse', 'risk_identify'],
      enabled_subagents: ['risk_review_subagent'],
      auto_run_condition: 'manual',
      skill_versions: { scenario_risk_skill: 'mvp-v1' },
    },
  ],
  run_policy: {
    require_change_reason: true,
    allow_locked_stage_rerun: true,
    min_audit_requirements: ['config_version_id', 'model_alias', 'prompt_hash', 'skill_version'],
  },
}

test('requiredPromptVariables returns canonical variable list', () => {
  assert.deepEqual(requiredPromptVariables(), [
    'project_goal',
    'stage_objective',
    'evidence_summary',
    'previous_stage_result',
  ])
})

test('ensureRequiredPromptVariables flags missing placeholders for stage templates', () => {
  const missing = ensureRequiredPromptVariables({
    id: 'prompt-stage-1',
    category: 'stage',
    body: '请基于 {{project_goal}} 输出 {{stage_objective}}',
  })
  assert.deepEqual(missing, ['evidence_summary', 'previous_stage_result'])
})

test('ensureRequiredPromptVariables accepts system templates without strict check', () => {
  assert.deepEqual(
    ensureRequiredPromptVariables({ id: 'system', category: 'system', body: 'no vars' }),
    []
  )
})

test('collectEnabledToolsForStage returns enabled tool list', () => {
  assert.deepEqual(collectEnabledToolsForStage(baseSettings, 'project-stage-1'), [
    'document_parse',
    'risk_identify',
  ])
  assert.deepEqual(collectEnabledToolsForStage(baseSettings, 'unknown'), [])
})

test('collectStageImpact reports stages whose tool or subagent set changed', () => {
  const draft = {
    ...baseSettings,
    stage_skill_profiles: [
      {
        ...baseSettings.stage_skill_profiles[0],
        enabled_tools: ['document_parse'],
      },
    ],
  }
  const impacted = collectStageImpact(baseSettings, draft)
  assert.equal(impacted.length, 1)
  assert.equal(impacted[0].stage_id, 'project-stage-1')
})

test('collectStageImpact reports primary_skill change even when tools match', () => {
  const draft = {
    ...baseSettings,
    stage_skill_profiles: [
      {
        ...baseSettings.stage_skill_profiles[0],
        primary_skill: 'value_modeling_skill',
      },
    ],
  }
  const impacted = collectStageImpact(baseSettings, draft)
  assert.equal(impacted.length, 1)
  assert.equal(impacted[0].change_type, 'modified')
})

test('collectStageImpact reports auto_run_condition change', () => {
  const draft = {
    ...baseSettings,
    stage_skill_profiles: [
      {
        ...baseSettings.stage_skill_profiles[0],
        auto_run_condition: 'auto',
      },
    ],
  }
  const impacted = collectStageImpact(baseSettings, draft)
  assert.equal(impacted.length, 1)
})

test('collectStageImpact reports skill_versions change', () => {
  const draft = {
    ...baseSettings,
    stage_skill_profiles: [
      {
        ...baseSettings.stage_skill_profiles[0],
        skill_versions: { scenario_risk_skill: 'mvp-v2' },
      },
    ],
  }
  const impacted = collectStageImpact(baseSettings, draft)
  assert.equal(impacted.length, 1)
})

test('collectStageImpact reports enabled_skills change when tools and primary match', () => {
  const draft = {
    ...baseSettings,
    stage_skill_profiles: [
      {
        ...baseSettings.stage_skill_profiles[0],
        enabled_skills: ['scenario_risk_skill', 'value_modeling_skill'],
      },
    ],
  }
  const impacted = collectStageImpact(baseSettings, draft)
  assert.equal(impacted.length, 1)
  assert.equal(impacted[0].stage_id, 'project-stage-1')
})

test('collectStageImpact reports no change when all fields match', () => {
  const impacted = collectStageImpact(baseSettings, baseSettings)
  assert.equal(impacted.length, 0)
})

test('buildSettingsImpactSummary counts impacted sections', () => {
  const summary = buildSettingsImpactSummary({
    impacted_stages: [{ stage_id: 'project-stage-1' }],
    impacted_models: [{ role: 'general' }],
    impacted_prompts: [],
    impacted_policy_keys: ['allow_locked_stage_rerun'],
  })
  assert.equal(summary.stages, 1)
  assert.equal(summary.models, 1)
  assert.equal(summary.prompts, 0)
  assert.equal(summary.policyKeys, 1)
})

test('settingsSnapshotAppliesToRun returns true when run has no config_version_id', () => {
  assert.equal(settingsSnapshotAppliesToRun({ config_version_id: null }, 'setv-abc'), true)
})

test('settingsSnapshotAppliesToRun returns false when run already pinned to a different version', () => {
  assert.equal(settingsSnapshotAppliesToRun({ config_version_id: 'setv-xyz' }, 'setv-abc'), false)
})

test('settingsSnapshotAppliesToRun returns true when run is pinned to the same version', () => {
  assert.equal(settingsSnapshotAppliesToRun({ config_version_id: 'setv-abc' }, 'setv-abc'), true)
})
