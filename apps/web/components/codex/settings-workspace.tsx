'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronLeft,
  ClipboardList,
  Database,
  Info,
  Loader2,
  MessageSquare,
  Plug,
  PlugZap,
  RotateCcw,
  Send,
  Sparkles,
  Undo2,
  User,
  Users,
  Wrench,
  XCircle,
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
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
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
  testProjectModelConnection,
} from '@/lib/api-client'
import type {
  ApiModelTestResponse,
  ApiProjectSettings,
  ApiProjectSettingsBundle,
  ApiRunPolicy,
  ApiSettingsImpact,
  ApiSkillOption,
  ApiStageSkillProfile,
} from '@/lib/api-types'

type SectionId = 'models' | 'prompts' | 'skills' | 'policy' | 'docs' | 'about'

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
  { id: 'about', label: '关于', icon: Info },
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
      enabled_skills: [...profile.enabled_skills],
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
    // Honor the project's own require_change_reason flag: only block when the
    // operator explicitly allowed empty reasons (False). The back-end
    // (publish_settings_draft) applies the same flag as the source of truth,
    // so we mirror it here to avoid a spurious "发布前必须填写变更原因"
    // prompt when the policy says a reason isn't required.
    if (draft.run_policy.require_change_reason && !draft.change_reason.trim()) {
      setErrorMessage('发布前必须填写变更原因：请在「配置发布」标签页填写「本次发布变更原因」。')
      setSection('policy')
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
                    projectId={projectId}
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
              {section === 'about' && <AboutSection />}
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
  projectId?: string
}

type ModelTestState =
  | { status: 'idle' }
  | { status: 'pending' }
  | { status: 'success'; result: ApiModelTestResponse }
  | { status: 'error'; message: string }

function ModelsSection({ models, onChange, projectId }: ModelsSectionProps) {
  // 测试结果按 role 分桶，键稳定且随 role 列表重排自动跟随。
  const [testStates, setTestStates] = useState<Record<string, ModelTestState>>({})

  const runTest = async (model: DraftState['models'][number]) => {
    if (!projectId) return
    setTestStates((prev) => ({ ...prev, [model.role]: { status: 'pending' } }))
    try {
      const result = await testProjectModelConnection(projectId, {
        model_name: model.model_name,
        base_url: model.base_url ?? '',
        api_key: model.api_key ?? '',
        reasoning_mode: model.reasoning_mode ?? true,
      })
      setTestStates((prev) => ({
        ...prev,
        [model.role]: result.ok
          ? { status: 'success', result }
          : { status: 'error', message: result.message || '测试失败' },
      }))
    } catch (testError) {
      const message =
        testError instanceof ApiError
          ? testError.message
          : testError instanceof Error
            ? testError.message
            : '测试失败'
      setTestStates((prev) => ({ ...prev, [model.role]: { status: 'error', message } }))
    }
  }

  const resetTest = (role: string) => {
    setTestStates((prev) => {
      if (!(role in prev)) return prev
      const next = { ...prev }
      delete next[role]
      return next
    })
  }

  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">模型配置</h2>
      </header>
      {models.map((model) => {
        // reasoning_mode 缺省 True:旧 settings 未持久化该字段时,默认保留推理能力。
        const reasoningMode = model.reasoning_mode ?? true
        const testState = testStates[model.role] ?? { status: 'idle' }
        return (
        <article
          key={model.role}
          className="rounded-lg border border-border bg-card p-3 shadow-xs"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-medium">{labelForRole(model.role)}</h3>
              <ModelTestButton
                model={model}
                state={testState}
                disabled={!projectId}
                onRun={() => runTest(model)}
                onReset={() => resetTest(model.role)}
              />
            </div>
            <div className="flex items-center gap-2">
              <BrainToggle
                enabled={reasoningMode}
                onChange={(value) => onChange(model.role, { reasoning_mode: value })}
              />
              <PlugToggle
                enabled={model.enabled}
                onChange={(value) => onChange(model.role, { enabled: value })}
              />
            </div>
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
        </article>
        )
      })}
    </section>
  )
}

