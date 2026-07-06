<template>
  <div class="learning-goals-page">
    <!-- 顶部工具栏 -->
    <div class="goals-toolbar">
      <div class="toolbar-left">
        <h3>🎯 学习目标</h3>
        <el-select
          v-model="selectedCourseId"
          placeholder="选择课程"
          clearable
          style="width: 200px"
          @change="loadGoals"
        >
          <el-option
            v-for="c in courses"
            :key="c.id"
            :label="c.name"
            :value="c.id"
          />
        </el-select>
      </div>
      <el-button type="primary" @click="showCreateDialog = true">
        + 新建目标
      </el-button>
    </div>

    <div class="goals-body" v-loading="loading">
      <!-- 左侧：目标列表 -->
      <div class="goals-list-panel">
        <div class="goals-list-header">
          <span>目标列表</span>
          <el-tag v-if="goals.length" size="small" type="info">{{ goals.length }}</el-tag>
        </div>
        <div class="goals-list" v-if="goals.length > 0">
          <div
            v-for="goal in goals"
            :key="goal.id"
            class="goal-item"
            :class="{ active: selectedGoal?.id === goal.id }"
            @click="selectGoal(goal)"
          >
            <div class="goal-item-title">{{ goal.title }}</div>
            <div class="goal-item-meta">
              <el-tag :type="statusTagType(goal.status)" size="small">
                {{ statusText(goal.status) }}
              </el-tag>
              <el-progress
                :percentage="Number(goal.progress_percent) || 0"
                :stroke-width="6"
                :show-text="false"
                style="flex: 1; margin-left: 8px"
              />
              <span class="goal-item-percent">{{ Number(goal.progress_percent) || 0 }}%</span>
            </div>
            <div class="goal-item-due" v-if="goal.due_date">
              截止：{{ goal.due_date }}
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无学习目标" :image-size="80" />
      </div>

      <!-- 右侧：目标详情 -->
      <div class="goals-detail-panel" v-if="selectedGoal">
        <!-- 从对话页跳转过来的提示（文档 Section 18） -->
        <el-alert
          v-if="advanceHintVisible"
          title="目标已创建，可以从第一步开始推进。"
          type="success"
          :closable="true"
          show-icon
          @close="advanceHintVisible = false"
          style="margin-bottom: 12px;"
        />
        <el-alert
          v-if="showAutoAdvanceHint"
          :title="autoAdvanceMessage"
          type="info"
          :closable="true"
          show-icon
          @close="showAutoAdvanceHint = false"
          style="margin-bottom: 12px;"
        />
        <div class="detail-header">
          <h4>{{ selectedGoal.title }}</h4>
          <div class="detail-actions">
            <!-- 推进目标主按钮（文档 Section 14.2-14.3） -->
            <el-button
              v-if="advanceMainAction === 'practice'"
              type="success"
              @click="handleAdvanceAction('practice')"
            >
              开始练习
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'document'"
              type="success"
              @click="handleAdvanceAction('document')"
            >
              阅读文档
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'read_explanation'"
              type="success"
              @click="handleAdvanceAction('read_explanation')"
            >
              阅读讲解
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'read_summary'"
              type="success"
              @click="handleAdvanceAction('read_summary')"
            >
              阅读总结
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'confirm_replan'"
              type="warning"
              @click="showReplanDialog = true"
            >
              确认重新规划
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'resolve_failure'"
              type="danger"
              @click="handleAdvanceAction('resolve_failure')"
            >
              查看失败
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'generate_plan'"
              type="success"
              @click="advanceGoal"
              :loading="advancing"
            >
              生成学习计划
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'advance'"
              type="primary"
              @click="advanceGoal"
              :loading="advancing"
            >
              推进目标
            </el-button>
            <!-- 自主推进按钮（文档 Section 23.2） -->
            <el-button
              v-if="['active','draft'].includes(selectedGoal.status) && advanceMainAction !== 'generate_plan'"
              type="success"
              @click="runGoalLoop"
              :loading="looping"
            >
              自主推进
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'replan_needed'"
              type="warning"
              @click="showReplanDialog = true"
            >
              需要重新规划
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'resume'"
              type="primary"
              @click="resumeGoal"
            >
              恢复目标
            </el-button>
            <el-button
              v-else-if="advanceMainAction === 'blocked'"
              type="info"
              disabled
            >
              {{ advanceBlockedReason || '暂不可推进' }}
            </el-button>
            <el-dropdown trigger="click" v-if="['active','paused'].includes(selectedGoal.status)">
              <el-button>更多操作<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="selectedGoal.status === 'active'" @click="pauseGoal">暂停目标</el-dropdown-item>
                  <el-dropdown-item @click="completeGoal">标记完成</el-dropdown-item>
                  <el-dropdown-item @click="showReplanDialog = true">重新规划</el-dropdown-item>
                  <el-dropdown-item divided @click="cancelGoal" style="color: #f56c6c">取消目标</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <el-descriptions :column="2" border size="small" class="detail-desc">
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(selectedGoal.status)">{{ statusText(selectedGoal.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="规划状态">{{ planningStatusText(selectedGoal.planning_status) }}</el-descriptions-item>
          <el-descriptions-item label="目标分数">{{ selectedGoal.target_score || '-' }}</el-descriptions-item>
          <el-descriptions-item label="当前分数">{{ selectedGoal.current_score || '-' }}</el-descriptions-item>
          <el-descriptions-item label="进度">
            <el-progress
              :percentage="Number(selectedGoal.progress_percent) || 0"
              :stroke-width="10"
            />
          </el-descriptions-item>
          <el-descriptions-item label="截止日期">{{ selectedGoal.due_date || '未设定' }}</el-descriptions-item>
          <el-descriptions-item label="目标描述" :span="2">{{ selectedGoal.goal_text }}</el-descriptions-item>
        </el-descriptions>

        <!-- 守护状态条（文档 Section 15.2） -->
        <div class="detail-section guardian-status-bar" v-if="guardianConfig">
          <div class="guardian-status-row">
            <div class="guardian-status-left">
              <span class="guardian-status-label">🛡 Agent 守护：</span>
              <el-tag :type="guardianConfig.enabled ? 'success' : 'info'" size="small">
                {{ guardianConfig.enabled ? '已开启' : '已关闭' }}
              </el-tag>
              <span class="guardian-level" v-if="guardianConfig.enabled">
                （{{ guardianLevelText(guardianConfig.guard_level) }}模式）
              </span>
              <span class="guardian-check-time" v-if="guardianConfig.last_checked_at">
                上次检查：{{ guardianTimeAgo(guardianConfig.last_checked_at) }}
              </span>
              <span class="guardian-check-time" v-if="guardianConfig.next_check_at && guardianConfig.enabled">
                下次检查：约 {{ guardianTimeAgo(guardianConfig.next_check_at) }}后
              </span>
            </div>
            <div class="guardian-status-right">
              <el-button size="small" text @click="runGuardianManually" :loading="runningGuardian">
                立即检查
              </el-button>
              <el-button size="small" text @click="openGuardianSettings">
                守护设置
              </el-button>
              <el-button size="small" text @click="showGuardianRuns = true" v-if="guardianRuns.length > 0">
                守护记录
              </el-button>
            </div>
          </div>
        </div>

        <!-- 守护提醒区域（文档 Section 15.3） -->
        <div class="detail-section guardian-events-area" v-if="guardianEvents.length > 0">
          <h5>🔔 Agent 提醒</h5>
          <div
            v-for="event in guardianEvents"
            :key="event.id"
            class="guardian-event-item"
            :class="'event-' + event.severity"
          >
            <div class="event-header">
              <el-tag :type="guardianEventSeverityTagType(event.severity)" size="small" effect="plain">
                {{ guardianEventTypeText(event.event_type) }}
              </el-tag>
              <span class="event-time">{{ guardianTimeAgo(event.created_at) }}</span>
            </div>
            <div class="event-message">{{ event.message || event.title }}</div>
            <div class="event-actions">
              <el-button
                v-if="event.action_type && event.action_payload"
                size="small"
                type="primary"
                text
                @click="handleGuardianEventAction(event)"
              >
                去完成
              </el-button>
              <el-button size="small" text @click="readGuardianEvent(event)">已读</el-button>
              <el-button size="small" text @click="dismissGuardianEvent(event)">忽略</el-button>
            </div>
          </div>
        </div>

        <!-- 计划摘要 -->
        <div class="detail-section" v-if="detailData.plan_summary">
          <h5>📋 计划摘要</h5>
          <p class="plan-summary-text">{{ cleanUserText(detailData.plan_summary) }}</p>
        </div>

        <!-- 目标推进控制台（文档 Section 14.2-14.3） -->
        <div class="detail-section advance-console" v-if="advanceConsoleInfo">
          <h5>🎮 目标推进</h5>
          <div class="advance-console-body">
            <div class="advance-console-row">
              <span class="advance-console-label">Agent 判断：</span>
              <span class="advance-console-value">{{ advanceConsoleInfo.judgment || '准备就绪' }}</span>
            </div>
            <div class="advance-console-row" v-if="advanceConsoleInfo.actionMessage">
              <span class="advance-console-label">当前需要：</span>
              <span class="advance-console-value advance-console-action">
                {{ advanceConsoleInfo.actionMessage }}
              </span>
            </div>
            <div class="advance-console-row" v-if="advanceConsoleInfo.lastResult">
              <span class="advance-console-label">最近推进：</span>
              <span class="advance-console-value">{{ advanceConsoleInfo.lastResult }}</span>
            </div>
          </div>
        </div>

        <!-- 步骤列表（增强版） -->
        <div class="detail-section">
          <h5>📝 学习步骤（{{ detailData.steps?.length || 0 }} 步）</h5>
          <div class="steps-list" v-if="detailData.steps?.length > 0">
            <div
              v-for="step in detailData.steps"
              :key="step.id"
              class="step-item"
              :class="'step-' + step.status"
            >
              <div class="step-order">{{ step.step_order }}</div>
              <div class="step-content">
                <div class="step-title">
                  {{ cleanUserText(step.title) }}
                  <el-tag
                    :type="stepStatusTagType(step.status)"
                    size="small"
                    class="step-status-tag"
                  >
                    {{ stepStatusText(step.status) }}
                  </el-tag>
                  <el-tag size="small" type="info" class="step-type-tag">
                    {{ stepTypeText(step.step_type) }}
                  </el-tag>
                  <el-tag
                    v-if="step.output_type"
                    size="small"
                    type=""
                    class="step-output-tag"
                  >
                    {{ outputTypeText(step.output_type) }}
                  </el-tag>
                </div>
                <div class="step-desc" v-if="step.description">{{ cleanUserText(step.description) }}</div>
                <div class="step-meta">
                  <span v-if="step.estimated_minutes">⏱ {{ step.estimated_minutes }} 分钟</span>
                  <span v-if="step.result_summary">📄 {{ cleanUserText(step.result_summary) }}</span>
                  <span v-if="step.last_error" class="step-error">❌ {{ cleanUserText(step.last_error) }}</span>
                </div>
                <!-- 步骤产物摘要 -->
                <div class="step-output-info" v-if="getStepOutputRef(step)">
                  <span v-if="getStepOutputType(step) === 'practice_session'">
                    📝 已生成练习
                    <template v-if="getStepOutputRef(step)?.question_count">
                      （{{ getStepOutputRef(step).question_count }} 题）
                    </template>
                  </span>
                  <span v-else-if="getStepOutputType(step) === 'document'">
                    📃 已生成练习文档
                  </span>
                </div>
                <!-- 最近复盘 -->
                <div class="step-reflection-mini" v-if="step.latest_reflection">
                  <el-tag
                    :type="step.latest_reflection.is_success ? 'success' : 'danger'"
                    size="small"
                    effect="plain"
                  >
                    复盘 {{ (step.latest_reflection.quality_score * 100).toFixed(0) }}分
                  </el-tag>
                  <span class="reflection-next" v-if="step.latest_reflection.next_action">
                    → {{ nextActionText(step.latest_reflection.next_action) }}
                  </span>
                </div>
                <!-- 操作按钮 -->
                <div class="step-actions">
                  <!-- 查看执行结果 -->
                  <el-button
                    v-if="step.latest_run"
                    size="small"
                    text
                    type="primary"
                    @click="openRunDetail(step)"
                  >
                    查看结果
                  </el-button>
                  <!-- 阅读讲解 -->
                  <el-button
                    v-if="canReadExplanation(step)"
                    size="small"
                    type="success"
                    plain
                    @click="openRunDetail(step, 'read_explanation')"
                  >
                    阅读讲解
                  </el-button>
                  <!-- 阅读总结 -->
                  <el-button
                    v-if="canReadSummary(step)"
                    size="small"
                    type="success"
                    plain
                    @click="openRunDetail(step, 'read_summary')"
                  >
                    阅读总结
                  </el-button>
                  <!-- 进入练习 -->
                  <el-button
                    v-if="canOpenPractice(step)"
                    size="small"
                    type="success"
                    @click="openPractice(step)"
                  >
                    {{ practiceButtonText(step) }}
                  </el-button>
                  <!-- 阅读文档 -->
                  <el-button
                    v-if="canOpenDocument(step)"
                    size="small"
                    type="success"
                    plain
                    @click="openDocument(step)"
                  >
                    阅读文档
                  </el-button>
                  <!-- 标记完成（文档/线下任务等） -->
                  <el-button
                    v-if="canManualComplete(step)"
                    size="small"
                    type="primary"
                    @click="openManualComplete(step)"
                  >
                    标记完成
                  </el-button>
                  <!-- 刷新复盘 -->
                  <el-button
                    v-if="step.latest_run"
                    size="small"
                    text
                    @click="refreshReflection(step)"
                    :loading="refreshingReflection === step.id"
                  >
                    刷新复盘
                  </el-button>
                </div>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无学习步骤，请先生成计划" :image-size="60" />
        </div>

        <!-- 最近自主推进记录（文档 Section 23） -->
        <div class="detail-section" v-if="loopRuns.length > 0">
          <h5>🔄 自主推进记录</h5>
          <div class="loop-runs-list">
            <div
              v-for="run in loopRuns.slice(0, 10)"
              :key="run.id"
              class="loop-run-item"
              @click="openLoopRunDetail(run)"
            >
              <div class="loop-run-icon">
                {{ loopStatusIcon(run.status) }}
              </div>
              <div class="loop-run-content">
                <div class="loop-run-header">
                  <span class="loop-run-summary">{{ run.summary || '推进完成' }}</span>
                  <el-tag
                    :type="loopStatusTagType(run.status)"
                    size="small"
                    effect="plain"
                  >
                    {{ loopStatusText(run.status) }}
                  </el-tag>
                  <span class="loop-run-time">{{ formatTime(run.started_at) || formatTime(run.created_at) }}</span>
                </div>
                <div class="loop-run-meta">
                  <span>完成 {{ run.completed_iterations }}/{{ run.max_iterations }} 轮</span>
                  <span v-if="run.stop_reason" style="margin-left: 12px">
                    停止原因：{{ loopStopReasonText(run.stop_reason) }}
                  </span>
                  <span v-if="run.action_required" style="margin-left: 12px">
                    <el-tag size="small" type="warning" effect="plain">
                      需要操作：{{ actionTypeText(run.action_type) }}
                    </el-tag>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 最近推进记录（文档 Section 14.4） -->
        <div class="detail-section" v-if="advanceCycles.length > 0">
          <h5>📜 最近推进记录</h5>
          <div class="advance-cycles-list">
            <div
              v-for="cycle in advanceCycles.slice(0, 10)"
              :key="cycle.id"
              class="advance-cycle-item"
              @click="openAdvanceCycleDetail(cycle)"
            >
              <div class="cycle-icon">
                {{ decisionTypeIcon(cycle.decision_type) }}
              </div>
              <div class="cycle-content">
                <div class="cycle-header">
                  <span class="cycle-action">{{ decisionTypeText(cycle.decision_type) }}</span>
                  <el-tag
                    :type="cycleStatusTagType(cycle.status)"
                    size="small"
                    effect="plain"
                  >
                    {{ cycleStatusText(cycle.status) }}
                  </el-tag>
                  <span class="cycle-time">{{ formatTime(cycle.started_at) }}</span>
                </div>
                <div class="cycle-reason" v-if="cycle.decision_reason">
                  {{ cycle.decision_reason }}
                </div>
                <div class="cycle-result" v-if="cycle.result_summary">
                  {{ cycle.result_summary }}
                </div>
                <div class="cycle-meta" v-if="cycle.action_required">
                  <el-tag size="small" type="warning" effect="plain">
                    需要操作：{{ actionTypeText(cycle.action_type) }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 最近复盘 -->
        <div class="detail-section" v-if="detailData.latest_reflections?.length > 0">
          <h5>🔍 最近复盘</h5>
          <div
            v-for="ref in detailData.latest_reflections.slice(0, 5)"
            :key="ref.id"
            class="reflection-item"
          >
            <div class="reflection-header">
              <el-tag :type="ref.is_success ? 'success' : 'danger'" size="small">
                {{ ref.is_success ? '成功' : '需关注' }}
              </el-tag>
              <span class="reflection-score" v-if="ref.quality_score !== null">
                质量分：{{ (ref.quality_score * 100).toFixed(0) }}
              </span>
              <span class="reflection-time">{{ formatTime(ref.created_at) }}</span>
            </div>
            <div class="reflection-summary">{{ ref.summary }}</div>
            <div class="reflection-action" v-if="ref.next_action">
              <el-tag size="small" type="warning" effect="plain">
                建议：{{ nextActionText(ref.next_action) }}
              </el-tag>
              <span v-if="ref.applied_action_status" class="applied-status">
                {{ ref.applied_action_status === 'applied' ? '✅ 已应用' : '⏳ 待处理' }}
              </span>
            </div>
            <div class="reflection-issues" v-if="ref.issues_json?.length > 0">
              <div v-for="(issue, idx) in ref.issues_json" :key="idx" class="issue-item">
                ⚠ {{ issue.message }}
              </div>
            </div>
          </div>
        </div>

        <!-- 执行结果 -->
        <div class="detail-section" v-if="runResult">
          <h5>📊 最近执行结果</h5>
          <el-alert
            :type="runResult.status === 'completed' || runResult.status === 'waiting_user_action' ? 'success' : 'warning'"
            :closable="false"
          >
            <template #title>{{ runResult.text }}</template>
          </el-alert>
          <div class="reflection-result" v-if="runResult.reflection">
            <div class="reflection-header">
              <el-tag :type="runResult.reflection.is_success ? 'success' : 'danger'" size="small">
                {{ runResult.reflection.is_success ? '复盘通过' : '需改进' }}
              </el-tag>
              <span v-if="runResult.reflection.quality_score !== null">
                质量分：{{ (runResult.reflection.quality_score * 100).toFixed(0) }}
              </span>
            </div>
            <div>{{ runResult.reflection.summary }}</div>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div class="goals-detail-panel goals-empty" v-else>
        <el-empty description="请选择一个目标查看详情" :image-size="120" />
      </div>
    </div>

    <!-- 创建目标对话框 -->
    <el-dialog v-model="showCreateDialog" title="新建学习目标" width="550px" :close-on-click-modal="false">
      <el-form :model="createForm" label-position="top">
        <el-form-item label="课程" required>
          <el-select v-model="createForm.course_id" placeholder="选择课程" style="width: 100%">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="目标标题">
          <el-input v-model="createForm.title" placeholder="30 天掌握操作系统进程与线程" />
        </el-form-item>
        <el-form-item label="目标描述" required>
          <el-input
            v-model="createForm.goal_text"
            type="textarea"
            :rows="3"
            placeholder="描述你的学习目标"
          />
        </el-form-item>
        <el-form-item label="目标分数">
          <el-input-number v-model="createForm.target_score" :min="0" :max="100" />
        </el-form-item>
        <el-form-item label="截止日期">
          <el-date-picker
            v-model="createForm.due_date"
            type="date"
            placeholder="选择截止日期"
            style="width: 100%"
            value-format="YYYY-MM-DD"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createGoal" :loading="creating">创建</el-button>
      </template>
    </el-dialog>

    <!-- 手动完成步骤对话框 -->
    <el-dialog v-model="showManualDialog" title="标记完成" width="450px">
      <el-form :model="manualForm" label-position="top">
        <el-form-item label="步骤">{{ manualStep?.title }}</el-form-item>
        <el-form-item label="完成说明">
          <el-input
            v-model="manualForm.result_summary"
            type="textarea"
            :rows="3"
            placeholder="描述你的完成情况"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showManualDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmManualComplete" :loading="completingManual">确认</el-button>
      </template>
    </el-dialog>

    <!-- 执行结果抽屉（文档 Section 11.4） -->
    <el-drawer
      v-model="runDrawerVisible"
      title="执行结果详情"
      size="500px"
      :close-on-click-modal="true"
    >
      <div class="run-drawer-body" v-if="currentRunDetail" v-loading="loadingRunDetail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="状态">
            <el-tag :type="currentRunDetail.status === 'completed' ? 'success' : 'danger'">
              {{ runStatusText(currentRunDetail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="执行内容">{{ toolNameText(currentRunDetail.tool_name) }}</el-descriptions-item>
          <el-descriptions-item label="产出类型">{{ outputTypeText(currentRunDetail.output_type) || '-' }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(currentRunDetail.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(currentRunDetail.finished_at) }}</el-descriptions-item>
          <el-descriptions-item v-if="currentRunDetail.error_message" label="错误信息">
            <span style="color: #f56c6c">{{ currentRunDetail.error_message }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <!-- QA 回答 -->
        <div class="drawer-section" v-if="currentRunDetail.qa">
          <h5>💬 答疑回答</h5>
          <div class="qa-content">
            <div class="qa-question"><strong>Q:</strong> {{ currentRunDetail.qa.question }}</div>
            <div class="qa-answer"><strong>A:</strong> {{ currentRunDetail.qa.answer }}</div>
          </div>
        </div>

        <!-- 阶段总结 -->
        <div class="drawer-section" v-if="currentRunSummary">
          <h5>📋 阶段总结</h5>
          <div class="summary-content">{{ cleanUserText(currentRunSummary) }}</div>
        </div>

        <!-- 阅读计时与完成（讲解 / 总结共用） -->
        <div v-if="activeUserAction && runDrawerVisible" class="drawer-section reading-timer">
          <el-tag :type="readSeconds >= 30 ? 'success' : 'warning'" size="small">
            {{ readSeconds >= 30 ? '已完成阅读' : `阅读计时：${readSeconds}秒 / ${activeUserAction.required_seconds || 30}秒` }}
          </el-tag>
          <el-button
            type="primary"
            size="small"
            style="margin-left: 8px"
            @click="completeReadingAction"
            :loading="completingReading"
          >
            我已读完
          </el-button>
        </div>

        <!-- 练习会话 -->
        <div class="drawer-section" v-if="currentRunDetail.practice_session">
          <h5>📝 练习会话</h5>
          <div class="practice-info">
            <p>题目数: {{ currentRunDetail.practice_session.question_count }}</p>
            <p>已作答: {{ currentRunDetail.practice_session.answered_count }}</p>
            <p>正确数: {{ currentRunDetail.practice_session.correct_count }}</p>
          </div>
          <el-button
            type="success"
            size="small"
            @click="openPracticeFromRun(currentRunDetail)"
          >
            {{ currentRunDetail.practice_session.status === 'completed' ? '查看练习' : '开始练习' }}
          </el-button>
        </div>

        <!-- 文档 -->
        <div class="drawer-section" v-if="currentRunDetail.generated_document">
          <h5>📃 练习文档</h5>
          <p>{{ currentRunDetail.generated_document.title || '已生成练习文档' }}</p>
          <div class="document-preview" v-if="currentRunDetail.generated_document.preview_content">
            {{ currentRunDetail.generated_document.preview_content.slice(0, 300) }}
          </div>
          <el-button type="success" size="small" @click="openDocumentFromRun(currentRunDetail)">
            阅读文档
          </el-button>
        </div>

        <!-- Agent 步骤 -->
        <div class="drawer-section" v-if="currentRunDetail.agent_steps?.length > 0">
          <h5>🤖 Agent 执行过程</h5>
          <div v-for="(as, idx) in currentRunDetail.agent_steps" :key="idx" class="agent-step-item">
            <el-tag size="small" :type="as.status === 'done' ? 'success' : 'info'">{{ cleanUserText(as.title) }}</el-tag>
            <span class="agent-step-detail" v-if="as.detail">: {{ cleanUserText(as.detail) }}</span>
          </div>
        </div>

        <!-- 工具结果 -->
        <div class="drawer-section" v-if="showDebugDetails && currentRunDetail.tool_result">
          <h5>执行原始记录</h5>
          <el-collapse>
            <el-collapse-item title="展开查看调试数据">
              <pre class="json-block">{{ JSON.stringify(currentRunDetail.tool_result, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>

        <!-- 复盘 -->
        <div class="drawer-section" v-if="currentRunDetail.reflection">
          <h5>🔍 复盘结果</h5>
          <div class="reflection-item">
            <div class="reflection-header">
              <el-tag :type="currentRunDetail.reflection.is_success ? 'success' : 'danger'" size="small">
                {{ currentRunDetail.reflection.is_success ? '通过' : '未通过' }}
              </el-tag>
              <span v-if="currentRunDetail.reflection.quality_score !== null">
                质量分：{{ (currentRunDetail.reflection.quality_score * 100).toFixed(0) }}
              </span>
            </div>
            <div>{{ currentRunDetail.reflection.summary }}</div>
            <div v-if="currentRunDetail.reflection.next_action" style="margin-top: 4px">
              <el-tag size="small" type="warning">建议：{{ nextActionText(currentRunDetail.reflection.next_action) }}</el-tag>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 文档阅读抽屉 -->
    <el-drawer
      v-model="documentDrawerVisible"
      title="练习文档"
      size="640px"
      :close-on-click-modal="true"
    >
      <div class="document-drawer-body" v-loading="loadingDocument">
        <template v-if="currentDocument">
          <div class="document-title">{{ currentDocument.title || '练习文档' }}</div>
          <pre class="document-content">{{ currentDocument.preview_content || '暂无可预览内容' }}</pre>
          <div class="document-actions">
            <el-button type="primary" @click="downloadCurrentDocument">下载文档</el-button>
            <el-button
              v-if="activeUserAction"
              type="success"
              @click="completeReadingAction"
              :loading="completingReading"
            >
              我已读完
            </el-button>
          </div>
          <div v-if="activeUserAction" class="reading-timer" style="margin-top:12px; text-align: center;">
            <el-tag :type="readSeconds >= 30 ? 'success' : 'warning'" size="small">
              {{ readSeconds >= 30 ? '已完成阅读' : `阅读计时：${readSeconds}秒 / ${activeUserAction.required_seconds || 30}秒` }}
            </el-tag>
          </div>
        </template>
      </div>
    </el-drawer>

    <!-- 练习面板（文档 Section 11.5） -->
    <el-drawer
      v-model="practicePanelVisible"
      title="目标练习"
      size="600px"
      :close-on-click-modal="true"
      @closed="practicePanelClosed"
    >
      <div class="practice-panel-body" v-if="currentPractice" v-loading="loadingPractice">
        <!-- 练习概览 -->
        <div class="practice-overview">
          <el-progress
            :percentage="Math.round((currentPractice.session.answered_count / currentPractice.session.question_count) * 100)"
            :stroke-width="12"
            color="#67c23a"
          />
          <p class="practice-stats">
            已作答 {{ currentPractice.session.answered_count }}/{{ currentPractice.session.question_count }} 题，
            正确 {{ currentPractice.session.correct_count }} 题
          </p>
        </div>

        <!-- 题目列表 -->
        <div class="practice-questions" v-if="currentPractice.questions?.length > 0">
          <div
            v-for="q in currentPractice.questions"
            :key="q.id"
            class="practice-question-card"
            :class="{ 'q-answered': q.status === 'answered', 'q-correct': q.is_correct, 'q-wrong': q.is_correct === false }"
          >
            <div class="q-header">
              <span class="q-no">第 {{ q.question_no }} 题</span>
              <el-tag v-if="q.status === 'answered'" :type="q.is_correct ? 'success' : 'danger'" size="small">
                {{ q.is_correct ? '正确' : '错误' }}
              </el-tag>
              <el-tag v-else size="small" type="info">未作答</el-tag>
            </div>
            <div class="q-stem">{{ q.stem }}</div>
            <div class="q-options" v-if="questionOptions(q).length > 0">
              <div
                v-for="opt in questionOptions(q)"
                :key="opt.key"
                class="q-option"
                :class="{
                  'opt-selected': selectedAnswers[q.question_no] === opt.key || q.submitted_answer === opt.key,
                  'opt-correct': q.status === 'answered' && q.is_correct && q.submitted_answer === opt.key,
                  'opt-wrong': q.status === 'answered' && !q.is_correct && q.submitted_answer === opt.key,
                }"
                @click="q.status !== 'answered' && selectOption(q, opt)"
              >
                <span class="opt-label">{{ opt.key }}</span>
                <span class="opt-text">{{ opt.text }}</span>
              </div>
            </div>
            <!-- 反馈 -->
            <div class="q-feedback" v-if="q.feedback_text">
              <el-alert
                :type="q.is_correct ? 'success' : 'error'"
                :closable="false"
                show-icon
              >
                {{ q.feedback_text }}
              </el-alert>
            </div>
            <!-- 解析 -->
            <div class="q-explanation" v-if="q.explanation && q.status === 'answered'">
              <p><strong>解析：</strong>{{ q.explanation }}</p>
            </div>
            <!-- 提交按钮 -->
            <div class="q-submit" v-if="q.status !== 'answered' && selectedAnswers[q.question_no]">
              <el-button
                type="primary"
                size="small"
                @click="submitAnswer(q)"
                :loading="submittingAnswer === q.question_no"
              >
                提交答案
              </el-button>
            </div>
          </div>
        </div>

        <!-- 练习完成状态 -->
        <div class="practice-complete" v-if="currentPractice.session.status === 'completed'">
          <el-result
            :icon="currentPractice.session.correct_count / currentPractice.session.question_count >= 0.6 ? 'success' : 'warning'"
            :title="currentPractice.session.correct_count / currentPractice.session.question_count >= 0.6 ? '练习完成！' : '需要加强'"
            :sub-title="`正确率 ${Math.round(currentPractice.session.correct_count / currentPractice.session.question_count * 100)}%`"
          >
            <template #extra>
              <el-button type="primary" @click="closePracticeAndRefresh">
                返回目标页
              </el-button>
            </template>
          </el-result>
        </div>
      </div>
    </el-drawer>

    <!-- 重新规划对话框 -->
    <el-dialog v-model="showReplanDialog" title="重新规划目标" width="500px">
      <el-form :model="replanForm" label-position="top">
        <el-form-item label="重新规划原因">
          <el-input
            v-model="replanForm.reason"
            type="textarea"
            :rows="3"
            placeholder="例如：练习结果显示某知识点仍薄弱，需要调整计划"
          />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="replanForm.preserve_completed_steps">保留已完成步骤</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showReplanDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmReplan" :loading="replanning">确认重新规划</el-button>
      </template>
    </el-dialog>

    <!-- 自主推进详情抽屉（文档 Section 23.4） -->
    <el-drawer
      v-model="loopDrawerVisible"
      title="自主推进详情"
      size="550px"
      :close-on-click-modal="true"
    >
      <div class="loop-drawer-body" v-if="currentLoopRun" v-loading="loadingLoopDetail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="状态">
            <el-tag :type="loopStatusTagType(currentLoopRun.status)">
              {{ loopStatusText(currentLoopRun.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="完成轮数">{{ currentLoopRun.completed_iterations }}/{{ currentLoopRun.max_iterations }}</el-descriptions-item>
          <el-descriptions-item label="停止原因">{{ loopStopReasonText(currentLoopRun.stop_reason) || '-' }}</el-descriptions-item>
          <el-descriptions-item v-if="currentLoopRun.action_required" label="需要操作">
            <el-tag type="warning">{{ actionTypeText(currentLoopRun.action_type) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="循环摘要">{{ currentLoopRun.summary || '-' }}</el-descriptions-item>
        </el-descriptions>

        <!-- 每轮详情 -->
        <div class="drawer-section" v-if="currentLoopRun.iterations?.length > 0">
          <h5>📋 执行轨迹</h5>
          <div
            v-for="it in currentLoopRun.iterations"
            :key="it.id"
            class="loop-iteration-card"
            :class="'iter-' + it.status"
          >
            <div class="iter-header">
              <span class="iter-no">第 {{ it.iteration_no }} 轮</span>
              <el-tag :type="it.status === 'completed' ? 'success' : 'danger'" size="small">
                {{ it.status === 'completed' ? '完成' : it.status }}
              </el-tag>
            </div>
            <div class="iter-detail" v-if="it.decision_type">
              <span class="iter-label">决策类型：</span>{{ decisionTypeText(it.decision_type) }}
            </div>
            <div class="iter-detail" v-if="it.action_summary">
              <span class="iter-label">执行内容：</span>{{ it.action_summary }}
            </div>
            <div class="iter-detail" v-if="it.evaluation?.reason">
              <span class="iter-label">评估结论：</span>{{ it.evaluation.reason }}
            </div>
            <div class="iter-detail" v-if="it.stop_reason">
              <span class="iter-label">停止原因：</span>{{ loopStopReasonText(it.stop_reason) }}
            </div>
            <div class="iter-detail" v-if="it.observation?.step">
              <span class="iter-label">关联步骤：</span>
              {{ it.observation.step.title }}（{{ stepStatusText(it.observation.step.status) }}）
            </div>
            <!-- 展开查看关联advance cycle -->
            <el-button
              v-if="it.advance_cycle && it.advance_cycle.decision_type"
              size="small"
              text
              type="primary"
              style="margin-top: 4px"
              @click="currentLoopRun._expandedIter = currentLoopRun._expandedIter === it.iteration_no ? null : it.iteration_no"
            >
              {{ currentLoopRun._expandedIter === it.iteration_no ? '收起详情' : '展开推进详情' }}
            </el-button>
            <div v-if="currentLoopRun._expandedIter === it.iteration_no && it.advance_cycle" class="iter-advance-expanded">
              <div class="cycle-reason" v-if="it.advance_cycle.decision_reason">
                判断依据：{{ it.advance_cycle.decision_reason }}
              </div>
              <div class="cycle-result" v-if="it.advance_cycle.result_summary">
                执行结果：{{ it.advance_cycle.result_summary }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 守护设置弹窗（文档 Section 15.4） -->
    <el-dialog v-model="showGuardianSettings" title="守护设置" width="500px" :close-on-click-modal="false">
      <el-form :model="guardianSettingsForm" label-position="top">
        <el-form-item label="开启守护">
          <el-switch v-model="guardianSettingsForm.enabled" />
          <span class="form-hint">Agent 只会准备学习材料和提醒你，不会替你完成阅读或练习。</span>
        </el-form-item>
        <el-form-item label="守护强度" v-if="guardianSettingsForm.enabled">
          <el-select v-model="guardianSettingsForm.guard_level" style="width: 100%">
            <el-option label="轻量 — 只提醒，不自动准备" value="light" />
            <el-option label="标准 — 可自动准备下一步" value="normal" />
            <el-option label="严格 — 更积极提醒和补救" value="strict" />
          </el-select>
        </el-form-item>
        <el-form-item label="检查间隔" v-if="guardianSettingsForm.enabled">
          <el-select v-model="guardianSettingsForm.check_interval_minutes" style="width: 100%">
            <el-option label="15 分钟" :value="15" />
            <el-option label="30 分钟" :value="30" />
            <el-option label="60 分钟" :value="60" />
            <el-option label="120 分钟" :value="120" />
          </el-select>
        </el-form-item>
        <el-form-item label="长时间未学习提醒" v-if="guardianSettingsForm.enabled">
          <el-select v-model="guardianSettingsForm.stale_action_hours" style="width: 100%">
            <el-option label="6 小时" :value="6" />
            <el-option label="12 小时" :value="12" />
            <el-option label="24 小时" :value="24" />
          </el-select>
        </el-form-item>
        <el-form-item label="截止日期提醒" v-if="guardianSettingsForm.enabled">
          <el-select v-model="guardianSettingsForm.due_soon_days" style="width: 100%">
            <el-option label="1 天" :value="1" />
            <el-option label="3 天" :value="3" />
            <el-option label="7 天" :value="7" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="guardianSettingsForm.enabled">
          <el-checkbox v-model="guardianSettingsForm.allow_auto_prepare">允许自动准备下一步</el-checkbox>
        </el-form-item>
        <el-form-item v-if="guardianSettingsForm.enabled">
          <el-checkbox v-model="guardianSettingsForm.allow_auto_remedial">允许自动插入补救步骤</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGuardianSettings = false">取消</el-button>
        <el-button type="primary" @click="saveGuardianConfig" :loading="savingGuardianConfig">保存设置</el-button>
      </template>
    </el-dialog>

    <!-- 守护记录抽屉（文档 Section 15.5） -->
    <el-drawer
      v-model="showGuardianRuns"
      title="守护记录"
      size="500px"
      :close-on-click-modal="true"
    >
      <div class="guardian-runs-body">
        <div
          v-for="run in guardianRuns"
          :key="run.id"
          class="guardian-run-item"
          :class="'run-' + run.status"
        >
          <div class="run-header">
            <el-tag :type="guardianRiskTagType(run.risk_level)" size="small" effect="plain">
              {{ guardianRiskText(run.risk_level) || '正常' }}
            </el-tag>
            <span class="run-trigger">{{ guardianTriggerTypeText(run.trigger_type) }}</span>
            <span class="run-time">{{ formatTime(run.started_at) }}</span>
          </div>
          <div class="run-summary" v-if="run.summary">{{ run.summary }}</div>
          <div class="run-status">
            <el-tag :type="run.status === 'completed' ? 'success' : run.status === 'failed' ? 'danger' : 'info'" size="small">
              {{ run.status === 'completed' ? '完成' : run.status === 'failed' ? '失败' : run.status }}
            </el-tag>
          </div>
        </div>
        <el-empty v-if="guardianRuns.length === 0" description="暂无守护记录" :image-size="80" />
      </div>
    </el-drawer>

    <!-- 插入补救步骤对话框 -->
    <el-dialog v-model="showRemedialDialog" title="插入补救步骤" width="500px">
      <el-form :model="remedialForm" label-position="top">
        <el-form-item label="参考步骤之后插入">
          <el-select v-model="remedialForm.after_step_id" placeholder="选择步骤" style="width: 100%">
            <el-option
              v-for="s in detailData.steps"
              :key="s.id"
              :label="`步骤 ${s.step_order}: ${s.title}`"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="步骤标题" required>
          <el-input v-model="remedialForm.title" placeholder="例如：补充线程同步讲解" />
        </el-form-item>
        <el-form-item label="步骤描述">
          <el-input v-model="remedialForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="步骤类型">
          <el-select v-model="remedialForm.step_type" style="width: 100%">
            <el-option label="知识讲解" value="qa_explanation" />
            <el-option label="对话练习" value="inline_practice" />
            <el-option label="诊断测验" value="diagnostic_quiz" />
            <el-option label="练习文档" value="exercise_document" />
            <el-option label="线下任务" value="manual_task" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRemedialDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmRemedial" :loading="insertingRemedial">确认插入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { agentGoalAPI, exerciseGenerationAPI } from '../api'
import { courseAPI } from '../api'

// ── 路由 ──────────────────────────────
const route = useRoute()

// ── 课程列表 ──────────────────────────────
const courses = ref([])

const loadCourses = async () => {
  try {
    const res = await courseAPI.list()
    courses.value = res.items || res || []
  } catch {
    // 课程加载失败不阻塞页面
  }
}

// ── 目标列表 ──────────────────────────────
const goals = ref([])
const selectedGoal = ref(null)
const selectedCourseId = ref(null)
const loading = ref(false)
const detailData = reactive({ steps: [], latest_reflections: [], plan_summary: '' })
const runResult = ref(null)
const showDebugDetails = false
const advancing = ref(false)
const advanceCycles = ref([])
const advanceCyclesDetailVisible = ref(false)
const advanceHintVisible = ref(false)
const currentAdvanceCycle = ref(null)

// ── 自主推进循环 ──────────────────────────
const looping = ref(false)
const loopRuns = ref([])
const loopDrawerVisible = ref(false)
const currentLoopRun = ref(null)
const loadingLoopDetail = ref(false)

// ── 用户动作阅读计时（文档 Section 16.3） ──
const activeUserAction = ref(null)
const readTimer = ref(null)
const readSeconds = ref(0)
const currentReadingStep = ref(null)
const autoAdvanceMessage = ref('')
const showAutoAdvanceHint = ref(false)
const autoAdvancePollTimer = ref(null)
const autoAdvancePolling = ref(false)

// ── 目标守护（文档 Section 15） ──
const guardianConfig = ref(null)
const guardianEvents = ref([])
const guardianRuns = ref([])
const showGuardianSettings = ref(false)
const showGuardianRuns = ref(false)
const guardianSettingsForm = reactive({
  enabled: true,
  guard_level: 'normal',
  check_interval_minutes: 60,
  stale_action_hours: 12,
  due_soon_days: 3,
  allow_auto_prepare: true,
  allow_auto_remedial: true,
})
const savingGuardianConfig = ref(false)
const runningGuardian = ref(false)
const guardianPollTimer = ref(null)

const internalLabelMap = {
  diagnostic_quiz: '诊断测验',
  qa_explanation: '知识讲解',
  inline_practice: '对话练习',
  exercise_document: '练习文档',
  review_summary: '阶段总结',
  recommendation_sync: '推荐同步',
  profile_check: '画像检查',
  manual_task: '线下任务',
  qa_answer: '知识讲解',
  generate_inline_practice: '对话练习',
  generate_exercise_document: '练习文档',
}

const cleanUserText = (text) => {
  if (!text) return text
  let value = String(text)
  Object.entries(internalLabelMap).forEach(([raw, label]) => {
    value = value.replace(new RegExp(`\\b${raw}\\b`, 'g'), label)
  })
  return value
    .replace(/[（(]\s*ID\s*=\s*\d+(?:\s*[,，]\s*\d+)*\s*[）)]/gi, '')
    .replace(/\bID\s*=\s*\d+(?:\s*[,，]\s*\d+)*\b/gi, '')
    .replace(/Session\s*#\d+/gi, '练习记录')
    .replace(/\s+([，。；、：])/g, '$1')
    .replace(/[（(]\s*[）)]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

const getStepOutputType = (step) => {
  if (step.output_type) return step.output_type
  if (step.latest_run?.output_type) return step.latest_run.output_type
  if (step.latest_run?.practice_session_id) return 'practice_session'
  if (step.latest_run?.generated_document_id) return 'document'
  return null
}

const getStepOutputRef = (step) => {
  if (step.output_ref) return step.output_ref
  if (step.latest_run?.output_ref) return step.latest_run.output_ref
  if (step.latest_run?.practice_session_id) {
    return {
      practice_session_id: step.latest_run.practice_session_id,
    }
  }
  if (step.latest_run?.generated_document_id) {
    return { document_id: step.latest_run.generated_document_id }
  }
  return null
}

const canOpenPractice = (step) =>
  getStepOutputType(step) === 'practice_session' && !!getStepOutputRef(step)?.practice_session_id

const practiceButtonText = (step) =>
  step.user_action_status === 'completed' ? '查看练习' : '开始练习'

const canOpenDocument = (step) =>
  getStepOutputType(step) === 'document' && !!getStepOutputRef(step)?.document_id

const canReadExplanation = (step) =>
  step.step_type === 'qa_explanation' && step.status === 'waiting_user_action' && !!step.latest_run

const canReadSummary = (step) =>
  step.step_type === 'review_summary' && step.status === 'waiting_user_action' && !!step.latest_run

const isReadingStep = (step) =>
  ['qa_explanation', 'review_summary', 'exercise_document'].includes(step.step_type) ||
  ['read_explanation', 'read_summary', 'read_document'].includes(step.user_action_type)

const canManualComplete = (step) =>
  ['blocked', 'pending', 'failed_retryable', 'waiting_user_action'].includes(step.status) &&
  !isReadingStep(step) &&
  !canOpenPractice(step)

// ── 目标推进控制台计算属性（文档 Section 14.2） ──
const advanceConsoleInfo = computed(() => {
  const action = detailData.current_agent_action
  const cycle = detailData.latest_advance_cycle
  if (!action && !cycle) return null

  const info = {
    judgment: null,
    actionMessage: null,
    lastResult: null,
  }

  // Agent 当前判断
  if (cycle?.decision_type) {
    info.judgment = decisionTypeJudgment(cycle.decision_type, cycle.decision_reason)
  } else if (selectedGoal.value?.planning_status === 'none') {
    info.judgment = '尚未生成学习计划'
  } else if (selectedGoal.value?.planning_status === 'planned') {
    info.judgment = '计划已就绪，可以推进'
  }

  // 当前需要用户做什么
  if (action) {
    info.actionMessage = action.message || actionTypeText(action.action_type)
  }

  // 最近一次推进结果
  if (cycle?.result_summary) {
    info.lastResult = cycle.result_summary
  }

  return info
})

const advanceMainAction = computed(() => {
  const goal = selectedGoal.value
  if (!goal) return null

  const action = detailData.current_agent_action

  // 优先使用 current_agent_action 的建议
  if (action) {
    if (action.action_type === 'practice_session') return 'practice'
    if (action.action_type === 'read_document') return 'document'
    if (action.action_type === 'read_explanation') return 'read_explanation'
    if (action.action_type === 'read_summary') return 'read_summary'
    if (action.action_type === 'confirm_replan') return 'confirm_replan'
    if (action.action_type === 'resolve_failure') return 'resolve_failure'
  }

  // 状态机判断
  if (goal.planning_status === 'none' || goal.planning_status === 'failed') return 'generate_plan'
  if (goal.planning_status === 'planning') return 'blocked'
  if (goal.planning_status === 'replan_needed') return 'replan_needed'
  if (goal.status === 'paused') return 'resume'
  if (goal.status === 'canceled' || goal.status === 'completed') return null
  if (goal.status === 'active' && goal.planning_status === 'planned') return 'advance'

  return null
})

const advanceBlockedReason = computed(() => {
  if (advanceMainAction.value !== 'blocked') return null
  if (selectedGoal.value?.planning_status === 'planning') return '计划生成中…'
  return null
})

const loadGoals = async () => {
  loading.value = true
  try {
    const params = {}
    if (selectedCourseId.value) params.courseId = selectedCourseId.value
    const res = await agentGoalAPI.list(params)
    goals.value = res || []
    if (selectedGoal.value) {
      const updated = goals.value.find(g => g.id === selectedGoal.value.id)
      if (updated) {
        selectedGoal.value = updated
      }
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    loading.value = false
  }
}

const selectGoal = async (goal, options = {}) => {
  if (!options.keepAutoAdvancePolling) {
    stopAutoAdvancePolling()
  }
  selectedGoal.value = goal
  runResult.value = null
  advanceCycles.value = []
  Object.assign(detailData, { steps: [], latest_reflections: [], plan_summary: '', current_agent_action: null, latest_advance_cycle: null })
  try {
    const res = await agentGoalAPI.get(goal.id)
    Object.assign(detailData, res)
    // 并行加载推进记录和循环记录
    loadAdvanceCycles()
    loadLoopRuns()
    // 加载守护数据
    loadGuardianConfig()
    loadGuardianEvents()
    loadGuardianRuns()
  } catch {
    // 错误已由拦截器处理
  }
}

// ── 刷新目标详情（用于阅读完成后自动刷新） ──
const refreshGoalDetail = async (options = {}) => {
  await loadGoals()
  if (selectedGoal.value) {
    await selectGoal(selectedGoal.value, options)
  }
}

const stopAutoAdvancePolling = () => {
  if (autoAdvancePollTimer.value) {
    clearInterval(autoAdvancePollTimer.value)
    autoAdvancePollTimer.value = null
  }
  autoAdvancePolling.value = false
}

const currentActionMessage = () => {
  if (selectedGoal.value?.status === 'completed') return '学习目标已完成'

  const action = detailData.current_agent_action
  if (action?.message) return action.message
  if (action?.action_type === 'practice_session') return '练习题已生成，可以开始练习'
  if (action?.action_type === 'read_document') return '学习文档已生成，可以开始阅读'
  if (action?.action_type === 'read_explanation') return '知识讲解已生成，可以开始阅读'
  if (action?.action_type === 'read_summary') return '阶段总结已生成，可以开始阅读'

  const waitingStep = detailData.steps?.find(s => s.status === 'waiting_user_action')
  if (!waitingStep) return ''
  if (canOpenPractice(waitingStep)) return `「${waitingStep.title}」练习题已生成，可以开始练习`
  if (canOpenDocument(waitingStep)) return `「${waitingStep.title}」文档已生成，可以开始阅读`
  if (canReadExplanation(waitingStep)) return `「${waitingStep.title}」讲解已生成，可以开始阅读`
  if (canReadSummary(waitingStep)) return `「${waitingStep.title}」总结已生成，可以开始阅读`
  return `「${waitingStep.title}」需要你继续操作`
}

const hasPendingAutoAdvance = () => {
  if (selectedGoal.value?.status === 'completed') return false
  const latestLoop = loopRuns.value?.[0]
  return latestLoop?.status === 'running'
}

const startAutoAdvancePolling = (message = 'Agent 正在准备下一步，完成后会自动刷新') => {
  stopAutoAdvancePolling()
  autoAdvanceMessage.value = message
  showAutoAdvanceHint.value = true
  autoAdvancePolling.value = true

  let attempts = 0
  autoAdvancePollTimer.value = setInterval(async () => {
    attempts += 1
    await refreshGoalDetail({ keepAutoAdvancePolling: true })
    const message = currentActionMessage()
    if (message) {
      autoAdvanceMessage.value = message
      showAutoAdvanceHint.value = true
      if (selectedGoal.value?.status === 'completed') {
        ElMessage.success(message)
      } else {
        ElMessage.success(message)
      }
      stopAutoAdvancePolling()
      return
    }
    if (!hasPendingAutoAdvance() && attempts >= 2) {
      autoAdvanceMessage.value = 'Agent 已完成本次推进'
      showAutoAdvanceHint.value = true
      stopAutoAdvancePolling()
      return
    }
    if (attempts >= 30) {
      autoAdvanceMessage.value = 'Agent 仍在准备下一步，请稍后查看'
      stopAutoAdvancePolling()
    }
  }, 3000)
}

// ── 创建目标 ──────────────────────────────
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = reactive({
  course_id: null,
  title: '',
  goal_text: '',
  target_score: 80,
  due_date: null,
})

const createGoal = async () => {
  if (!createForm.course_id) {
    ElMessage.warning('请选择课程')
    return
  }
  if (!createForm.goal_text.trim()) {
    ElMessage.warning('请输入目标描述')
    return
  }
  creating.value = true
  try {
    await agentGoalAPI.create({
      course_id: createForm.course_id,
      title: createForm.title || null,
      goal_text: createForm.goal_text,
      target_score: createForm.target_score,
      target_knowledge_point_ids: [],
      due_date: createForm.due_date || null,
    })
    ElMessage.success('目标创建成功')
    showCreateDialog.value = false
    Object.assign(createForm, { course_id: null, title: '', goal_text: '', target_score: 80, due_date: null })
    await loadGoals()
  } catch {
    // 错误已由拦截器处理
  } finally {
    creating.value = false
  }
}

// ── 生成计划 ──────────────────────────────
const planning = ref(false)

const generatePlan = async () => {
  planning.value = true
  try {
    const res = await agentGoalAPI.plan(selectedGoal.value.id)
    ElMessage.success(res.message || '学习计划已生成')
    await loadGoals()
    if (selectedGoal.value) {
      await selectGoal(selectedGoal.value)
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    planning.value = false
  }
}

// ── 推进目标（文档 Section 14.3） ──────────

const advanceGoal = async () => {
  advancing.value = true
  try {
    const res = await agentGoalAPI.advance(selectedGoal.value.id, {
      allow_generate_plan: true,
      allow_replan: false,
      allow_retry: true,
    })

    // 显示 user_message
    if (res.user_message) {
      if (res.status === 'completed') {
        ElMessage.success(res.user_message)
      } else if (res.status === 'waiting_user_action') {
        ElMessage.info(res.user_message)
      } else if (res.status === 'blocked' || res.status === 'failed') {
        ElMessage.warning(res.user_message)
      } else {
        ElMessage.info(res.user_message)
      }
    }

    // 自动打开执行结果抽屉（如果有 run）
    if (res.selected_run_id && res.run) {
      runResult.value = {
        run_id: res.run.id,
        run_uuid: res.run.run_uuid,
        goal_id: res.goal_id,
        step_id: res.selected_step_id,
        status: res.run.status,
        text: res.result_summary || res.user_message,
        reflection: res.reflection,
        agent_steps: [],
      }
    }

    // 如果返回练习 action，自动打开练习
    if (res.action_type === 'practice_session' && res.action_payload?.session_id) {
      const practiceStep = {
        id: res.selected_step_id,
        output_type: 'practice_session',
        output_ref: { practice_session_id: res.action_payload.session_id },
      }
      await openPractice(practiceStep)
    }

    // 如果返回文档 action，自动打开文档
    if (res.action_type === 'read_document' && res.action_payload?.document_id) {
      await openDocumentById(res.action_payload.document_id)
    }

    // 刷新目标和详情
    await loadGoals()
    if (selectedGoal.value) {
      await selectGoal(selectedGoal.value)
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    advancing.value = false
  }
}

// ── 自主推进（文档 Section 23.2） ──────────

const runGoalLoop = async () => {
  looping.value = true
  try {
    const res = await agentGoalAPI.runLoop(selectedGoal.value.id, {
      max_iterations: 3,
      max_seconds: 60,
      allow_generate_plan: true,
      allow_replan: false,
      allow_retry: true,
      stop_on_user_action: true,
    })

    // 显示摘要消息
    if (res.summary) {
      if (res.status === 'waiting_user_action') {
        ElMessage.info(res.summary)
      } else if (res.status === 'completed' || res.status === 'goal_completed') {
        ElMessage.success(res.summary)
      } else if (res.status === 'blocked' || res.status === 'failed') {
        ElMessage.warning(res.summary)
      } else {
        ElMessage.info(res.summary)
      }
    }

    // 如果返回练习 action，自动打开练习
    if (res.action_type === 'practice_session' && res.action_payload?.session_id) {
      const practiceStep = {
        output_type: 'practice_session',
        output_ref: { practice_session_id: res.action_payload.session_id },
      }
      await openPractice(practiceStep)
    }

    // 如果返回文档 action，自动打开文档
    if (res.action_type === 'read_document' && res.action_payload?.document_id) {
      await openDocumentById(res.action_payload.document_id)
    }

    // 刷新目标和详情
    await loadGoals()
    if (selectedGoal.value) {
      await selectGoal(selectedGoal.value)
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    looping.value = false
  }
}

// ── 加载自主推进记录 ──────────────────────

const loadLoopRuns = async () => {
  if (!selectedGoal.value) return
  try {
    loopRuns.value = await agentGoalAPI.loopRuns(selectedGoal.value.id, { limit: 10 })
  } catch {
    loopRuns.value = []
  }
}

// ── 打开自主推进详情 ──────────────────────

const openLoopRunDetail = async (run) => {
  loopDrawerVisible.value = true
  loadingLoopDetail.value = true
  currentLoopRun.value = null
  try {
    const detail = await agentGoalAPI.loopRunDetail(
      selectedGoal.value.id,
      run.id
    )
    detail._expandedIter = null
    currentLoopRun.value = detail
  } catch {
    ElMessage.error('获取循环详情失败')
    loopDrawerVisible.value = false
  } finally {
    loadingLoopDetail.value = false
  }
}

// ── 循环状态辅助 ──────────────────────────

const loopStatusIcon = (status) => {
  const map = {
    running: '▶️', completed: '✅', waiting_user_action: '👤',
    blocked: '🚫', failed: '❌', budget_exhausted: '⏰',
    goal_completed: '🎉', canceled: '🗑',
  }
  return map[status] || '🔄'
}

const loopStatusTagType = (status) => {
  const map = {
    running: '', completed: 'success', waiting_user_action: 'warning',
    blocked: 'info', failed: 'danger', budget_exhausted: 'warning',
    goal_completed: 'success', canceled: 'info',
  }
  return map[status] || 'info'
}

const loopStatusText = (status) => {
  const map = {
    running: '运行中', completed: '完成', waiting_user_action: '等待操作',
    blocked: '阻塞', failed: '失败', budget_exhausted: '预算耗尽',
    goal_completed: '目标完成', canceled: '已取消',
  }
  return map[status] || status
}

const loopStopReasonText = (reason) => {
  const map = {
    user_action_required: '需要用户操作',
    max_iterations_reached: '达到最大轮数',
    max_seconds_reached: '达到最大时间',
    goal_completed: '目标完成',
    replan_required: '需要重新规划',
    manual_task_required: '需要线下任务',
    failed_final: '步骤失败',
    blocked: '目标阻塞',
    no_action_available: '无可用动作',
    error: '异常',
  }
  return map[reason] || reason
}

// ── 处理推进动作（文档 Section 14.5）───────

const handleAdvanceAction = async (actionType) => {
  const action = detailData.current_agent_action
  if (!action) return

  if (actionType === 'practice' && action.payload?.session_id) {
    const practiceStep = {
      output_type: 'practice_session',
      output_ref: { practice_session_id: action.payload.session_id },
    }
    await openPractice(practiceStep)
  } else if (actionType === 'document' && action.payload?.document_id) {
    await openDocumentById(action.payload.document_id)
  } else if (actionType === 'read_explanation' || actionType === 'read_summary') {
    // 找到对应步骤并打开运行详情
    const waitStep = detailData.steps?.find(
      s => s.status === 'waiting_user_action' &&
        (s.step_type === 'qa_explanation' || s.step_type === 'review_summary')
    )
    if (waitStep && waitStep.latest_run) {
      const effectiveAction = waitStep.step_type === 'qa_explanation' ? 'read_explanation' : 'read_summary'
      await openRunDetail(waitStep, effectiveAction)
    }
  } else if (actionType === 'resolve_failure') {
    // 如果有失败的步骤，尝试打开其 run 详情
    const failedStep = detailData.steps?.find(
      s => s.status === 'failed_retryable' || s.status === 'failed_final' || s.status === 'blocked'
    )
    if (failedStep && failedStep.latest_run) {
      await openRunDetail(failedStep)
    } else if (failedStep) {
      ElMessage.warning(failedStep.last_error || '请查看步骤详情了解失败原因')
    }
  }
}

// ── 加载推进记录 ──────────────────────────

const loadAdvanceCycles = async () => {
  if (!selectedGoal.value) return
  try {
    advanceCycles.value = await agentGoalAPI.advanceCycles(selectedGoal.value.id, { limit: 10 })
  } catch {
    advanceCycles.value = []
  }
}

// ── 打开推进记录详情 ──────────────────────

const openAdvanceCycleDetail = async (cycle) => {
  try {
    currentAdvanceCycle.value = await agentGoalAPI.advanceCycleDetail(
      selectedGoal.value.id,
      cycle.id
    )
    advanceCyclesDetailVisible.value = true
  } catch {
    // 静默失败
  }
}

// ── 推进记录辅助文本 ──────────────────────

const decisionTypeIcon = (type) => {
  const map = {
    generate_plan: '📋', execute_step: '▶️', retry_step: '🔄',
    wait_user_action: '👤', refresh_reflection: '🔍', replan_goal: '📝',
    complete_goal: '🎉', blocked: '🚫', noop: '⏸️',
  }
  return map[type] || '❓'
}

const decisionTypeText = (type) => {
  const map = {
    generate_plan: '生成计划', execute_step: '执行步骤', retry_step: '重试步骤',
    wait_user_action: '等待操作', refresh_reflection: '刷新复盘', replan_goal: '重新规划',
    complete_goal: '完成目标', blocked: '阻塞', noop: '无动作',
  }
  return map[type] || type
}

const decisionTypeJudgment = (type, reason) => {
  const map = {
    generate_plan: '需要生成学习计划',
    execute_step: '准备执行下一步骤',
    retry_step: '准备重试失败步骤',
    wait_user_action: '需要用户完成当前操作',
    refresh_reflection: '需要刷新复盘',
    replan_goal: '需要重新规划目标',
    complete_goal: '目标已满足完成条件',
    blocked: '当前无法继续推进',
    noop: '当前无需推进',
  }
  return map[type] || reason || '准备就绪'
}

const cycleStatusTagType = (status) => {
  const map = { completed: 'success', waiting_user_action: 'warning', failed: 'danger', running: '', blocked: 'info' }
  return map[status] || 'info'
}

const cycleStatusText = (status) => {
  const map = { completed: '完成', waiting_user_action: '等待操作', failed: '失败', running: '执行中', blocked: '阻塞' }
  return map[status] || status
}

const actionTypeText = (type) => {
  const map = {
    practice_session: '完成练习', read_document: '阅读文档', manual_complete: '手动完成',
    confirm_replan: '确认重规划', resolve_failure: '处理失败', confirm_generate_plan: '确认生成计划',
  }
  return map[type] || type
}

// ── 暂停/恢复/取消/完成 ──────────────────
const pauseGoal = async () => {
  try {
    await ElMessageBox.confirm('确定要暂停此目标吗？', '确认', { type: 'warning' })
    await agentGoalAPI.pause(selectedGoal.value.id)
    ElMessage.success('目标已暂停')
    await loadGoals()
    if (selectedGoal.value) await selectGoal(selectedGoal.value)
  } catch {
    // 用户取消或错误
  }
}

const resumeGoal = async () => {
  try {
    await agentGoalAPI.resume(selectedGoal.value.id)
    ElMessage.success('目标已恢复')
    await loadGoals()
    if (selectedGoal.value) await selectGoal(selectedGoal.value)
  } catch {
    // 错误已由拦截器处理
  }
}

const cancelGoal = async () => {
  try {
    await ElMessageBox.confirm('确定要取消此目标吗？取消后不可恢复。', '确认取消', {
      type: 'error',
      confirmButtonText: '确认取消',
    })
    await agentGoalAPI.cancel(selectedGoal.value.id)
    ElMessage.success('目标已取消')
    await loadGoals()
    if (selectedGoal.value) await selectGoal(selectedGoal.value)
  } catch {
    // 用户取消或错误
  }
}

const completeGoal = async () => {
  try {
    await ElMessageBox.confirm('确定要标记此目标为完成吗？', '确认', { type: 'success' })
    await agentGoalAPI.complete(selectedGoal.value.id)
    ElMessage.success('目标已标记为完成')
    await loadGoals()
    if (selectedGoal.value) await selectGoal(selectedGoal.value)
  } catch {
    // 用户取消或错误
  }
}

// ── 手动完成步骤 ──────────────────────────
const showManualDialog = ref(false)
const completingManual = ref(false)
const manualStep = ref(null)
const manualForm = reactive({ result_summary: '' })

const openManualComplete = (step) => {
  manualStep.value = step
  manualForm.result_summary = ''
  showManualDialog.value = true
}

const confirmManualComplete = async () => {
  if (!manualForm.result_summary.trim()) {
    ElMessage.warning('请填写完成说明')
    return
  }
  completingManual.value = true
  try {
    await agentGoalAPI.completeStep(
      selectedGoal.value.id,
      manualStep.value.id,
      { result_summary: manualForm.result_summary }
    )
    ElMessage.success('步骤已标记完成')
    showManualDialog.value = false
    await loadGoals()
    if (selectedGoal.value) await selectGoal(selectedGoal.value)
  } catch {
    // 错误已由拦截器处理
  } finally {
    completingManual.value = false
  }
}

// ── 阅读计时（文档 Section 16.3） ──────────
const completingReading = ref(false)

const startStepUserAction = async (step, actionType, targetId = null) => {
  try {
    const res = await agentGoalAPI.startUserAction(
      selectedGoal.value.id,
      step.id,
      {
        action_type: actionType,
        target_type: 'run',
        target_id: targetId || step.latest_run?.id,
      }
    )
    activeUserAction.value = res
    readSeconds.value = res.accumulated_seconds || 0
    currentReadingStep.value = step
    return res
  } catch {
    // 启动失败，静默处理
    return null
  }
}

const startReadTimer = (step) => {
  stopReadTimer()
  readTimer.value = setInterval(async () => {
    if (!activeUserAction.value) {
      stopReadTimer()
      return
    }
    // 只有抽屉可见且页面活跃时才心跳（文档 Section 15.1）
    if (document.visibilityState !== 'visible') return
    if (!runDrawerVisible.value && !documentDrawerVisible.value) return

    try {
      const res = await agentGoalAPI.heartbeatUserAction(
        selectedGoal.value.id,
        step.id,
        {
          action_uuid: activeUserAction.value.action_uuid,
          visible: true,
          active_seconds: 5,
        }
      )
      readSeconds.value = res.accumulated_seconds || 0
      if (res.completed) {
        stopReadTimer()
        ElMessage.success('已完成阅读，Agent 正在准备下一步')
        handleAutoAdvanceResult(res.auto_advance_result)
        if (res.auto_advance_queued) {
          startAutoAdvancePolling('已完成阅读，Agent 正在准备下一步')
        }
        await refreshGoalDetail({ keepAutoAdvancePolling: true })
      }
    } catch {
      // 心跳失败，静默处理
    }
  }, 5000)
}

const stopReadTimer = () => {
  if (readTimer.value) {
    clearInterval(readTimer.value)
    readTimer.value = null
  }
}

const completeReadingAction = async () => {
  if (!activeUserAction.value) return
  completingReading.value = true
  try {
    const res = await agentGoalAPI.completeUserAction(
      selectedGoal.value.id,
      currentReadingStep.value.id,
      {
        action_uuid: activeUserAction.value.action_uuid,
        trigger_auto_advance: true,
      }
    )
    stopReadTimer()
    ElMessage.success('已标记完成，Agent 正在准备下一步')
    handleAutoAdvanceResult(res.auto_advance_result)
    if (res.auto_advance_queued) {
      startAutoAdvancePolling('已标记完成，Agent 正在准备下一步')
    }
    await refreshGoalDetail({ keepAutoAdvancePolling: true })
  } catch {
    ElMessage.error('标记完成失败')
  } finally {
    completingReading.value = false
  }
}

const handleAutoAdvanceResult = (result) => {
  if (!result) return
  if (result.summary) {
    autoAdvanceMessage.value = result.summary
    showAutoAdvanceHint.value = true
    ElMessage.info(result.summary)
  }
  // 如果推进生成了新的练习，提示
  if (result.action_type === 'practice_session') {
    autoAdvanceMessage.value = (result.summary || '') + ' 请开始练习。'
  }
  if (result.action_required) {
    setTimeout(() => {
      refreshGoalDetail({ keepAutoAdvancePolling: true })
    }, 500)
  }
}

const clearReadingState = () => {
  stopReadTimer()
  activeUserAction.value = null
  readSeconds.value = 0
  currentReadingStep.value = null
  autoAdvanceMessage.value = ''
  showAutoAdvanceHint.value = false
}

// ── 执行结果抽屉（文档 Section 11.4） ─────
const runDrawerVisible = ref(false)
const currentRunDetail = ref(null)
const loadingRunDetail = ref(false)

const currentRunSummary = computed(() => {
  const detail = currentRunDetail.value
  if (!detail) return ''
  return detail.tool_result?.summary ||
    detail.tool_result?.result_summary ||
    detail.step?.result_summary ||
    ''
})

const readingActionTypeForStep = (step) => {
  if (step.step_type === 'qa_explanation') return 'read_explanation'
  if (step.step_type === 'review_summary') return 'read_summary'
  if (step.step_type === 'exercise_document') return 'read_document'
  return step.user_action_type || null
}

const openRunDetail = async (step, actionType = null) => {
  runDrawerVisible.value = true
  loadingRunDetail.value = true
  currentRunDetail.value = null
  try {
    if (step.latest_run?.id) {
      const detail = await agentGoalAPI.runDetail(selectedGoal.value.id, step.latest_run.id)
      currentRunDetail.value = detail
    }
    const effectiveActionType = actionType || (
      step.status === 'waiting_user_action' ? readingActionTypeForStep(step) : null
    )
    if (effectiveActionType === 'read_explanation' || effectiveActionType === 'read_summary') {
      await startStepUserAction(step, effectiveActionType, step.latest_run?.id)
      startReadTimer(step)
    }
  } catch {
    ElMessage.error('获取执行详情失败')
    runDrawerVisible.value = false
  } finally {
    loadingRunDetail.value = false
  }
}

const openPracticeFromRun = async (runDetail) => {
  const step = detailData.steps.find(s => s.id === runDetail.step_id) || {
    id: runDetail.step_id,
    output_type: 'practice_session',
    output_ref: { practice_session_id: runDetail.practice_session?.id || runDetail.output_ref?.practice_session_id },
  }
  runDrawerVisible.value = false
  await openPractice(step)
}

const openDocumentFromRun = async (runDetail) => {
  const documentId = runDetail.generated_document?.id || runDetail.output_ref?.document_id
  if (!documentId) {
    ElMessage.warning('文档不存在')
    return
  }
  runDrawerVisible.value = false
  await openDocumentById(documentId)
}

// ── 练习面板（文档 Section 11.5） ─────────
const practicePanelVisible = ref(false)
const currentPractice = ref(null)
const currentPracticeStep = ref(null)
const loadingPractice = ref(false)
const submittingAnswer = ref(null)
const selectedAnswers = reactive({})

const openPractice = async (step) => {
  practicePanelVisible.value = true
  currentPracticeStep.value = step
  loadingPractice.value = true
  currentPractice.value = null
  // 清除之前的选项
  Object.keys(selectedAnswers).forEach(k => delete selectedAnswers[k])
  try {
    const sessionId = getStepOutputRef(step)?.practice_session_id
    if (!sessionId) {
      ElMessage.warning('练习会话不存在')
      practicePanelVisible.value = false
      return
    }
    const data = await agentGoalAPI.practiceDetail(selectedGoal.value.id, sessionId)
    currentPractice.value = data
  } catch {
    ElMessage.error('获取练习详情失败')
    practicePanelVisible.value = false
  } finally {
    loadingPractice.value = false
  }
}

const selectOption = (question, option) => {
  selectedAnswers[question.question_no] = option.key
}

const questionOptions = (question) => {
  const options = question?.options || []
  if (Array.isArray(options)) {
    return options.map((text, index) => ({
      key: String.fromCharCode(65 + index),
      text,
    }))
  }
  return Object.entries(options).map(([key, text]) => ({ key, text }))
}

const submitAnswer = async (question) => {
  const answer = selectedAnswers[question.question_no]
  if (!answer) {
    ElMessage.warning('请选择一个选项')
    return
  }
  submittingAnswer.value = question.question_no
  try {
    const sessionId = currentPracticeStep.value.output_ref?.practice_session_id
      || getStepOutputRef(currentPracticeStep.value)?.practice_session_id
    const res = await agentGoalAPI.submitPracticeAnswer(
      selectedGoal.value.id,
      sessionId,
      { question_no: question.question_no, submitted_answer: answer }
    )
    // 更新本地题目状态
    question.status = 'answered'
    question.submitted_answer = answer
    question.is_correct = res.is_correct
    question.feedback_text = res.feedback
    delete selectedAnswers[question.question_no]

    // 更新 session 计数
    if (currentPractice.value) {
      currentPractice.value.session.answered_count += 1
      if (res.is_correct) {
        currentPractice.value.session.correct_count += 1
      }
      if (res.session_completed) {
        currentPractice.value.session.status = 'completed'
        ElMessage.success('练习已完成！')
      }
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    submittingAnswer.value = null
  }
}

const closePracticeAndRefresh = async () => {
  practicePanelVisible.value = false
  currentPractice.value = null
  currentPracticeStep.value = null
  // 刷新目标详情
  await loadGoals()
  if (selectedGoal.value) {
    await selectGoal(selectedGoal.value)
  }
}

const practicePanelClosed = () => {
  currentPractice.value = null
  currentPracticeStep.value = null
}

// ── 文档阅读 ──────────────────────────────
const documentDrawerVisible = ref(false)
const currentDocument = ref(null)
const loadingDocument = ref(false)

const openDocument = async (step) => {
  const documentId = getStepOutputRef(step)?.document_id
  if (!documentId) {
    ElMessage.warning('文档不存在')
    return
  }
  // 保存 step 引用用于阅读计时
  currentReadingStep.value = step
  await openDocumentById(documentId, step)
}

const openDocumentById = async (documentId, step = null) => {
  documentDrawerVisible.value = true
  loadingDocument.value = true
  currentDocument.value = null
  try {
    currentDocument.value = await exerciseGenerationAPI.get(documentId)
    // 如果有步骤信息，启动文档阅读计时（文档 Section 17）
    const readingStep = step || currentReadingStep.value
    if (readingStep && readingStep.id) {
      await startStepUserAction(readingStep, 'read_document', documentId)
      startReadTimer(readingStep)
    }
  } catch {
    ElMessage.error('获取文档失败')
    documentDrawerVisible.value = false
  } finally {
    loadingDocument.value = false
  }
}

const downloadCurrentDocument = () => {
  if (!currentDocument.value?.id) return
  const token = localStorage.getItem('token')
  fetch(exerciseGenerationAPI.downloadUrl(currentDocument.value.id), {
    headers: { Authorization: `Bearer ${token}` },
  })
    .then(res => res.blob())
    .then(blob => {
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = currentDocument.value.file_name || '练习文档.md'
      a.click()
      URL.revokeObjectURL(blobUrl)
    })
}

// ── 刷新复盘 ──────────────────────────────
const refreshingReflection = ref(null)

const refreshReflection = async (step) => {
  refreshingReflection.value = step.id
  try {
    const res = await agentGoalAPI.refreshReflection(selectedGoal.value.id, step.id, { force_llm: false })
    ElMessage.success('复盘已刷新')
    // 重新加载详情
    if (selectedGoal.value) {
      await selectGoal(selectedGoal.value)
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    refreshingReflection.value = null
  }
}

// ── 重新规划（文档 Section 11.6） ──────────
const showReplanDialog = ref(false)
const replanning = ref(false)
const replanForm = reactive({ reason: '', preserve_completed_steps: true })

const confirmReplan = async () => {
  replanning.value = true
  try {
    const res = await agentGoalAPI.replan(selectedGoal.value.id, {
      reason: replanForm.reason || null,
      preserve_completed_steps: replanForm.preserve_completed_steps,
    })
    ElMessage.success(res.message || '目标已重新规划')
    showReplanDialog.value = false
    replanForm.reason = ''
    await loadGoals()
    if (selectedGoal.value) {
      await selectGoal(selectedGoal.value)
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    replanning.value = false
  }
}

// ── 插入补救步骤 ──────────────────────────
const showRemedialDialog = ref(false)
const insertingRemedial = ref(false)
const remedialForm = reactive({
  after_step_id: null,
  title: '',
  description: '',
  step_type: 'qa_explanation',
})

const confirmRemedial = async () => {
  if (!remedialForm.title.trim()) {
    ElMessage.warning('请输入步骤标题')
    return
  }
  if (!remedialForm.after_step_id) {
    ElMessage.warning('请选择参考步骤')
    return
  }
  insertingRemedial.value = true
  try {
    const toolNameMap = {
      qa_explanation: 'qa_answer',
      inline_practice: 'generate_inline_practice',
      diagnostic_quiz: 'generate_inline_practice',
      exercise_document: 'generate_exercise_document',
      manual_task: 'manual_task',
    }
    await agentGoalAPI.insertRemedialStep(selectedGoal.value.id, {
      after_step_id: remedialForm.after_step_id,
      title: remedialForm.title,
      description: remedialForm.description || null,
      step_type: remedialForm.step_type,
      tool_name: toolNameMap[remedialForm.step_type] || 'qa_answer',
      tool_args: {},
      target_knowledge_point_ids: [],
    })
    ElMessage.success('补救步骤已插入')
    showRemedialDialog.value = false
    Object.assign(remedialForm, { after_step_id: null, title: '', description: '', step_type: 'qa_explanation' })
    await loadGoals()
    if (selectedGoal.value) await selectGoal(selectedGoal.value)
  } catch {
    // 错误已由拦截器处理
  } finally {
    insertingRemedial.value = false
  }
}

// ── 状态映射 ──────────────────────────────

const statusTagType = (status) => {
  const map = { draft: 'info', active: 'success', paused: 'warning', completed: '', canceled: 'danger' }
  return map[status] || 'info'
}

const statusText = (status) => {
  const map = { draft: '草稿', active: '进行中', paused: '已暂停', completed: '已完成', canceled: '已取消' }
  return map[status] || status
}

const planningStatusText = (ps) => {
  const map = { none: '未规划', planning: '规划中', planned: '已规划', failed: '规划失败', replan_needed: '需重规划' }
  return map[ps] || ps
}

const runStatusText = (status) => {
  const map = {
    running: '执行中',
    completed: '已完成',
    waiting_user_action: '等待操作',
    failed: '执行失败',
    goal_completed: '目标已完成',
  }
  return map[status] || status || '-'
}

const stepStatusTagType = (status) => {
  const map = {
    pending: 'info', running: 'warning', completed: 'success',
    waiting_user_action: '', failed_retryable: 'danger', failed_final: 'danger',
    skipped: 'info', blocked: 'warning',
  }
  return map[status] || 'info'
}

const stepStatusText = (status) => {
  const map = {
    pending: '待执行', running: '执行中', completed: '已完成',
    waiting_user_action: '等待操作', failed_retryable: '失败(可重试)',
    failed_final: '失败(终局)', skipped: '已跳过', blocked: '需手动完成',
  }
  return map[status] || status
}

const stepTypeText = (type) => {
  const map = {
    diagnostic_quiz: '诊断测验', qa_explanation: '知识讲解', inline_practice: '对话练习',
    exercise_document: '练习文档', review_summary: '阶段总结', recommendation_sync: '推荐同步',
    profile_check: '画像检查', manual_task: '线下任务',
  }
  return map[type] || type
}

const outputTypeText = (type) => {
  const map = {
    qa: '答疑', practice_session: '练习', document: '文档',
    recommendation: '推荐', summary: '总结', manual: '线下',
  }
  return map[type] || type
}

const toolNameText = (toolName) => {
  const map = {
    qa_answer: '知识讲解',
    generate_inline_practice: '对话练习',
    generate_exercise_document: '练习文档',
    profile_check: '画像检查',
    recommendation_sync: '推荐同步',
    manual_task: '手动完成',
  }
  return map[toolName] || cleanUserText(toolName) || '-'
}

const nextActionText = (action) => {
  const map = {
    continue: '继续', retry_step: '建议重试', insert_remedial_step: '需补学',
    replan_needed: '需重规划', blocked_need_user: '需用户介入', complete_goal: '可完成目标',
  }
  return map[action] || action
}

const formatTime = (t) => {
  if (!t) return ''
  const d = new Date(t)
  return d.toLocaleString('zh-CN')
}

// ── 目标守护方法（文档 Section 15） ──

const loadGuardianConfig = async () => {
  if (!selectedGoal.value) return
  try {
    guardianConfig.value = await agentGoalAPI.guardianConfig(selectedGoal.value.id)
  } catch {
    guardianConfig.value = null
  }
}

const loadGuardianEvents = async () => {
  if (!selectedGoal.value) return
  try {
    guardianEvents.value = await agentGoalAPI.guardianEvents(selectedGoal.value.id, { status: 'unread', limit: 20 })
  } catch {
    guardianEvents.value = []
  }
}

const loadGuardianRuns = async () => {
  if (!selectedGoal.value) return
  try {
    guardianRuns.value = await agentGoalAPI.guardianRuns(selectedGoal.value.id, { limit: 20 })
  } catch {
    guardianRuns.value = []
  }
}

const openGuardianSettings = () => {
  if (guardianConfig.value) {
    Object.assign(guardianSettingsForm, {
      enabled: guardianConfig.value.enabled,
      guard_level: guardianConfig.value.guard_level,
      check_interval_minutes: guardianConfig.value.check_interval_minutes,
      stale_action_hours: guardianConfig.value.stale_action_hours,
      due_soon_days: guardianConfig.value.due_soon_days,
      allow_auto_prepare: guardianConfig.value.allow_auto_prepare,
      allow_auto_remedial: guardianConfig.value.allow_auto_remedial,
    })
  }
  showGuardianSettings.value = true
}

const saveGuardianConfig = async () => {
  savingGuardianConfig.value = true
  try {
    const res = await agentGoalAPI.updateGuardianConfig(selectedGoal.value.id, guardianSettingsForm)
    guardianConfig.value = res
    ElMessage.success('守护设置已保存')
    showGuardianSettings.value = false
  } catch {
    // 错误已由拦截器处理
  } finally {
    savingGuardianConfig.value = false
  }
}

const runGuardianManually = async () => {
  runningGuardian.value = true
  try {
    const res = await agentGoalAPI.runGuardian(selectedGoal.value.id)
    ElMessage.success(res.summary || '守护检查完成')
    await loadGuardianConfig()
    await loadGuardianEvents()
    await loadGuardianRuns()
    // 如果有自动准备，触发刷新
    if (res.auto_prepare_triggered) {
      startAutoAdvancePolling('Agent 正在准备下一步，完成后会自动刷新')
    }
  } catch {
    // 错误已由拦截器处理
  } finally {
    runningGuardian.value = false
  }
}

const readGuardianEvent = async (event) => {
  try {
    await agentGoalAPI.readGuardianEvent(selectedGoal.value.id, event.id)
    event.status = 'read'
    guardianEvents.value = guardianEvents.value.filter(e => e.id !== event.id)
  } catch {
    // 静默失败
  }
}

const dismissGuardianEvent = async (event) => {
  try {
    await agentGoalAPI.dismissGuardianEvent(selectedGoal.value.id, event.id)
    guardianEvents.value = guardianEvents.value.filter(e => e.id !== event.id)
  } catch {
    // 静默失败
  }
}

const handleGuardianEventAction = (event) => {
  if (!event.action_type || !event.action_payload) return
  const payload = event.action_payload

  if (event.action_type === 'read_document' && payload.document_id) {
    openDocumentById(payload.document_id)
  } else if (event.action_type === 'read_explanation' || event.action_type === 'read_summary') {
    const step = detailData.steps?.find(s => s.id === payload.step_id)
    if (step) {
      const actionType = event.action_type
      openRunDetail(step, actionType)
    }
  } else if (event.action_type === 'practice_session' && payload.practice_session_id) {
    const practiceStep = {
      output_type: 'practice_session',
      output_ref: { practice_session_id: payload.practice_session_id },
    }
    openPractice(practiceStep)
  } else if (event.action_type === 'advance_goal') {
    advanceGoal()
  }

  // 自动标记已读
  readGuardianEvent(event)
}

const startGuardianPolling = () => {
  stopGuardianPolling()
  guardianPollTimer.value = setInterval(async () => {
    if (!selectedGoal.value) return
    if (document.visibilityState !== 'visible') return

    try {
      const events = await agentGoalAPI.guardianEvents(selectedGoal.value.id, { status: 'unread', limit: 20 })
      guardianEvents.value = events || []

      // 发现 auto_prepare_finished 时刷新目标详情
      const hasAutoPrepareFinished = events.some(e => e.event_type === 'auto_prepare_finished')
      if (hasAutoPrepareFinished) {
        await refreshGoalDetail({ keepAutoAdvancePolling: true })
      }
    } catch {
      // 静默失败
    }
  }, 30000) // 每 30 秒轻量刷新
}

const stopGuardianPolling = () => {
  if (guardianPollTimer.value) {
    clearInterval(guardianPollTimer.value)
    guardianPollTimer.value = null
  }
}

const guardianRiskTagType = (level) => {
  const map = { info: 'info', success: 'success', warning: 'warning', danger: 'danger' }
  return map[level] || 'info'
}

const guardianRiskText = (level) => {
  const map = { info: '正常', success: '已完成', warning: '注意', danger: '高风险' }
  return map[level] || level
}

const guardianLevelText = (level) => {
  const map = { light: '轻量', normal: '标准', strict: '严格' }
  return map[level] || level
}

const guardianEventSeverityTagType = (severity) => {
  const map = { info: 'info', success: 'success', warning: 'warning', danger: 'danger' }
  return map[severity] || 'info'
}

const guardianEventTypeText = (type) => {
  const map = {
    stale_user_action: '等待完成', due_soon: '截止临近', progress_lag: '进度落后',
    low_quality: '质量偏低', remedial_inserted: '已添加补救', auto_prepare_started: '准备中',
    auto_prepare_finished: '准备完成', goal_completed: '目标完成', daily_review: '每日复盘',
    replan_suggested: '建议重规划',
  }
  return map[type] || type
}

const guardianTriggerTypeText = (type) => {
  const map = { scheduler: '定时检查', manual: '手动检查', user_action_completed: '操作后检查', practice_completed: '练习后检查' }
  return map[type] || type
}

const guardianTimeAgo = (t) => {
  if (!t) return ''
  const diff = Date.now() - new Date(t).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

// ── 初始化 ──────────────────────────────
onMounted(async () => {
  await loadCourses()
  await loadGoals()

  // 支持从对话页跳转：自动选中目标（文档 Section 18）
  const queryGoalId = route.query.goalId
  const queryAction = route.query.action

  if (queryGoalId) {
    const goalId = Number(queryGoalId)
    const goal = goals.value.find(g => g.id === goalId)
    if (goal) {
      await selectGoal(goal)
      // 如果有 advance action，显示提示但不自动执行
      if (queryAction === 'advance') {
        advanceHintVisible.value = true
      }
    }
  }

  // 启动守护事件轮询（文档 Section 16）
  startGuardianPolling()
})

// ── 抽屉关闭时停止阅读计时（文档 Section 21，任务 E） ──
watch([runDrawerVisible, documentDrawerVisible], ([runOpen, docOpen]) => {
  if (!runOpen && !docOpen) {
    stopReadTimer()
    // 保留 action started 状态，下次打开可继续
  }
})

onUnmounted(() => {
  stopReadTimer()
  stopAutoAdvancePolling()
  stopGuardianPolling()
})
</script>

<style scoped>
.learning-goals-page {
  max-width: 1400px;
  margin: 0 auto;
}

.goals-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.toolbar-left h3 {
  font-size: 18px;
  white-space: nowrap;
  margin: 0;
}

.goals-body {
  display: flex;
  gap: 16px;
  min-height: calc(100vh - 160px);
}

/* 左侧列表 */
.goals-list-panel {
  width: 320px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  padding: 12px;
  overflow-y: auto;
  max-height: calc(100vh - 160px);
}

.goals-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 4px 8px;
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 8px;
}

.goal-item {
  padding: 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  border: 1px solid transparent;
  margin-bottom: 4px;
}

.goal-item:hover {
  background: #f5f7fa;
}

.goal-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}

.goal-item-title {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.goal-item-meta {
  display: flex;
  align-items: center;
  gap: 4px;
}

.goal-item-percent {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

.goal-item-due {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 4px;
}

/* 右侧详情 */
.goals-detail-panel {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  padding: 20px;
  overflow-y: auto;
  max-height: calc(100vh - 160px);
}

.goals-empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
}

.detail-header h4 {
  font-size: 18px;
  margin: 0;
}

.detail-actions {
  display: flex;
  gap: 8px;
}

.detail-desc {
  margin-bottom: 20px;
}

.detail-section {
  margin-top: 20px;
}

.detail-section h5 {
  font-size: 15px;
  margin-bottom: 12px;
  color: #303133;
}

.plan-summary-text {
  color: #606266;
  line-height: 1.6;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

/* 步骤列表 */
.steps-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  transition: border-color 0.2s;
}

.step-item.step-completed {
  border-color: #c0e0c0;
  background: #f0f9f0;
}

.step-item.step-waiting_user_action {
  border-color: #409eff;
  background: #ecf5ff;
}

.step-item.step-running {
  border-color: #409eff;
  background: #ecf5ff;
}

.step-item.step-failed_retryable,
.step-item.step-failed_final {
  border-color: #f89898;
  background: #fef0f0;
}

.step-item.step-blocked {
  border-color: #e6a23c;
  background: #fdf6ec;
}

.step-order {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
  min-width: 0;
}

.step-title {
  font-size: 14px;
  font-weight: 500;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.step-status-tag,
.step-type-tag,
.step-output-tag {
  flex-shrink: 0;
}

.step-desc {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.step-meta {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 4px;
  display: flex;
  gap: 12px;
}

.step-error {
  color: #f56c6c;
}

.step-output-info {
  font-size: 12px;
  color: #409eff;
  margin-top: 4px;
}

.step-reflection-mini {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.reflection-next {
  font-size: 12px;
  color: #e6a23c;
}

.step-actions {
  margin-top: 8px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

/* 复盘 */
.reflection-item {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
}

.reflection-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.reflection-score {
  font-size: 13px;
  color: #606266;
}

.reflection-time {
  font-size: 12px;
  color: #c0c4cc;
  margin-left: auto;
}

.reflection-summary {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}

.reflection-action {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.applied-status {
  font-size: 12px;
  color: #909399;
}

.reflection-issues {
  margin-top: 6px;
}

.issue-item {
  font-size: 12px;
  color: #e6a23c;
  padding: 2px 0;
}

.reflection-result {
  margin-top: 12px;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 6px;
}

.reflection-result .reflection-header {
  margin-bottom: 8px;
}

/* 执行结果抽屉 */
.run-drawer-body {
  padding: 0 4px;
}

.drawer-section {
  margin-top: 20px;
}

.drawer-section h5 {
  font-size: 14px;
  margin-bottom: 8px;
  color: #303133;
}

.qa-content {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
}

.qa-question {
  margin-bottom: 8px;
  color: #606266;
}

.qa-answer {
  color: #303133;
  line-height: 1.6;
}

.practice-info p {
  font-size: 13px;
  color: #606266;
  margin: 4px 0;
}

.document-preview {
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
  background: #f5f7fa;
  border-radius: 6px;
  padding: 10px;
  margin: 8px 0 12px;
  white-space: pre-wrap;
}

.document-drawer-body {
  padding: 0 4px;
}

.document-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}

.document-content {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 16px;
  line-height: 1.8;
  font-size: 14px;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: calc(100vh - 230px);
  overflow: auto;
}

.document-actions {
  margin-top: 12px;
}

.agent-step-item {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 4px 0;
}

.agent-step-detail {
  font-size: 12px;
  color: #909399;
}

.json-block {
  background: #f5f7fa;
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 练习面板 */
.practice-panel-body {
  padding: 0 4px;
}

.practice-overview {
  margin-bottom: 20px;
}

.practice-stats {
  text-align: center;
  font-size: 14px;
  color: #606266;
  margin-top: 8px;
}

.practice-questions {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.practice-question-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px;
  transition: border-color 0.2s;
}

.practice-question-card.q-answered {
  border-color: #c0e0c0;
}

.practice-question-card.q-correct {
  background: #f0f9f0;
}

.practice-question-card.q-wrong {
  background: #fef0f0;
}

.q-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.q-no {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.q-stem {
  font-size: 14px;
  color: #303133;
  line-height: 1.6;
  margin-bottom: 12px;
}

.q-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.q-option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.q-option:hover {
  border-color: #409eff;
  background: #ecf5ff;
}

.q-option.opt-selected {
  border-color: #409eff;
  background: #ecf5ff;
}

.q-option.opt-correct {
  border-color: #67c23a;
  background: #f0f9f0;
}

.q-option.opt-wrong {
  border-color: #f56c6c;
  background: #fef0f0;
}

.opt-label {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #f5f7fa;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 12px;
  flex-shrink: 0;
}

.opt-text {
  font-size: 13px;
  color: #303133;
}

.q-feedback {
  margin-top: 12px;
}

.q-explanation {
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 4px;
}

.q-submit {
  margin-top: 12px;
  text-align: right;
}

.practice-complete {
  margin-top: 20px;
}

/* 目标推进控制台 */
.advance-console {
  background: linear-gradient(135deg, #ecf5ff, #f0f9ff);
  border: 1px solid #b3d8ff;
  border-radius: 10px;
  padding: 16px;
}

.advance-console-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.advance-console-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 14px;
}

.advance-console-label {
  color: #606266;
  font-weight: 500;
  white-space: nowrap;
  min-width: 90px;
}

.advance-console-value {
  color: #303133;
}

.advance-console-action {
  color: #409eff;
  font-weight: 500;
}

/* 推进记录时间线 */
.advance-cycles-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.advance-cycle-item {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.advance-cycle-item:hover {
  background: #f5f7fa;
}

.cycle-icon {
  font-size: 20px;
  flex-shrink: 0;
  width: 32px;
  text-align: center;
}

.cycle-content {
  flex: 1;
  min-width: 0;
}

.cycle-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cycle-action {
  font-weight: 500;
  font-size: 13px;
  color: #303133;
}

.cycle-time {
  font-size: 12px;
  color: #c0c4cc;
  margin-left: auto;
}

.cycle-reason {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.cycle-result {
  font-size: 12px;
  color: #606266;
  margin-top: 2px;
}

.cycle-meta {
  margin-top: 4px;
}

/* 自主推进记录 */
.loop-runs-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.loop-run-item {
  display: flex;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s;
}

.loop-run-item:hover {
  background: #f5f7fa;
}

.loop-run-icon {
  font-size: 20px;
  flex-shrink: 0;
  width: 32px;
  text-align: center;
}

.loop-run-content {
  flex: 1;
  min-width: 0;
}

.loop-run-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.loop-run-summary {
  font-weight: 500;
  font-size: 13px;
  color: #303133;
}

.loop-run-time {
  font-size: 12px;
  color: #c0c4cc;
  margin-left: auto;
}

.loop-run-meta {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  display: flex;
  align-items: center;
}

/* 自主推进详情抽屉 */
.loop-drawer-body {
  padding: 0 4px;
}

.loop-iteration-card {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  margin-bottom: 8px;
  transition: border-color 0.2s;
}

.loop-iteration-card.iter-completed {
  border-color: #c0e0c0;
  background: #f0f9f0;
}

.loop-iteration-card.iter-failed {
  border-color: #f89898;
  background: #fef0f0;
}

.loop-iteration-card.iter-waiting_user_action {
  border-color: #409eff;
  background: #ecf5ff;
}

.iter-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.iter-no {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}

.iter-detail {
  font-size: 13px;
  color: #606266;
  margin-top: 2px;
  line-height: 1.5;
}

.iter-label {
  font-weight: 500;
  color: #909399;
}

.iter-advance-expanded {
  margin-top: 8px;
  padding: 8px 10px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 12px;
  color: #606266;
}

/* ── 目标守护样式（文档 Section 15） ── */

.guardian-status-bar {
  background: linear-gradient(135deg, #f0f9ff, #ecfdf5);
  border: 1px solid #b3e5d8;
  border-radius: 10px;
  padding: 12px 16px;
}

.guardian-status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.guardian-status-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #606266;
}

.guardian-status-label {
  font-weight: 600;
  color: #303133;
}

.guardian-level {
  color: #909399;
  font-size: 12px;
}

.guardian-check-time {
  color: #909399;
  font-size: 12px;
}

.guardian-status-right {
  display: flex;
  gap: 4px;
}

.guardian-events-area {
  background: #fff8e6;
  border: 1px solid #f5dab1;
  border-radius: 10px;
  padding: 12px 16px;
}

.guardian-event-item {
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 8px;
  background: #fff;
  border: 1px solid #ebeef5;
}

.guardian-event-item:last-child {
  margin-bottom: 0;
}

.guardian-event-item.event-danger {
  border-left: 3px solid #f56c6c;
}

.guardian-event-item.event-warning {
  border-left: 3px solid #e6a23c;
}

.guardian-event-item.event-info {
  border-left: 3px solid #909399;
}

.guardian-event-item.event-success {
  border-left: 3px solid #67c23a;
}

.event-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.event-time {
  font-size: 12px;
  color: #c0c4cc;
}

.event-message {
  font-size: 14px;
  color: #303133;
  line-height: 1.5;
  margin-bottom: 6px;
}

.event-actions {
  display: flex;
  gap: 4px;
}

.form-hint {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

/* 守护记录 */
.guardian-runs-body {
  padding: 0 4px;
}

.guardian-run-item {
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  margin-bottom: 8px;
}

.guardian-run-item:last-child {
  margin-bottom: 0;
}

.run-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.run-trigger {
  font-size: 13px;
  color: #606266;
  flex: 1;
}

.run-time {
  font-size: 12px;
  color: #c0c4cc;
}

.run-summary {
  font-size: 13px;
  color: #303133;
  line-height: 1.5;
  margin-bottom: 4px;
}
</style>
