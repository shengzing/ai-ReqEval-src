'use client'

import { useState } from 'react'
import { AlertCircle, ArrowRight, CheckCircle2, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ApiError } from '@/lib/api-error'
import type { Stage } from '@/lib/types'

interface StageExitCardProps {
  stage: Stage
  onLockStage?: () => Promise<void> | void
}

export function StageExitCard({ stage, onLockStage }: StageExitCardProps) {
  const [locking, setLocking] = useState(false)
  const [lockError, setLockError] = useState<string>()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const isLocked = stage.status === 'locked'
  const lockCheck = stage.lockCheck
  const canLock = Boolean(lockCheck?.ready) && !isLocked

  const handleLock = async () => {
    setConfirmOpen(false)
    // Re-check canLock after dialog closes — conditions may have changed
    if (!canLock || locking) {
      setLockError('当前无法锁定阶段，门禁条件已变更。')
      return
    }
    setLocking(true)
    setLockError(undefined)
    setConfirmOpen(false)
    try {
      await onLockStage?.()
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : '阶段锁定失败'
      setLockError(message)
    } finally {
      setLocking(false)
    }
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {isLocked
              ? '当前阶段已锁定，不能继续修改阶段结果。'
              : lockCheck?.ready
                ? '后端门禁检查已通过，可以锁定阶段结果。'
                : '后端门禁检查未通过，请先处理未完成项。'}
          </p>
        </div>
        {!isLocked && (
          <Button
            size="sm"
            className="h-8 shrink-0 gap-1.5"
            disabled={!canLock || locking}
            onClick={() => setConfirmOpen(true)}
          >
            {locking ? '锁定中' : stage.exitAction ?? '锁定阶段结果'}
            <ArrowRight className="size-3.5" />
          </Button>
        )}
      </div>

      {/* Confirmation Dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认锁定阶段</DialogTitle>
            <DialogDescription>
              锁定后该阶段结果将不可修改，此操作不可撤销。确定要继续吗？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              取消
            </Button>
            <Button
              disabled={locking}
              onClick={() => void handleLock()}
            >
              {locking ? '锁定中...' : '确认锁定'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {lockCheck?.checks.length ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {lockCheck.checks.map((item) => {
            const Icon = item.passed ? CheckCircle2 : XCircle
            return (
              <div key={item.key} className="flex items-center gap-2 rounded-md bg-muted/35 px-3 py-2 text-xs">
                <Icon className={item.passed ? 'size-3.5 text-emerald-500' : 'size-3.5 text-amber-500'} />
                <span className="text-foreground">{item.label}</span>
              </div>
            )
          })}
        </div>
      ) : !isLocked ? (
        <div className="mt-3 flex items-center gap-2 rounded-md bg-muted/35 px-3 py-2 text-xs text-muted-foreground">
          <AlertCircle className="size-3.5" />
          暂未取得后端锁定检查结果。
        </div>
      ) : null}

      {isLocked && stage.versionLog && (
        <div className="mt-3 rounded-md bg-muted/20 p-3 text-xs text-muted-foreground">
          <p>锁定版本：{stage.versionLog.versionId ?? '后端未返回版本号'}</p>
          {stage.versionLog.lockedAt && <p className="mt-1">锁定时间：{new Date(stage.versionLog.lockedAt).toLocaleString()}</p>}
          {stage.versionLog.diffFields?.length ? (
            <p className="mt-1">变更字段：{stage.versionLog.diffFields.join('、')}</p>
          ) : null}
        </div>
      )}

      {lockError && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          <span>{lockError}</span>
        </div>
      )}
    </div>
  )
}