interface ModelTestButtonProps {
  model: DraftState['models'][number]
  state: ModelTestState
  disabled?: boolean
  onRun: () => void
  onReset: () => void
}

function ModelTestButton({ model, state, disabled, onRun, onReset }: ModelTestButtonProps) {
  const canRun = Boolean(
    model.model_name && (model.base_url ?? '') && (model.api_key ?? '')
  )
  const tooltipText =
    state.status === 'pending'
      ? '测试中…'
      : state.status === 'success'
        ? `${state.result.message}（点击重新测试）`
        : state.status === 'error'
          ? `${state.message}（点击重新测试）`
          : canRun
            ? '测试模型是否可用'
            : '请先填写模型名称、Base URL 和 Key'

  const icon =
    state.status === 'pending' ? (
      <Loader2 className="size-3.5 animate-spin" />
    ) : state.status === 'success' ? (
      <CheckCircle2 className="size-3.5 text-emerald-600" />
    ) : state.status === 'error' ? (
      <XCircle className="size-3.5 text-destructive" />
    ) : (
      <PlugZap className="size-3.5" />
    )

  const buttonClass = cn(
    'inline-flex h-6 items-center gap-1 rounded-md border px-1.5 text-[11px] transition-colors',
    state.status === 'idle'
      ? 'border-border text-muted-foreground hover:bg-muted hover:text-foreground'
      : 'border-transparent text-muted-foreground hover:bg-muted hover:text-foreground'
  )

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className={buttonClass}
          disabled={disabled || state.status === 'pending' || !canRun}
          onClick={state.status === 'idle' || state.status === 'pending' ? onRun : onReset}
          aria-label={`测试 ${model.role} 模型`}
        >
          {icon}
          <span className="sr-only">测试</span>
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{tooltipText}</TooltipContent>
    </Tooltip>
  )
}

interface PlugToggleProps {
  enabled: boolean
  onChange: (value: boolean) => void
}

function PlugToggle({ enabled, onChange }: PlugToggleProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={enabled ? '停用模型' : '启用模型'}
          onClick={() => onChange(!enabled)}
          className={cn(
            'flex h-6 w-6 items-center justify-center rounded-md border transition-colors',
            enabled
              ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20'
              : 'border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
          )}
        >
          <Plug className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>{enabled ? '已启用（点击拔出停用）' : '已停用（点击插回启用）'}</TooltipContent>
    </Tooltip>
  )
}

interface BrainToggleProps {
  enabled: boolean
  onChange: (value: boolean) => void
}

