'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ClipboardList,
  Database,
  Info,
  Loader2,
  MessageSquare,
  RotateCcw,
  Send,
  Sparkles,
  Undo2,
  Wrench,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { ApiError } from '@/lib/api-error'
import { DocsSection } from '@/components/codex/docs-section'
import {
  loadProjectSettingsBundle,
  loadProjectSettingsImpact,
  loadProjectSettingsVersions,
  loadSkillOptions,
  publishProjectSettings,
  resetProjectSettings,
  saveProjectSettingsDraft,
} from '@/lib/api-client'
import type {
  ApiProjectSettings,
  ApiProjectSettingsBundle,
  ApiRunPolicy,
  ApiSettingsImpact,
  ApiSkillOption,
  ApiStageSkillProfile,
} from '@/lib/api-types'

type SectionId = 'models' | 'prompts' | 'skills' | 'policy' | 'docs'

interface SettingsWorkspaceProps {
  projectId?: string
  projectName?: string
  onBack: () => void
  onDirtyChange?: (dirty: boolean) => void
}

const SECTION_DEFS: Array<{ id: SectionId; label: string; icon: typeof Sparkles }> = [
  { id: 'models', label: '模型', icon: Sparkles },
  { id: 'prompts', label: '提示词', icon: MessageSquare },
  { id: 'skills', label: '阶段 Skills', icon: Wrench },
  { id: 'policy', label: '配置发布', icon: ClipboardList },
  { id: 'docs', label: '使用手册', icon: BookOpen },
]

interface DraftState {
  models: ApiProjectSettings['models']
  prompts: ApiProjectSettings['prompts']
  stage_skill_profiles: ApiStageSkillProfile[]
  run_policy: ApiRunPolicy
  change_reason: string
}

const EMPTY_DRAFT: DraftState = {
  models: [],
  prompts: [],
  stage_skill_profiles: [],
  run_policy: {
    require_change_reason: true,
    allow_locked_stage_rerun: true,
    min_audit_requirements: ['config_version_id', 'model_alias', 'prompt_hash', 'skill_version'],
    conversation_message_limit: 20,
    conversation_evidence_item_limit: 50,
    conversation_evidence_snippet_limit: 500,
    conversation_run_event_limit: 30,
  },
  change_reason: '',
}

function clonePublished(settings: ApiProjectSettings): DraftState {
  return {
    models: settings.models.map((model) => ({ ...model })),
    prompts: settings.prompts.map((prompt) => ({ ...prompt, required_variables: [...prompt.required_variables] })),
    stage_skill_profiles: settings.stage_skill_profiles.map((profile) => ({
      ...profile,
      enabled_tools: [...profile.enabled_tools],
      enabled_subagents: [...profile.enabled_subagents],
      skill_versions: { ...profile.skill_versions },
    })),
    run_policy: {
      require_change_reason: settings.run_policy.require_change_reason,
      allow_locked_stage_rerun: settings.run_policy.allow_locked_stage_rerun,
      min_audit_requirements: [...settings.run_policy.min_audit_requirements],
      conversation_message_limit: settings.run_policy.conversation_message_limit ?? 20,
      conversation_evidence_item_limit: settings.run_policy.conversation_evidence_item_limit ?? 50,
      conversation_evidence_snippet_limit: settings.run_policy.conversation_evidence_snippet_limit ?? 500,
      conversation_run_event_limit: settings.run_policy.conversation_run_event_limit ?? 30,
    },
    change_reason: '',
  }
}

