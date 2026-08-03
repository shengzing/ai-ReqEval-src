'use client'

import { cn } from '@/lib/utils'
import type { StageSkill } from '@/lib/types'

const SKILL_LABELS: Record<string, string> = {
  scenario_risk_skill: '场景风险识别',
  value_modeling_skill: '价值建模',
  probe_validation_skill: '探针验证',
  evidence_decision_skill: '证据决策',
  report_generation_skill: '报告生成',
  generic_stage_skill: '通用阶段',
}

export function SkillStrip({ skills }: { skills: StageSkill[] }) {
  if (skills.length === 0) return null

  return (
    <div>
      <p className="mb-3 text-xs text-muted-foreground">按阶段上下文组合调用</p>
      <div className="grid gap-2 md:grid-cols-3">
        {skills.map((skill) => (
          <SkillPill key={skill.id} skill={skill} />
        ))}
      </div>
    </div>
  )
}

function SkillPill({ skill }: { skill: StageSkill }) {
  const statusConfig = {
    ready: { label: '待命', className: 'bg-muted text-muted-foreground' },
    running: { label: '运行中', className: 'bg-blue-500/10 text-blue-600' },
    waiting_user: { label: '待确认', className: 'bg-amber-500/10 text-amber-600' },
    completed: { label: '已完成', className: 'bg-emerald-500/10 text-emerald-600' },
  }
  const config = statusConfig[skill.status]
  const displayName = SKILL_LABELS[skill.name] ?? skill.name

  return (
    <div className="rounded-md bg-muted/35 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-foreground" title={skill.name}>
          {displayName}
        </span>
        <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium', config.className)}>
          {config.label}
        </span>
      </div>
      <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{skill.description}</p>
    </div>
  )
}