function BrainToggle({ enabled, onChange }: BrainToggleProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={enabled ? '关闭 Think 模式' : '开启 Think 模式'}
          onClick={() => onChange(!enabled)}
          className={cn(
            'flex h-6 w-6 items-center justify-center rounded-md border transition-colors',
            enabled
              ? 'border-violet-500/50 bg-violet-500/10 text-violet-600 hover:bg-violet-500/20'
              : 'border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
          )}
        >
          <Brain className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>
        {enabled ? 'Think 模式已开启（点击关闭，直接给最终答案）' : 'Think 模式已关闭（点击开启，输出推理链）'}
      </TooltipContent>
    </Tooltip>
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
  // 按 eligibleSkills 的注册顺序去重合并多个已启用 Skill 的工具/子代理允许集，
  // 作为该阶段可勾选项的并集来源。空启用时返回空数组（由调用方渲染空态提示）。
  const unionAllowed = (
    enabledSkillNames: string[],
    eligibleSkills: ApiSkillOption[],
    key: 'allowed_tools' | 'allowed_subagents'
  ): string[] => {
    const seen = new Set<string>()
    for (const skill of eligibleSkills) {
      if (!enabledSkillNames.includes(skill.name)) continue
      for (const item of skill[key]) seen.add(item)
    }
    return Array.from(seen)
  }

  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">阶段 Skill 配置</h2>
        <p className="text-xs text-muted-foreground">
          每个阶段可启用多个 Skill（点击右上角插座图标插回/拔出）；工具与子代理展示所有已启用 Skill 的并集。全部停用时由阶段 Harness 兜底处理。
        </p>
      </header>
      {profiles.map((profile) => {
        const stageSuffix = profile.stage_id.split('-').slice(-1).join('-') || ''
        const eligibleSkills = skillOptions.filter((s) => s.stage_suffix === `stage-${stageSuffix}` || s.stage_suffix === 'unknown')
        const stageLabel = STAGE_LABELS[stageSuffix] ?? profile.stage_id
        const enabledSkills = profile.enabled_skills
        const enabledDefs = eligibleSkills.filter((s) => enabledSkills.includes(s.name))
        const orphanEnabled = enabledSkills.filter(
          (name) => !eligibleSkills.some((s) => s.name === name)
        )
        const unionTools = unionAllowed(enabledSkills, eligibleSkills, 'allowed_tools')
        const unionSubagents = unionAllowed(enabledSkills, eligibleSkills, 'allowed_subagents')

        const toggleSkill = (skill: ApiSkillOption) => {
          const isEnabled = enabledSkills.includes(skill.name)
          const nextEnabled = isEnabled
            ? enabledSkills.filter((name) => name !== skill.name)
            : [...enabledSkills, skill.name]
          // primary_skill 由「第一个已启用 Skill」（按 eligible 顺序）派生；
          // 全停用时回退到当前 primary_skill，保持后端校验通过（不置空）。
          const enabledInOrder = eligibleSkills.filter((s) => nextEnabled.includes(s.name))
          const nextPrimary = enabledInOrder[0]?.name ?? profile.primary_skill
          // 启用时若缺少版本号则补 'mvp-v1'；停用时不动版本号。
          const nextSkillVersions = isEnabled
            ? profile.skill_versions
            : {
                ...profile.skill_versions,
                [skill.name]: profile.skill_versions[skill.name] ?? 'mvp-v1',
              }
          onChange(profile.stage_id, {
            enabled_skills: nextEnabled,
            primary_skill: nextPrimary,
            skill_versions: nextSkillVersions,
          })
        }

        return (
          <article key={profile.stage_id} className="rounded-lg border border-border bg-card p-3 shadow-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-0.5">
                <div className="text-sm font-medium" title={profile.stage_id}>{stageLabel}</div>
                <div className="text-[11px] text-muted-foreground">
                  已启用 {enabledDefs.length} 个 Skill
                  {enabledDefs.length > 0 && `：${enabledDefs.map((s) => SKILL_LABELS[s.name] ?? s.name).join('、')}`}
                </div>
              </div>
            </div>

            <div className="mt-3">
              <Field label="启用 Skill">
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {eligibleSkills.map((skill) => {
                    const isEnabled = enabledSkills.includes(skill.name)
                    const isPrimary = skill.name === profile.primary_skill
                    return (
                      <div
                        key={skill.name}
                        className={cn(
                          'relative rounded-md border p-2 transition-colors',
                          isEnabled
                            ? 'border-primary bg-primary/5'
                            : 'border-border bg-background hover:border-primary/50'
                        )}
                      >
                        <div className="flex items-start justify-between gap-1">
                          <div className="min-w-0 space-y-0.5">
                            <div className="flex items-center gap-1">
                              <span className="text-xs font-medium">
                                {SKILL_LABELS[skill.name] ?? skill.name}
                              </span>
                              {isPrimary && isEnabled && (
                                <span className="rounded bg-primary/15 px-1 text-[9px] font-medium text-primary">
                                  主
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] text-muted-foreground">
                              {skill.description}
                            </div>
                            <div className="font-mono text-[10px] text-muted-foreground/70">
                              {skill.name}
                            </div>
                          </div>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                type="button"
                                role="switch"
                                aria-checked={isEnabled}
                                aria-label={isEnabled ? `停用 ${SKILL_LABELS[skill.name] ?? skill.name}` : `启用 ${SKILL_LABELS[skill.name] ?? skill.name}`}
                                onClick={() => toggleSkill(skill)}
                                className={cn(
                                  'flex h-6 w-6 shrink-0 items-center justify-center rounded-md border transition-colors',
                                  isEnabled
                                    ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20'
                                    : 'border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground'
                                )}
                              >
                                <Plug className="size-3.5" />
                              </button>
                            </TooltipTrigger>
                            <TooltipContent>
                              {isEnabled ? '已启用（点击拔出停用）' : '已停用（点击插回启用）'}
                            </TooltipContent>
                          </Tooltip>
                        </div>
                      </div>
                    )
                  })}
                  {orphanEnabled.length > 0 && (
                    <div className="rounded-md border border-dashed border-border p-2 text-[11px] text-muted-foreground">
                      当前启用的 {orphanEnabled.map((n) => SKILL_LABELS[n] ?? n).join('、')} 不在该阶段可选列表
                    </div>
                  )}
                </div>
              </Field>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
              <FieldWithInfo
                label="工具"
                info="勾选该阶段已启用 Skill 允许的工具并集。工具是 Skill 调用的能力单元（如文档解析、风险识别）；未勾选的项不会在该阶段执行。全部停用时该阶段不会执行有效工具，由 Harness 兜底。"
              >
                <div className="flex flex-wrap gap-1.5">
                  {unionTools.map((tool) => {
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
                  {enabledDefs.length === 0 && (
                    <span className="text-[11px] text-amber-600">
                      未启用任何 Skill，该阶段不会执行有效工具
                    </span>
                  )}
                  {enabledDefs.length > 0 && unionTools.length === 0 && (
                    <span className="text-[11px] text-muted-foreground">已启用 Skill 无可用工具</span>
                  )}
                </div>
              </FieldWithInfo>
              <FieldWithInfo
                label="子代理"
                info="勾选该阶段已启用 Skill 允许的子代理（Sub-agent）并集。子代理负责执行 Skill 的细分任务（如风险复核、价值复核）；未勾选的项不参与本轮执行。"
              >
                <div className="flex flex-wrap gap-1.5">
                  {unionSubagents.map((subagent) => {
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
                  {enabledDefs.length === 0 && (
                    <span className="text-[11px] text-amber-600">
                      未启用任何 Skill，该阶段不会执行有效子代理
                    </span>
                  )}
                  {enabledDefs.length > 0 && unionSubagents.length === 0 && (
                    <span className="text-[11px] text-muted-foreground">已启用 Skill 无可用子代理</span>
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

const APP_VERSION = '0.1.0'

interface AboutItem {
  icon: typeof User
  label: string
  value: string
}

const ABOUT_ITEMS: AboutItem[] = [
  { icon: User, label: '作者', value: '贾承斌' },
  { icon: Users, label: '指导老师', value: '刘璘' },
]

function AboutSection() {
  return (
    <section className="space-y-3">
      <header className="space-y-1">
        <h2 className="text-sm font-medium">关于</h2>
        <p className="text-xs text-muted-foreground">
          ai-ReqEval · 银行 GenAI 场景前置评估研究与工具平台
        </p>
      </header>

      <article className="rounded-lg border border-border bg-card p-4 shadow-xs">
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {ABOUT_ITEMS.map((item) => {
            const Icon = item.icon
            return (
              <div
                key={item.label}
                className="flex items-center gap-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2.5"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Icon className="size-4" />
                </span>
                <div className="min-w-0 space-y-0.5">
                  <dt className="text-[11px] text-muted-foreground">{item.label}</dt>
                  <dd className="truncate text-sm font-medium text-foreground">{item.value}</dd>
                </div>
              </div>
            )
          })}
        </dl>

        <div className="mt-3 flex items-center gap-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Info className="size-4" />
          </span>
          <div className="min-w-0 space-y-0.5">
            <div className="text-[11px] text-muted-foreground">版本号</div>
            <div className="font-mono text-sm font-medium text-foreground">v{APP_VERSION}</div>
          </div>
        </div>
      </article>

      <article className="rounded-lg border border-border bg-card p-4 text-xs leading-relaxed text-muted-foreground shadow-xs">
        <p>
          本平台用于在银行 GenAI 场景立项前，评估该场景是否应当推进。当前研究对象为贷后风险监测与预警评估。平台产出可审计的风险、价值与技术证据，不替代生产审批或业务决策。
        </p>
      </article>
    </section>
  )
}