export function SettingsWorkspace({ projectId, projectName, onBack, onDirtyChange }: SettingsWorkspaceProps) {
  const [bundle, setBundle] = useState<ApiProjectSettingsBundle | undefined>()
  const [impact, setImpact] = useState<ApiSettingsImpact | undefined>()
  const [versions, setVersions] = useState<ApiProjectSettings[]>([])
  const [skillOptions, setSkillOptions] = useState<ApiSkillOption[]>([])
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT)
  const [section, setSection] = useState<SectionId>('models')
  const [loading, setLoading] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [lastSavedDraft, setLastSavedDraft] = useState<DraftState | undefined>()

  const reload = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setErrorMessage(null)
    try {
      const [nextBundle, nextImpact, nextVersions, nextSkillOptions] = await Promise.all([
        loadProjectSettingsBundle(projectId),
        loadProjectSettingsImpact(projectId).catch(() => undefined),
        loadProjectSettingsVersions(projectId).catch(() => ({ items: [] as ApiProjectSettings[] })),
        loadSkillOptions().catch(() => ({ items: [] as ApiSkillOption[] })),
      ])
      setBundle(nextBundle)
      setImpact(nextImpact)
      setVersions(nextVersions.items)
      setSkillOptions(nextSkillOptions.items)
      const source = nextBundle.draft ?? nextBundle.published
      if (source) {
        const cloned = clonePublished(source)
        setDraft(cloned)
        setLastSavedDraft(cloned)
      }
    } catch (loadError) {
      setErrorMessage(loadError instanceof Error ? loadError.message : '加载设置失败')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void reload()
  }, [reload])

  // Compute dirty state BEFORE any early returns — hooks must not be conditional
  // Track whether local draft has diverged from the last-saved server snapshot,
  // not just whether a server-side draft exists.
  const draftDirty = lastSavedDraft !== undefined && JSON.stringify(draft) !== JSON.stringify(lastSavedDraft)

  // Notify parent when dirty state changes
  useEffect(() => {
    onDirtyChange?.(draftDirty)
  }, [draftDirty, onDirtyChange])

  if (!projectId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-background p-8 text-sm text-muted-foreground">
        <Database className="size-6 text-muted-foreground/60" />
        <p>请先在左侧选择一个项目，再进入设置。</p>
        <Button variant="outline" size="sm" onClick={onBack}>
          返回工作台
        </Button>
      </div>
    )
  }

  if (loading && !bundle) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        加载项目设置...
      </div>
    )
  }

  const hasDraft = bundle?.has_draft === true

  const displayModels = draft.models
  const displayPrompts = draft.prompts
  const displayProfiles = draft.stage_skill_profiles
  const displayPolicy = draft.run_policy

  const updateModel = (role: string, patch: Partial<DraftState['models'][number]>) => {
    setDraft((prev) => ({
      ...prev,
      models: prev.models.map((model) => (model.role === role ? { ...model, ...patch } : model)),
    }))
  }

  const updatePrompt = (id: string, patch: Partial<DraftState['prompts'][number]>) => {
    setDraft((prev) => ({
      ...prev,
      prompts: prev.prompts.map((prompt) => (prompt.id === id ? { ...prompt, ...patch } : prompt)),
    }))
  }

  const updateProfile = (stageId: string, patch: Partial<ApiStageSkillProfile>) => {
    setDraft((prev) => ({
      ...prev,
      stage_skill_profiles: prev.stage_skill_profiles.map((profile) =>
        profile.stage_id === stageId ? { ...profile, ...patch } : profile
      ),
    }))
  }

  const toggleArray = (
    list: string[],
    value: string,
    onChange: (next: string[]) => void
  ) => {
    if (list.includes(value)) {
      onChange(list.filter((item) => item !== value))
    } else {
      onChange([...list, value])
    }
  }

  const updatePolicy = (patch: Partial<ApiRunPolicy>) => {
    setDraft((prev) => ({
      ...prev,
      run_policy: { ...prev.run_policy, ...patch },
    }))
  }

  const handleReset = async () => {
    if (!projectId) return
    setResetting(true)
    setErrorMessage(null)
    setSuccessMessage(null)
    try {
      const reset = await resetProjectSettings(projectId)
      setDraft(clonePublished(reset))
      setSuccessMessage('已重置为系统默认设置（草稿）。')
      await reload()
    } catch (resetError) {
      setErrorMessage(resetError instanceof Error ? resetError.message : '重置失败')
    } finally {
      setResetting(false)
    }
  }

  const handleLoadVersion = (version: ApiProjectSettings) => {
    const cloned = clonePublished(version)
    setDraft(cloned)
    setSection('models')
    setErrorMessage(null)
    setSuccessMessage(`已加载版本 ${version.version_id} 到草稿，可编辑后发布。`)
  }

  const handlePublish = async () => {
    if (!projectId) return
    if (!draft.change_reason.trim()) {
      setErrorMessage('发布前必须填写变更原因。')
      return
    }
    setPublishing(true)
    setErrorMessage(null)
    setSuccessMessage(null)
    try {
      await saveProjectSettingsDraft(projectId, {
        models: draft.models,
        prompts: draft.prompts,
        stage_skill_profiles: draft.stage_skill_profiles,
        run_policy: draft.run_policy,
        change_reason: draft.change_reason,
      })
      const published = await publishProjectSettings(projectId, {
        change_reason: draft.change_reason.trim(),
      })
      setSuccessMessage(`已发布版本 ${published.version_id}。`)
      await reload()
    } catch (publishError) {
      setErrorMessage(
        publishError instanceof ApiError
          ? publishError.message
          : publishError instanceof Error
            ? publishError.message
            : '发布失败'
      )
    } finally {
      setPublishing(false)
    }
  }

  return (
    <div className="flex h-full w-full min-h-0 flex-col bg-background">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onBack} className="gap-1.5 text-xs text-muted-foreground">
            <ChevronLeft className="size-3.5" />
            返回工作台
          </Button>
          <div className="text-sm font-medium text-foreground/90">
            {projectName ?? '项目'} · 设置
          </div>
        </div>
        <div className="flex items-center gap-2">
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="sm" disabled={resetting} className="gap-1.5">
                <Undo2 className="size-3.5" />
                恢复默认
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>恢复默认设置？</AlertDialogTitle>
                <AlertDialogDescription>
                  此操作会用系统默认设置覆盖当前草稿，已编辑的内容将丢失。该操作不可撤销。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={handleReset}>确认恢复</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <Button size="sm" onClick={handlePublish} disabled={publishing} className="gap-1.5">
            {publishing ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
            发布配置
          </Button>
        </div>
      </header>

      {(errorMessage || successMessage) && (
        <div
          className={cn(
            'flex items-center gap-2 border-b border-border px-4 py-1.5 text-xs',
            errorMessage ? 'bg-destructive/10 text-destructive' : 'bg-emerald-50 text-emerald-700'
          )}
        >
          {errorMessage ? <AlertTriangle className="size-3.5" /> : <CheckCircle2 className="size-3.5" />}
          <span>{errorMessage ?? successMessage}</span>
        </div>
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="flex w-[200px] shrink-0 flex-col border-r border-border bg-muted/20 overflow-hidden">
          <ScrollArea className="flex-1 px-2 py-3">
            <div className="space-y-1">
              {SECTION_DEFS.map((item) => {
                const Icon = item.icon
                const active = section === item.id
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSection(item.id)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors',
                      active
                        ? 'bg-primary/10 text-primary'
                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                    )}
                  >
                    <Icon className="size-3.5" />
                    {item.label}
                  </button>
                )
              })}
            </div>
          </ScrollArea>
          <div className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
            {draftDirty ? '草稿未发布' : '当前为已发布配置'}
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {section === 'docs' ? (
            <div className="flex min-h-0 flex-1 flex-col p-4">
              <DocsSection />
            </div>
          ) : (
            <ScrollArea className="flex-1 min-h-0">
              <div className="space-y-4 p-4">
                {section === 'models' && (
                  <ModelsSection
                    models={displayModels}
                    onChange={updateModel}
                />
              )}
              {section === 'prompts' && (
                <PromptsSection
                  prompts={displayPrompts}
                  onChange={updatePrompt}
                />
              )}
              {section === 'skills' && (
                <SkillsSection
                  profiles={displayProfiles}
                  skillOptions={skillOptions}
                  onChange={updateProfile}
                  onToggleTool={(stageId, tool) => {
                    const profile = displayProfiles.find((item) => item.stage_id === stageId)
                    if (!profile) return
                    toggleArray(profile.enabled_tools, tool, (next) =>
                      updateProfile(stageId, { enabled_tools: next })
                    )
                  }}
                  onToggleSubagent={(stageId, subagent) => {
                    const profile = displayProfiles.find((item) => item.stage_id === stageId)
                    if (!profile) return
                    toggleArray(profile.enabled_subagents, subagent, (next) =>
                      updateProfile(stageId, { enabled_subagents: next })
                    )
                  }}
                />
              )}
              {section === 'policy' && (
                <PolicySection
                  policy={displayPolicy}
                  onChange={updatePolicy}
                  changeReason={draft.change_reason}
                  onChangeReason={(value) =>
                    setDraft((prev) => ({ ...prev, change_reason: value }))
                  }
                  impact={impact}
                  versions={versions}
                  bundle={bundle}
                  onLoadVersion={handleLoadVersion}
                />
              )}
            </div>
            </ScrollArea>
          )}
        </main>
      </div>
    </div>
  )
}

