import React, { useMemo } from 'react';
import type { CoachDetail, CoachLanguage } from '../coach';
import { readHistorySessions } from '../coachHistory';

type Props = {
  open: boolean;
  onClose: () => void;
  username?: string | null;
  coachDetail: CoachDetail;
  onChangeCoachDetail: (detail: CoachDetail) => void;
  coachLanguage: CoachLanguage;
  onChangeCoachLanguage: (lang: CoachLanguage) => void;
  voiceEnabled: boolean;
  onToggleVoice: (enabled: boolean) => void;
  hintsEnabled: boolean;
  onToggleHints: (enabled: boolean) => void;
  onLogout: () => void;
};

export const ProfileModal: React.FC<Props> = ({
  open,
  onClose,
  username,
  coachDetail,
  onChangeCoachDetail,
  coachLanguage,
  onChangeCoachLanguage,
  voiceEnabled,
  onToggleVoice,
  hintsEnabled,
  onToggleHints,
  onLogout,
}) => {
  const isChinese = coachLanguage === 'zh-CN';

  // Calculate user coaching statistics from historical sessions
  const stats = useMemo(() => {
    const sessions = readHistorySessions();
    let totalGames = sessions.length;
    let totalBlunders = 0;
    let totalMistakes = 0;
    let totalGoodMoves = 0;
    const themeCounts = new Map<string, number>();

    for (const session of sessions) {
      for (const rec of session.records) {
        if (rec.classification === 'blunder') totalBlunders++;
        else if (rec.classification === 'mistake') totalMistakes++;
        else if (rec.classification === 'good') totalGoodMoves++;

        if (rec.themes) {
          for (const theme of rec.themes) {
            themeCounts.set(theme, (themeCounts.get(theme) || 0) + 1);
          }
        }
      }
    }

    const topThemes = [...themeCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);

    return { totalGames, totalBlunders, totalMistakes, totalGoodMoves, topThemes };
  }, [open]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-card profile-modal-card custom-scroll" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <span className="modal-kicker">{isChinese ? '学员档案与教练偏好' : 'PLAYER PROFILE & COACH RAPPORT'}</span>
            <h2 className="modal-title">{username || (isChinese ? '本地学员' : 'Guest Student')}</h2>
          </div>
          <button type="button" className="ghost close-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {/* Player Stats Grid */}
        <div className="profile-stats-grid">
          <div className="stat-card">
            <span className="stat-icon">🎮</span>
            <strong className="stat-value">{stats.totalGames}</strong>
            <span className="stat-label">{isChinese ? '对局记录' : 'Training Games'}</span>
          </div>

          <div className="stat-card">
            <span className="stat-icon">🛡️</span>
            <strong className="stat-value">{stats.totalBlunders}</strong>
            <span className="stat-label">{isChinese ? '漏算提醒' : 'Blunders Caught'}</span>
          </div>

          <div className="stat-card">
            <span className="stat-icon">💡</span>
            <strong className="stat-value">{stats.totalMistakes}</strong>
            <span className="stat-label">{isChinese ? '失误复盘' : 'Mistakes Reviewed'}</span>
          </div>

          <div className="stat-card">
            <span className="stat-icon">⭐</span>
            <strong className="stat-value">{stats.totalGoodMoves}</strong>
            <span className="stat-label">{isChinese ? '妙手表扬' : 'Good Moves Praised'}</span>
          </div>
        </div>

        {/* Top Tactical Themes */}
        {stats.topThemes.length > 0 && (
          <div className="profile-section">
            <h3 className="profile-section-title">{isChinese ? '近期高频战术主题' : 'Top Tactical Focus Areas'}</h3>
            <div className="profile-theme-pills">
              {stats.topThemes.map(([theme, count]) => (
                <div key={theme} className="profile-theme-pill">
                  <span className="theme-name">{theme}</span>
                  <span className="theme-count">×{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Coach Preferences */}
        <div className="profile-section">
          <h3 className="profile-section-title">{isChinese ? 'AI 教练教学风格' : 'AI Coach Settings'}</h3>

          <div className="setting-row">
            <div>
              <strong>{isChinese ? '讲解详细度' : 'Explanations Detail'}</strong>
              <p className="setting-desc">
                {isChinese
                  ? '控制教练点评的长短与深度（简短、适中或苏格拉底深度启发）'
                  : 'Choose concise alerts, balanced tips, or deep Socratic reasoning'}
              </p>
            </div>
            <div className="setting-pill-group">
              {(['quick', 'balanced', 'deep'] as const).map((detail) => (
                <button
                  key={detail}
                  type="button"
                  className={`setting-pill ${coachDetail === detail ? 'active' : ''}`}
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
          </div>

          <div className="setting-row">
            <div>
              <strong>{isChinese ? '语音朗读' : 'Spoken Voice Coaching'}</strong>
              <p className="setting-desc">
                {isChinese ? '通过系统高品质语音实时朗读教练点评与提问' : 'Speak coach feedback and questions aloud'}
              </p>
            </div>
            <button
              type="button"
              className={`toggle-btn ${voiceEnabled ? 'on' : ''}`}
              onClick={() => onToggleVoice(!voiceEnabled)}
            >
              {voiceEnabled ? (isChinese ? '已开启' : 'ON') : (isChinese ? '已关闭' : 'OFF')}
            </button>
          </div>

          <div className="setting-row">
            <div>
              <strong>{isChinese ? '教学语言' : 'Coach Language'}</strong>
              <p className="setting-desc">
                {isChinese ? '切换教练对话与战术术语语言' : 'Language used for explanations and chess themes'}
              </p>
            </div>
            <div className="setting-pill-group">
              <button
                type="button"
                className={`setting-pill ${coachLanguage === 'en' ? 'active' : ''}`}
                onClick={() => onChangeCoachLanguage('en')}
              >
                English
              </button>
              <button
                type="button"
                className={`setting-pill ${coachLanguage === 'zh-CN' ? 'active' : ''}`}
                onClick={() => onChangeCoachLanguage('zh-CN')}
              >
                中文
              </button>
            </div>
          </div>

          <div className="setting-row">
            <div>
              <strong>{isChinese ? '棋盘战术箭头' : 'Coach Tactical Arrows'}</strong>
              <p className="setting-desc">
                {isChinese ? '在棋盘上高亮显示好手与威胁箭头' : 'Draw visual arrows for threats and best ideas'}
              </p>
            </div>
            <button
              type="button"
              className={`toggle-btn ${hintsEnabled ? 'on' : ''}`}
              onClick={() => onToggleHints(!hintsEnabled)}
            >
              {hintsEnabled ? (isChinese ? '已开启' : 'ON') : (isChinese ? '已关闭' : 'OFF')}
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="modal-footer">
          {username && (
            <button type="button" className="ghost danger-btn" onClick={onLogout}>
              {isChinese ? '退出 Lichess 登录' : 'Log Out of Lichess'}
            </button>
          )}
          <button type="button" className="primary" onClick={onClose}>
            {isChinese ? '完成' : 'Done'}
          </button>
        </div>
      </div>
    </div>
  );
};
