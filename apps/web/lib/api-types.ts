import type { RunEventFrame } from '@/lib/api-mappers'

export interface ApiProject {
  id: string
  name: string
  goal: string
  status: string
  created_at: string
  updated_at: string
}

export interface ApiStage {
  id: string
  project_id: string
  name: string
  status: string
  objective?: string | null
  created_at: string
}

export interface ApiStageResult {
  id: string
  project_id: string
  stage_id: string
  version_id: string
  base_version_id?: string | null
  run_id: string
  status: string
  input_file_ids: string[]
  evidence_item_ids: string[]
  model_config: Record<string, unknown>
  skill_versions: Record<string, string>
  autoresearch_record_ids: string[]
  confirmation_ids: string[]
  result_payload: Record<string, unknown>
  summary: string
  created_at: string
  updated_at: string
  locked_at?: string | null
}

export interface ApiConversation {
  id: string
  stage_id: string
  project_id: string
  title: string
  status: 'active' | 'archived' | 'deleted'
  created_at: string
  updated_at: string
  archived_at?: string | null
  messages?: Array<{
    role: 'user' | 'assistant'
    content: string
    created_at: string
    source_event_id?: string | null
    run_id?: string | null
    action_proposals?: Array<{
      id: string
      action_type: string
      title: string
      requires_confirmation: boolean
      status: string
    }>
    harness_warnings?: Array<Record<string, unknown>>
    tool_calls?: Array<Record<string, unknown>>
    process_only?: boolean
  }>
}

export interface ApiWorkspaceStage extends ApiStage {
  pending_confirmations: number
  conversations: ApiConversation[]
}

export interface ApiWorkspaceProject extends ApiProject {
  pending_count: number
  file_count: number
  stages: ApiWorkspaceStage[]
}

export interface ApiEvidenceItem {
  id: string
  project_id: string
  name: string
  source_type: string
  source_file_id?: string | null
  attachment_path?: string | null
  snippet?: string | null
  created_at: string
  status: string
  review_note?: string | null
  updated_at: string
}

export interface ApiFileArtifact {
  id: string
  project_id: string
  filename: string
  content_type: string
  status: string
  storage_path?: string | null
  size_bytes: number
  created_at: string
}

export interface ApiFilePreview {
  id: string
  project_id: string
  filename: string
  content_type: string
  preview_type: 'text' | 'pdf' | 'image'
  content: string
  encoding: 'utf-8' | 'base64'
  size_bytes: number
  truncated: boolean
}

export interface ApiVisionResultSummary {
  file_id: string
  model: string
  structured_fields: Record<string, unknown>
  evidence_fragments: Array<Record<string, unknown>>
  uncertainties: string[]
  to_confirm: Array<Record<string, unknown>>
  project_id: string
  raw_response: string
}

export interface ApiSkill {
  name: string
  description: string
}

export interface ApiAutoResearchRecord {
  id: string
  project_id: string
  stage_id: string
  run_id: string
  stage_result_id: string
  title: string
  source: string
  impact: string
  risk: string
  description: string
  action: string
  context: Record<string, unknown>
  status: string
  note?: string | null
  edited_description?: string | null
  created_at: string
  updated_at: string
  confirmed_at?: string | null
}

export interface ApiRun {
  id: string
  project_id: string
  stage_id?: string | null
  conversation_id?: string | null
  goal: string
  status: string
  failure_reason?: string | null
  failure_context?: Record<string, unknown>
  config_version_id?: string | null
  created_at: string
}

export interface ApiVersionLog {
  id: string
  project_id: string
  resource_type: string
  resource_id: string
  change_type: string
  summary: string
  run_id?: string | null
  details: Record<string, unknown>
  created_at: string
}

export interface ApiReport {
  id: string
  project_id: string
  title: string
  status: string
  approval_check_passed: boolean
  export_path?: string | null
  decision_card_path?: string | null
  evidence_directory_path?: string | null
  bundle_export_path?: string | null
  stage_result_ids: string[]
  evidence_item_ids: string[]
  created_at: string
}