interface ModelsSectionProps {
  models: DraftState['models']
  onChange: (role: string, patch: Partial<DraftState['models'][number]>) => void
}

function ModelsSection({ models, onChange }: ModelsSectionProps) {
  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">模型配置</h2>
        <p className="text-xs text-muted-foreground">
          按兼容 OpenAI 的 Chat Completions API 配置。这里只保留模型名称、Base URL、Key、Think 模式。
        </p>
      </header>
      {models.map((model) => {
        // reasoning_mode 缺省 True:旧 settings 未持久化该字段时,默认保留推理能力。
        const reasoningMode = model.reasoning_mode ?? true
        return (
        <article
          key={model.role}
          className="rounded-lg border border-border bg-card p-3 shadow-xs"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] uppercase">
                {model.role}
              </span>
              <h3 className="text-sm font-medium">{labelForRole(model.role)}</h3>
            </div>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Switch
                checked={model.enabled}
                onCheckedChange={(value) => onChange(model.role, { enabled: value })}
              />
              {model.enabled ? '启用' : '停用'}
            </label>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-3">
            <Field label="模型名称" className="min-w-0">
              <Input
                className="min-w-0"
                value={model.model_name}
                placeholder="gpt-4o-mini"
                onChange={(event) => onChange(model.role, { model_name: event.target.value })}
              />
            </Field>
            <Field label="Base URL" className="min-w-0">
              <Input
                className="min-w-0"
                value={model.base_url ?? ''}
                placeholder="https://api.openai.com/v1"
                onChange={(event) => onChange(model.role, { base_url: event.target.value })}
              />
            </Field>
            <Field label="Key" className="min-w-0">
              <Input
                className="min-w-0"
                type="password"
                value={model.api_key ?? ''}
                placeholder="sk-..."
                autoComplete="off"
                onChange={(event) => onChange(model.role, { api_key: event.target.value })}
              />
            </Field>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-border/70 bg-muted/20 px-3 py-2">
            <div className="min-w-0 flex-1 space-y-0.5">
              <div className="text-xs font-medium text-foreground">Think 模式（推理模式）</div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                开启时模型可输出 {`<think>…</think>`} 推理链后再给最终答案（适合 MiniMax-M3 / DeepSeek-R1 / QwQ 等推理模型）。
                关闭时模型直接给最终答案，不再输出思考过程。
              </p>
            </div>
            <label className="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
              <Switch
                checked={reasoningMode}
                onCheckedChange={(value) => onChange(model.role, { reasoning_mode: value })}
              />
              {reasoningMode ? '开启' : '关闭'}
            </label>
          </div>
        </article>
        )
      })}
    </section>
  )
}
  interface PromptsSectionProps {
  prompts: DraftState['prompts']
  onChange: (id: string, patch: Partial<DraftState['prompts'][number]>) => void
}

