import React, { useState } from 'react';
import { LunaChat } from './LunaChat';
import type { ChatPosition } from '../lunaChat';
import type { ChessTheme, CoachDetail, CoachLanguage, CoachResult } from '../coach';
import type { TtsStatus } from '../tts';

export type CriticalPrompt = {
  mateThreat?: boolean;
  kind: 'threat' | 'opportunity' | 'decision' | 'check';
  title: string;
  question: string;
  ply: number;
};

export type CoachNote = CoachResult & {
  gameId: string;
  savedAt: number;
  playerColor: 'white' | 'black';
  language?: CoachLanguage;
};

type Props = {
  chatSessionId: string;
  chatPosition: ChatPosition;
  onSpeakChat?: (text: string) => void;
  openingLabel: string;
  openingStatus: string;
  historyStatus: 'syncing' | 'synced' | 'offline' | 'unavailable';
  coachResult: CoachResult | null;
  coachThinking: boolean;
  coachError: string | null;
  criticalPrompt: CriticalPrompt | null;
  coachNotes: CoachNote[];
  isMyTurn: boolean;
  voiceEnabled: boolean;
  onToggleVoice: (enabled: boolean) => void;
  ttsStatus: TtsStatus;
  hintsEnabled: boolean;
  onToggleHints: (enabled: boolean) => void;
  coachDetail: CoachDetail;
  onChangeCoachDetail: (detail: CoachDetail) => void;
  coachLanguage: CoachLanguage;
  onChangeCoachLanguage: (lang: CoachLanguage) => void;
  onReviewPosition: (result: CoachResult) => void;
  onSelectPly: (ply: number) => void;
  currentPly: number | null;
  themeLabel: (theme: ChessTheme, lang: CoachLanguage) => string;
};

