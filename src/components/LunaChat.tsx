import { useEffect, useRef, useState } from 'react';
import type { CoachDetail, CoachLanguage } from '../coach';
import { loadChat, mergeChatTurns, positionLabel, readChatCache, sendChat, writeChatCache,
  type ChatCache, type ChatPosition, type ChatRequest } from '../lunaChat';

type Props = { sessionId: string; position: ChatPosition; language?: CoachLanguage; detail?: CoachDetail;
  coachQuestion?: string; onSpeak?: (text: string) => void };

// Mount with key=sessionId so a game or analysis change cannot reuse another conversation's state.
export function LunaChat({ sessionId, position, language = 'en', detail = 'balanced', coachQuestion, onSpeak }: Props) {
  const [cache, setCache] = useState<ChatCache>(() => readChatCache(sessionId));
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const [error, setError] = useState('');
  const [storageOk, setStorageOk] = useState(true);
  const [pending, setPending] = useState<ChatRequest | null>(null);
  const active = useRef(true);
  const sending = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const zh = language === 'zh-CN';

  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => { setStorageOk(writeChatCache(sessionId, cache)); }, [sessionId, cache]);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [cache.turns.length, pending]);

  async function refresh() {
    setLoading(true); setHistoryError('');
    try {
      const turns = await loadChat(sessionId);
      if (!active.current) return;
      setCache(old => {
        const completed = turns.some(turn => turn.requestId === old.attempt?.requestId);
        return { ...old, turns: mergeChatTurns(old.turns, turns),
          attempt: completed ? undefined : old.attempt,
          draft: completed && old.draft === old.attempt?.message ? '' : old.draft };
      });
    } catch {
      if (active.current) setHistoryError(zh ? '历史记录暂时无法连接，显示此设备上的副本。' : 'History is offline. Showing the copy on this device.');
    } finally { if (active.current) setLoading(false); }
  }
  useEffect(() => { void refresh(); }, [sessionId]); // Conversation identity is the only reload trigger.

  async function submit(request: ChatRequest) {
    if (sending.current || loading) return;
    sending.current = true; setBusy(true); setError(''); setPending(request);
    const staged = { ...cache, attempt: request };
    writeChatCache(sessionId, staged);
    setCache(staged);
    try {
      const turn = await sendChat(request);
      // Keep the local copy even if navigation unmounted this window while the server answered.
      const latest = readChatCache(sessionId);
      const next = { turns: mergeChatTurns(mergeChatTurns(cache.turns, latest.turns), [turn]),
        draft: latest.draft.trim() === request.message ? '' : latest.draft,
        attempt: latest.attempt?.requestId === request.requestId ? undefined : latest.attempt };
      writeChatCache(sessionId, next);
      if (active.current) { setCache(next); setHistoryError(''); }
    } catch (cause) {
      if (active.current) setError(cause instanceof Error ? cause.message : 'Luna could not answer. Try again.');
    } finally {
      sending.current = false;
      if (active.current) { setBusy(false); setPending(null); composer.current?.focus(); }
    }
  }
  function sendDraft() {
    const message = cache.draft.trim();
    if (!message || busy || loading) return;
    const old = cache.attempt;
    const request = old && old.message === message && old.fen === position.fen
      && old.language === language && old.detail === detail ? old : {
        ...position, moves: [...position.moves], sessionId, requestId: crypto.randomUUID(), message, language, detail,
      };
    void submit(request);
  }
  const suggestions = zh ? ['这个局面我该注意什么？', '为什么推荐这个走法？', '给我一个提示，先别说答案。']
    : ['What should I notice here?', 'Why is that move recommended?', 'Give me a hint, without the answer.'];

  return <section className="luna-chat" aria-label={zh ? '与 Luna 聊天' : 'Chat with Luna'}>
    <div className="luna-chat-heading"><div><span className="eyebrow">{zh ? '一起思考' : 'THINK TOGETHER'}</span><h3>{zh ? '与 Luna 聊天' : 'Chat with Luna'}</h3></div><span className="luna-context-chip" title={position.fen}>{positionLabel(position.fen, zh)}</span></div>
    <p className="luna-chat-caption">{zh ? '问问题，分享你的想法。Luna 会看到你发送时的棋盘。' : 'Ask why. Try an idea. Luna sees the board you’re looking at when you send.'}</p>
    <div className="luna-chat-transcript custom-scroll" role="log" aria-label={zh ? '聊天记录' : 'Conversation'} aria-live="polite" aria-relevant="additions">
      {!cache.turns.length && !pending && <div className="luna-chat-welcome"><span aria-hidden="true">☾</span><h4>{zh ? '不只是听讲，一起聊聊吧。' : 'Your next question belongs here.'}</h4><p>{zh ? '说说你的思路，或问我刚才的讲解。我会和你一起思考。' : 'Tell me what you’re thinking, ask about my coaching, or work through a position with me.'}</p></div>}
      {cache.turns.map(turn => <div className="luna-chat-turn" key={turn.requestId}>
        <p className="luna-turn-position" title={turn.fen}>{positionLabel(turn.fen, zh)}{turn.fen !== position.fen && <span> · {zh ? '之前的局面' : 'Earlier position'}</span>}</p>
        <div className="luna-bubble user"><strong>{zh ? '你' : 'You'}</strong><p>{turn.message}</p></div>
        <div className="luna-bubble assistant"><strong>☾ Luna</strong><p>{turn.reply}</p>{onSpeak && <button className="ghost luna-read-aloud" onClick={() => onSpeak(turn.reply)}>{zh ? '朗读' : 'Read aloud'}</button>}</div>
      </div>)}
      {pending && <div className="luna-chat-turn"><p className="luna-turn-position">{positionLabel(pending.fen, zh)}</p><div className="luna-bubble user"><strong>{zh ? '你' : 'You'}</strong><p>{pending.message}</p></div><div className="luna-bubble assistant"><strong>☾ Luna</strong><p role="status">{zh ? '正在查看棋盘，思考你的问题…' : 'Looking at the board and thinking about your question…'}</p>{pending.fen !== position.fen && <small>{zh ? '棋盘已改变，这次回答仍针对发送时的局面。' : 'The board changed. This reply will use the position you sent.'}</small>}</div></div>}
      <div ref={end} />
    </div>
    <div className="luna-suggestions" aria-label={zh ? '提问建议' : 'Question ideas'}>{suggestions.map(text => <button className="ghost" key={text} disabled={busy} onClick={() => { setCache(old => ({ ...old, draft: text })); composer.current?.focus(); }}>{text}</button>)}
      {coachQuestion && <button className="ghost" disabled={busy} onClick={() => { setCache(old => ({ ...old, draft: `${zh ? '关于你刚才的问题：' : 'About your question: '}${coachQuestion}\n` })); composer.current?.focus(); }}>{zh ? '讨论教练的问题' : 'Discuss your coaching question'}</button>}</div>
    {historyError && <p className="luna-chat-status" role="status">{historyError} <button className="ghost" disabled={busy || loading} onClick={() => void refresh()}>{zh ? '重新连接' : 'Reconnect'}</button></p>}
    {(error || (!busy && cache.attempt)) && <div className="inline-error" role="alert"><span>{error || (zh ? '有一个未确认的问题，可以重试。' : 'An earlier question has no confirmed reply. You can retry it.')}</span><button className="ghost" disabled={busy || loading} onClick={() => cache.attempt && void submit(cache.attempt)}>{zh ? '重试原来的问题' : 'Retry original question'}</button></div>}
    <form className="luna-composer" onSubmit={event => { event.preventDefault(); sendDraft(); }}>
      <label className="sr-only" htmlFor={`luna-message-${sessionId}`}>{zh ? '给 Luna 的消息' : 'Message Luna'}</label>
      <textarea id={`luna-message-${sessionId}`} ref={composer} rows={3} maxLength={2000} value={cache.draft} disabled={busy}
        placeholder={zh ? 'Luna，我在想…' : 'Luna, I’m thinking…'} onChange={event => setCache(old => ({ ...old, draft: event.target.value }))}
        onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); sendDraft(); } }} />
      <div className="luna-composer-footer"><small>{busy ? zh ? 'Luna 正在思考…' : 'Luna is thinking…' : loading ? zh ? '加载聊天记录…' : 'Loading conversation…' : zh ? 'Enter 发送 · Shift+Enter 换行' : 'Enter to send · Shift+Enter for a new line'}</small><button className="primary" disabled={busy || loading || !cache.draft.trim()} type="submit">{busy ? '…' : zh ? '发送 ↗' : 'Send ↗'}</button></div>
    </form>
    <p className="luna-chat-status">{zh ? '聊天与棋盘局面会保存在教练历史中。' : 'Conversation and position snapshots are saved in coaching history.'}{!storageOk && (zh ? ' 此浏览器无法保存离线副本。' : ' This browser could not save an offline copy.')}</p>
  </section>;
}