const REQUIRED_VARIABLES = ['project_goal', 'stage_objective', 'evidence_summary', 'previous_stage_result']

function PromptsSection({ prompts, onChange }: PromptsSectionProps) {
  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">提示词模板</h2>
        <p className="text-xs text-muted-foreground">
          模板支持变量替换；发布时将校验必需变量（{REQUIRED_VARIABLES.join('、')}）。
        </p>
      </header>
      {prompts.map((prompt) => {
        const body = prompt.body || ''
        const missing = REQUIRED_VARIABLES.filter(
          (variable) => prompt.category === 'stage' && !body.includes(`{{${variable}}}`)
        )
        return (
          <article key={prompt.id} className="rounded-lg border border-border bg-card p-3 shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-0.5">
                <div className="text-sm font-medium">{prompt.title || prompt.id}</div>
                <span className="inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {prompt.category}
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">
                {prompt.skill_name ? `关联 Skill: ${prompt.skill_name}` : '通用模板'}
              </span>
            </div>
            <Textarea
              className="mt-2 min-h-[120px] font-mono text-xs"
              value={body}
              onChange={(event) => onChange(prompt.id, { body: event.target.value })}
            />
            {missing.length > 0 && (
              <div className="mt-1 text-[11px] text-amber-600">
                缺少必需变量：{missing.join('、')}
              </div>
            )}
          </article>
        )
      })}
    </section>
  )
}