export interface ApiStageLockCheck {
  stage_id: string
  ready: boolean
  checks: ApiStageLockCheckItem[]
}

export interface ApiStageLockCheckItem {
  key: string
  label: string
  passed: boolean
}

export interface ApiReportContent {
  id: string
  title: string
  status: string
  content: string
}

export interface ApiModelOption {
  provider: string
  model_name: string
  base_url?: string
}

export interface ApiSkillOption {
  name: string
  stage_suffix: string
  description: string
  allowed_tools: string[]
  allowed_subagents: string[]
  auto_run_condition: string
  visibility: string
}

export interface ApiModelProfile {
  role: string
  provider: string
  model_name: string
  base_url: string
  api_key: string
  enabled: boolean
  // True = reasoning model may emit <think>...</think> chains before JSON.
  // False = backend sends extra_body={enable_thinking: false} and a system
  // prompt directive to suppress the thinking chain.
  reasoning_mode: boolean
}

export interface ApiPromptTemplate {
  id: string
  category: string
  scope: string
  title: string
  body: string
  required_variables: string[]
  skill_name?: string | null
  version: string
}

export interface ApiStageSkillProfile {
  stage_id: string
  primary_skill: string
  enabled_tools: string[]
  enabled_subagents: string[]
  auto_run_condition: string
  skill_versions: Record<string, string>
}

export interface ApiRunPolicy {
  require_change_reason: boolean
  allow_locked_stage_rerun: boolean
  min_audit_requirements: string[]
  conversation_message_limit?: number
  conversation_evidence_item_limit?: number
  conversation_evidence_snippet_limit?: number
  conversation_run_event_limit?: number
}

export interface ApiProjectSettings {
  id: string
  project_id: string
  version_id: string
  base_version_id?: string | null
  status: 'draft' | 'published'
  config_hash: string
  change_reason: string
  models: ApiModelProfile[]
  prompts: ApiPromptTemplate[]
  stage_skill_profiles: ApiStageSkillProfile[]
  run_policy: ApiRunPolicy
  created_at: string
  updated_at: string
  published_at?: string | null
  created_by: string
}

export interface ApiProjectSettingsBundle {
  published?: ApiProjectSettings | null
  draft?: ApiProjectSettings | null
  has_draft: boolean
}

export interface ApiProjectSettingsList {
  items: ApiProjectSettings[]
}

export interface ApiSettingsImpact {
  project_id: string
  draft_id?: string | null
  draft_version_id?: string | null
  has_draft: boolean
  impacted_stages: Array<Record<string, unknown>>
  impacted_models: Array<Record<string, unknown>>
  impacted_prompts: Array<Record<string, unknown>>
  impacted_policy_keys: string[]
  summary: string
}

export interface StreamRunEventsOptions {
  signal?: AbortSignal
  onEvent?: (frame: RunEventFrame) => void
  maxReconnects?: number
}

/** 一次追加消息后后端返回的 assistant harness 消息（仅 run_harness=true 时存在） */
export interface ApiAssistantMessage {
  role: 'assistant'
  content: string
  created_at: string
  tool_calls?: Array<Record<string, unknown>>
}

/** 对话 Harness 的摘要信息，附在 AppendMessageResponse.harness */
export interface ApiHarnessSummary {
  conversation_harness_version: string
  intent: Record<string, unknown>
  citations: Array<Record<string, unknown>>
  warnings: Array<Record<string, unknown>>
  action_proposals: Array<{
    id: string
    action_type: string
    title: string
    requires_confirmation: boolean
    status: string
  }>
}

/** POST /conversations/{id}/messages 的响应体 */
export interface ApiAppendMessageResponse {
  role: 'user' | 'assistant'
  content: string
  created_at: string
  assistant_message?: ApiAssistantMessage
  harness?: ApiHarnessSummary
}

export interface ApiConfirmConversationActionProposalResponse {
  proposal: {
    id: string
    status: string
  }
  run_id: string
}