export const CoachWindow: React.FC<Props> = ({
  chatSessionId,
  chatPosition,
  onSpeakChat,
  openingLabel,
  openingStatus,
  historyStatus,
  coachResult,
  coachThinking,
  coachError,
  criticalPrompt,
  coachNotes,
  isMyTurn,
  voiceEnabled,
  onToggleVoice,
  ttsStatus,
  hintsEnabled,
  onToggleHints,
  coachDetail,
  onChangeCoachDetail,
  coachLanguage,
  onChangeCoachLanguage,
  onReviewPosition,
  onSelectPly,
  currentPly,
  themeLabel,
}) => {
  const isChinese = coachLanguage === 'zh-CN';
  const isSpeaking = ttsStatus.state === 'speaking';
  const [mode, setMode] = useState<'coach' | 'chat'>('coach');

  return (
    <div className="coach-window-panel">
      {/* Coach Window Titlebar */}
      <div className="coach-window-header">
        <div className="coach-window-identity">
          <div className="coach-window-avatar">
            <span className="coach-avatar-glyph">🧙‍♂️</span>
            <span className={`coach-avatar-pulse ${isSpeaking ? 'speaking' : coachThinking ? 'thinking' : 'idle'}`} />
          </div>
          <div className="coach-window-info">
            <div className="coach-window-title-row">
              <h2 className="coach-window-title">
                {isChinese ? 'Luna · 国际象棋教练' : 'Luna · Chess Coach'}
              </h2>
              <span className="coach-live-badge">
                {coachThinking
                  ? isChinese ? '思考中…' : 'Thinking…'
                  : isSpeaking
                    ? isChinese ? '讲解中…' : 'Speaking'
                    : isChinese ? '就绪' : 'Live'}
              </span>
            </div>
            <p className="coach-window-subtitle">
              {isChinese
                ? '全盘实时监控 · 战术提点 · 深度苏格拉底教学'
                : 'Real-time observation · Tactical alerts · Socratic guidance'}
            </p>
          </div>
        </div>

        <div className="coach-window-controls">
          <button
            type="button"
            className={`coach-icon-toggle ${voiceEnabled ? 'active' : ''}`}
            onClick={() => onToggleVoice(!voiceEnabled)}
            title={voiceEnabled ? 'Voice enabled (click to mute)' : 'Voice muted (click to enable)'}
            aria-label="Toggle coach voice"
          >
            {voiceEnabled ? '🔊' : '🔇'}
          </button>

          <div className="coach-detail-pills">
            {(['quick', 'balanced', 'deep'] as const).map((detail) => (
              <button
                key={detail}
                type="button"
                className={`coach-detail-pill ${coachDetail === detail ? 'active' : ''}`}
                onClick={() => onChangeCoachDetail(detail)}
              >
                {detail === 'quick'
                  ? isChinese ? '简短' : 'Quick'
                  : detail === 'balanced'
                    ? isChinese ? '适中' : 'Balanced'
                    : isChinese ? '深度' : 'Deep'}
              </button>
            ))}
          </div>

          <button
            type="button"
            className="coach-lang-pill"
            onClick={() => onChangeCoachLanguage(isChinese ? 'en' : 'zh-CN')}
            title="Switch coach language"
          >
            {isChinese ? '中' : 'EN'}
          </button>
        </div>
      </div>

      <div className="coach-mode-tabs" role="group" aria-label={isChinese ? '教练窗口模式' : 'Coach window mode'}>
        <button type="button" aria-pressed={mode === 'coach'} onClick={() => setMode('coach')}>{isChinese ? '教练点评' : 'Coach'}{coachThinking && <span aria-label="Analyzing"> ···</span>}</button>
        <button type="button" aria-pressed={mode === 'chat'} onClick={() => setMode('chat')}>{isChinese ? '与 Luna 聊天' : 'Chat with Luna'} <span aria-hidden="true">☾</span></button>
      </div>
      <div className="coach-chat-body" hidden={mode !== 'chat'}>
        {criticalPrompt && isMyTurn && <div className="coach-callout critical-prompt-card" role="status">
          <strong>{criticalPrompt.mateThreat ? '⚠️ ' : '💡 '}{criticalPrompt.title}</strong><p>{criticalPrompt.question}</p>
        </div>}
        {coachResult?.shouldCoach && <details className="luna-coach-context"><summary>{isChinese ? '最近的教练点评' : 'Latest coaching'} · {coachResult.title}</summary><p>{coachResult.feedback}</p>{coachResult.question && <p>{coachResult.question}</p>}</details>}
        <LunaChat key={chatSessionId} sessionId={chatSessionId} position={chatPosition}
          language={coachLanguage} detail={coachDetail} coachQuestion={criticalPrompt?.question || coachResult?.question}
          onSpeak={onSpeakChat} />
      </div>

      {/* Coach Window Independent Scrollable Body */}
      <div className="coach-window-body custom-scroll" hidden={mode !== 'coach'}>
        {openingLabel && <div className="opening-badge coach-opening-badge" role="status">
          <strong>{openingLabel}</strong>
          {openingStatus && <small>{openingStatus}</small>}
        </div>}
        {/* Urgent Critical Prompt Before Move */}
        {criticalPrompt && isMyTurn ? (
          <section className="coach-callout critical-prompt-card">
            <div className="callout-header">
              <div className="callout-badge-wrap">
                <span className="callout-icon">{criticalPrompt.mateThreat ? '⚠️' : '💡'}</span>
                <span className={`callout-badge ${criticalPrompt.mateThreat ? 'danger' : 'attention'}`}>
                  {criticalPrompt.mateThreat
                    ? isChinese ? '将杀威胁 · 优先处理' : 'Mate Threat · Immediate Alert'
                    : criticalPrompt.kind === 'opportunity'
                      ? isChinese ? '战术机会' : 'Tactical Opportunity'
                      : criticalPrompt.kind === 'threat'
                        ? isChinese ? '对手企图' : 'Opponent Idea'
                        : isChinese ? '关键决策局面' : 'Critical Decision'}
                </span>
              </div>
              <span className="callout-kicker">
                {isChinese ? '落子之前，先想一想' : 'Pause before moving'}
              </span>
            </div>

            <h3 className="callout-title">{criticalPrompt.title}</h3>
            <p className="callout-question">{criticalPrompt.question}</p>
          </section>
        ) : null}

        {/* Coach Analysis Card */}
        {coachThinking ? (
          <div className="coach-thinking-card">
            <div className="thinking-waveform">
              <span /><span /><span /><span /><span />
            </div>
            <p>{isChinese ? '正在深入计算局面并解析战术要素…' : 'Analyzing move, tactical motives & engine diagnostics…'}</p>
          </div>
        ) : coachError ? (
          <div className="coach-error-card">
            <span className="error-icon">⚠️</span>
            <p>{coachError}</p>
          </div>
        ) : coachResult ? (
          <section className="coach-insight-card">
            <div className="insight-header">
              <div className="insight-title-group">
                <span className="insight-kicker">
                  {isChinese ? `第 ${coachResult.moveNumber} 回合点评` : `Move ${coachResult.moveNumber} Evaluation`}
                </span>
                <h3 className="insight-title">{coachResult.title}</h3>
              </div>

              {coachResult.shouldCoach && (
                <span className={`quality-badge ${coachResult.classification}`}>
                  {coachResult.classification}
                </span>
              )}
            </div>

            <p className="insight-feedback">{coachResult.feedback}</p>

            {/* Tactical Theme Pills */}
            {coachResult.themes && coachResult.themes.length > 0 && (
              <div className="insight-themes" aria-label="Chess themes">
                {coachResult.themes.map((theme) => (
                  <span key={theme} className="insight-theme-tag">
                    🏷️ {themeLabel(theme, coachLanguage)}
                  </span>
                ))}
              </div>
            )}

            {/* Socratic Question */}
            {coachResult.question && (
              <div className="insight-socratic-box">
                <div className="socratic-label">
                  <span>❓</span>
                  <strong>{isChinese ? '思考题' : 'Socratic Challenge'}</strong>
                </div>
                <p>{coachResult.question}</p>
              </div>
            )}

            {/* Coach Lesson */}
            {coachResult.lesson && (
              <div className="insight-lesson-box">
                <div className="lesson-label">
                  <span>♟️</span>
                  <strong>{isChinese ? '核心要诀' : 'Master Takeaway'}</strong>
                </div>
                <p>{coachResult.lesson}</p>
              </div>
            )}

            {/* Review Button */}
            <div className="insight-action-row">
              <button
                type="button"
                className="coach-review-btn"
                onClick={() => onReviewPosition(coachResult)}
              >
                <span>🔍</span>
                <span>{isChinese ? '深入复盘该局面' : 'Review & Test Lines'}</span>
              </button>
            </div>
          </section>
        ) : (
          <div className="coach-standby-card">
            <div className="standby-icon">👀</div>
            <div className="standby-text">
              <h3>{isChinese ? '全神贯注观战中' : 'Observing the Board'}</h3>
              <p>
                {isChinese
                  ? '走子后，我将立即为你分析战术意图、捕捉漏算，并在关键时刻触发提问。'
                  : 'Make your move on the board. I will instantly highlight tactical motives, flag blunders, and guide your calculation.'}
              </p>
            </div>
          </div>
        )}

        {/* Coach Timeline Feed from This Match */}
        {coachNotes.length > 0 && (
          <div className="coach-timeline-section">
            <div className="timeline-heading">
              <h4>{isChinese ? '本局教练手记' : 'Game Coaching Timeline'}</h4>
              <span className="timeline-count">{coachNotes.length}</span>
            </div>

            <p className="fine-print" role="status">{historyStatus === 'synced'
              ? isChinese ? '已保存到教练历史' : 'Saved to coaching history'
              : historyStatus === 'offline'
                ? isChinese ? '已保存在此设备，等待同步' : 'Saved on this device · waiting to sync'
                : historyStatus === 'unavailable'
                  ? isChinese ? '无法保存教练历史' : 'History could not be saved'
                  : isChinese ? '正在同步教练历史…' : 'Syncing coaching history…'}</p>
            <div className="coach-timeline-list">
              {coachNotes.map((note) => {
                const isSelected = currentPly === note.ply;
                return (
                  <div
                    key={`${note.gameId}-${note.ply}`}
                    className={`timeline-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => onSelectPly(note.ply)}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="timeline-item-meta">
                      <span className="timeline-ply">
                        {Math.floor((note.ply + 1) / 2)}.{note.ply % 2 === 1 ? '' : '..'}{note.playedMove}
                      </span>
                      <span className={`quality-badge-mini ${note.classification}`}>
                        {note.classification}
                      </span>
                    </div>
                    <p className="timeline-item-title">{note.title}</p>
                    <p className="timeline-item-snippet">{note.feedback}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Coach Window Footer */}
      <div className="coach-window-footer">
        <label className="coach-footer-toggle">
          <input
            type="checkbox"
            checked={hintsEnabled}
            onChange={(e) => onToggleHints(e.target.checked)}
          />
          <span>{isChinese ? '棋盘战术箭头' : 'Coach Board Arrows'}</span>
        </label>

        <span className="coach-footer-status">
          {ttsStatus.state === 'speaking'
            ? isChinese ? '正在语音讲解…' : 'Audio speaking'
            : isChinese ? '随时为你答疑' : 'Active Mentor'}
        </span>
      </div>
    </div>
  );
};