const STAGE_LABELS: Record<string, string> = {
  '1': '阶段一·场景解构与风险定级',
  '2': '阶段二·价值建模与目标 SLA',
  '3': '阶段三·任务拆解与微型探针',
  '4': '阶段四·三维对齐与报告',
}

const SKILL_LABELS: Record<string, string> = {
  scenario_risk_skill: '场景风险识别',
  value_modeling_skill: '价值建模',
  probe_validation_skill: '探针验证',
  evidence_decision_skill: '证据决策',
  report_generation_skill: '报告生成',
  generic_stage_skill: '通用阶段',
}

interface SkillsSectionProps {
  profiles: ApiStageSkillProfile[]
  skillOptions: ApiSkillOption[]
  onChange: (stageId: string, patch: Partial<ApiStageSkillProfile>) => void
  onToggleTool: (stageId: string, tool: string) => void
  onToggleSubagent: (stageId: string, subagent: string) => void
}

function SkillsSection({ profiles, skillOptions, onChange, onToggleTool, onToggleSubagent }: SkillsSectionProps) {
  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">阶段 Skill 配置</h2>
        <p className="text-xs text-muted-foreground">
          为每个阶段选择主 Skill，启用范围须在 Skill 允许集合内。
        </p>
      </header>
      {profiles.map((profile) => {
        const currentSkill = skillOptions.find((s) => s.name === profile.primary_skill)
        const stageSuffix = profile.stage_id.split('-').slice(-1).join('-') || ''
        const eligibleSkills = skillOptions.filter((s) => s.stage_suffix === `stage-${stageSuffix}` || s.stage_suffix === 'unknown')
        const stageLabel = STAGE_LABELS[stageSuffix] ?? profile.stage_id

        return (
          <article key={profile.stage_id} className="rounded-lg border border-border bg-card p-3 shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-0.5">
                <div className="text-sm font-medium" title={profile.stage_id}>{stageLabel}</div>
              </div>
              <FieldWithInfo
                label="触发方式"
                info="控制该阶段 Skill 何时执行。「手动」需点运行按钮才执行；「输入就绪」在依赖数据备齐后自动执行；「自动」在阶段进入时立即执行。"
              >
                <select
                  className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                  value={profile.auto_run_condition}
                  onChange={(event) =>
                    onChange(profile.stage_id, { auto_run_condition: event.target.value })
                  }
                >
                  <option value="manual">手动</option>
                  <option value="on_inputs_ready">输入就绪</option>
                  <option value="auto">自动</option>
                </select>
              </FieldWithInfo>
            </div>

            <div className="mt-3">
              <Field label="主 Skill">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {eligibleSkills.map((skill) => {
                    const selected = skill.name === profile.primary_skill
                    return (
                      <button
                        key={skill.name}
                        type="button"
                        aria-pressed={selected}
                        onClick={() =>
                          onChange(profile.stage_id, {
                            primary_skill: skill.name,
                            enabled_tools: [...skill.allowed_tools],
                            enabled_subagents: [...skill.allowed_subagents],
                            skill_versions: {
                              ...profile.skill_versions,
                              [skill.name]: profile.skill_versions[skill.name] ?? 'mvp-v1',
                            },
                          })
                        }
                        className={cn(
                          'relative rounded-md border p-2 text-left transition-colors',
                          selected
                            ? 'border-primary bg-primary/5'
                            : 'border-border bg-background hover:border-primary/50'
                        )}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-xs font-medium">
                            {SKILL_LABELS[skill.name] ?? skill.name}
                          </span>
                          {selected && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                        </div>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          {skill.description}
                        </div>
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground/70">
                          {skill.name}
                        </div>
                      </button>
                    )
                  })}
                  {currentSkill && !eligibleSkills.includes(currentSkill) && (
                    <div className="rounded-md border border-dashed border-border p-2 text-[11px] text-muted-foreground">
                      当前 {SKILL_LABELS[currentSkill.name] ?? currentSkill.name} 不在可选列表
                    </div>
                  )}
                </div>
              </Field>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <FieldWithInfo
                label="工具"
                info="勾选该阶段 Skill 允许的工具。工具是 Skill 调用的能力单元（如文档解析、风险识别）；未勾选的项不会在该阶段执行，但 Skill 仍可访问其默认允许集，仅不向 Harness 暴露。"
              >
                <div className="flex flex-wrap gap-1.5">
                  {(currentSkill?.allowed_tools ?? []).map((tool) => {
                    const enabled = profile.enabled_tools.includes(tool)
                    return (
                      <label
                        key={tool}
                        className={cn(
                          'flex cursor-pointer items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] transition-colors',
                          enabled
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border bg-background text-muted-foreground hover:border-primary/50'
                        )}
                      >
                        <input
                          type="checkbox"
                          className="sr-only"
                          checked={enabled}
                          onChange={() => onToggleTool(profile.stage_id, tool)}
                        />
                        {tool}
                      </label>
                    )
                  })}
                  {!currentSkill && (
                    <span className="text-[11px] text-muted-foreground">请先选择主 Skill</span>
                  )}
                  {currentSkill && (currentSkill.allowed_tools ?? []).length === 0 && (
                    <span className="text-[11px] text-muted-foreground">该 Skill 无可用工具</span>
                  )}
                </div>
              </FieldWithInfo>
              <FieldWithInfo
                label="子代理"
                info="勾选该阶段 Skill 允许的子代理（Sub-agent）。子代理负责执行 Skill 的细分任务（如风险复核、价值复核）；未勾选的项不参与本轮执行，但 Skill 默认允许集不受影响。"
              >
                <div className="flex flex-wrap gap-1.5">
                  {(currentSkill?.allowed_subagents ?? []).map((subagent) => {
                    const enabled = profile.enabled_subagents.includes(subagent)
                    return (
                      <label
                        key={subagent}
                        className={cn(
                          'flex cursor-pointer items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] transition-colors',
                          enabled
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border bg-background text-muted-foreground hover:border-primary/50'
                        )}
                      >
                        <input
                          type="checkbox"
                          className="sr-only"
                          checked={enabled}
                          onChange={() => onToggleSubagent(profile.stage_id, subagent)}
                        />
                        {subagent}
                      </label>
                    )
                  })}
                  {!currentSkill && (
                    <span className="text-[11px] text-muted-foreground">请先选择主 Skill</span>
                  )}
                  {currentSkill && (currentSkill.allowed_subagents ?? []).length === 0 && (
                    <span className="text-[11px] text-muted-foreground">该 Skill 无可用子代理</span>
                  )}
                </div>
              </FieldWithInfo>
            </div>
          </article>
        )
      })}
    </section>
  )
}

interface PolicySectionProps {
  policy: ApiRunPolicy
  onChange: (patch: Partial<ApiRunPolicy>) => void
  changeReason: string
  onChangeReason: (value: string) => void
  impact?: ApiSettingsImpact
  versions: ApiProjectSettings[]
  bundle?: ApiProjectSettingsBundle | null
  onLoadVersion: (version: ApiProjectSettings) => void
}

function PolicySection({
  policy,
  onChange,
  changeReason,
  onChangeReason,
  impact,
  versions,
  bundle,
  onLoadVersion,
}: PolicySectionProps) {
  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">配置发布</h2>
        <p className="text-xs text-muted-foreground">
          关闭锁定重跑后，已锁定阶段不再允许新建 Run。
        </p>
      </header>
      <article className="rounded-lg border border-border bg-card p-3 shadow-xs">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <PolicySwitch
            label="发布需要变更原因"
            description="强制填写 change_reason 才能发布新配置。"
            checked={policy.require_change_reason}
            onChange={(value) => onChange({ require_change_reason: value })}
          />
          <PolicySwitch
            label="允许锁定阶段重跑"
            description="关闭后锁定阶段禁止新 Run（前端按钮会禁用）。"
            checked={policy.allow_locked_stage_rerun}
            onChange={(value) => onChange({ allow_locked_stage_rerun: value })}
          />
        </div>
        <Field label="本次发布变更原因（必填）" className="mt-3">
          <Textarea
            value={changeReason}
            placeholder="例如：把通用模型从 mini 升级到 4o，开启 Judge 模型"
            onChange={(event) => onChangeReason(event.target.value)}
          />
        </Field>
      </article>

      {impact && impact.has_draft && (
        <details className="group rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          <summary className="cursor-pointer font-medium marker:hidden">
            未发布变更影响范围
            <span className="ml-2 text-amber-700/70">
              （阶段 {impact.impacted_stages.length} · 模型 {impact.impacted_models.length} · 提示词 {impact.impacted_prompts.length}）
            </span>
          </summary>
          <ul className="mt-2 list-disc space-y-0.5 pl-4">
            <li>受影响阶段：{impact.impacted_stages.length}</li>
            <li>受影响模型：{impact.impacted_models.length}</li>
            <li>受影响提示词：{impact.impacted_prompts.length}</li>
            <li>受影响策略键：{impact.impacted_policy_keys.join('、') || '无'}</li>
          </ul>
          <p className="mt-1">{impact.summary}</p>
        </details>
      )}

      <article className="rounded-lg border border-border bg-card p-3 shadow-xs">
        <div className="mb-2 text-sm font-medium">最近版本</div>
        <ul className="space-y-1.5 text-xs">
          {versions.slice(-5).reverse().map((item) => {
            const publishedAt = item.published_at
              ? new Date(item.published_at).toLocaleString('zh-CN', {
                  year: 'numeric',
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : '未发布'
            const isCurrent = bundle?.published?.version_id === item.version_id
            return (
              <li
                key={item.id}
                className={cn(
                  'flex items-center justify-between gap-2 rounded-md border px-2 py-1.5',
                  isCurrent ? 'border-primary/40 bg-primary/5' : 'border-border/60'
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] text-muted-foreground">{publishedAt}</span>
                    {isCurrent && (
                      <span className="rounded bg-primary/15 px-1 py-0.5 text-[10px] font-medium text-primary">
                        当前
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 truncate text-[11px] text-foreground/80">
                    {item.change_reason || '无变更原因'}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 gap-1 px-1.5 text-[11px] text-muted-foreground hover:text-foreground"
                  onClick={() => onLoadVersion(item)}
                >
                  <RotateCcw className="size-3" />
                  加载
                </Button>
              </li>
            )
          })}
          {versions.length === 0 && (
            <li className="text-[11px] text-muted-foreground">暂无版本记录。</li>
          )}
        </ul>
      </article>
    </section>
  )
}

interface PolicySwitchProps {
  label: string
  description: string
  checked: boolean
  onChange: (value: boolean) => void
}

function PolicySwitch({ label, description, checked, onChange }: PolicySwitchProps) {
  return (
    <label className="flex items-start justify-between gap-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-sm">
      <div className="space-y-0.5">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-[11px] text-muted-foreground">{description}</div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  )
}

interface FieldProps {
  label: string
  children: React.ReactNode
  className?: string
}

interface FieldWithInfoProps {
  label: string
  info: React.ReactNode
  children: React.ReactNode
  className?: string
}

function FieldWithInfo({ label, info, children, className }: FieldWithInfoProps) {
  return (
    <div className={cn('space-y-1', className)}>
      <div className="flex items-center gap-1">
        <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={`${label} 说明`}
              className="text-muted-foreground/60 transition-colors hover:text-foreground"
            >
              <Info className="h-3 w-3" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-72 text-xs leading-relaxed text-popover-foreground">
            {info}
          </PopoverContent>
        </Popover>
      </div>
      {children}
    </div>
  )
}

function Field({ label, children, className }: FieldProps) {
  return (
    <div className={cn('space-y-1', className)}>
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  )
}

function labelForRole(role: string): string {
  if (role === 'general') return '通用推理'
  if (role === 'vision') return '视觉解析'
  if (role === 'judge') return 'Judge 校准'
  return role
}
