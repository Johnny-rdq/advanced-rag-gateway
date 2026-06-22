import React, { useState, useEffect } from 'react';
import { BarChart3, Bot, User, MessageSquare, ChevronDown } from 'lucide-react';

function EvalPage({ sessions, API_BASE }) {
  const [selectedId, setSelectedId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [evalScores, setEvalScores] = useState({});
  const [evaluatingIdx, setEvaluatingIdx] = useState(null);
  const [evalTimes, setEvalTimes] = useState({});
  const [evalErrors, setEvalErrors] = useState({});

  useEffect(() => {
    if (selectedId) {
      loadMessages(selectedId);
    } else {
      setMessages([]);
      setEvalScores({});
    }
  }, [selectedId]);

  const loadMessages = async (sessionId) => {
    setMessages([]);
    setEvalScores({});
    try {
      const [msgRes, evalRes] = await Promise.all([
        fetch(`${API_BASE}/sessions/${sessionId}/messages`),
        fetch(`${API_BASE}/evaluations/${sessionId}`),
      ]);
      const msgData = await msgRes.json();
      const savedEvals = await evalRes.json();
      const msgs = msgData.messages || [];
      setMessages(msgs);
      const mapped = {};
      msgs.forEach((msg, idx) => {
        if (msg.role === 'user' && savedEvals[msg.content]) {
          mapped[idx + 1] = savedEvals[msg.content];
        }
      });
      if (Object.keys(mapped).length > 0) {
        setEvalScores(mapped);
      }
    } catch (error) {
      console.error('加载消息失败', error);
    }
  };

  const evaluateFaithfulness = async (msgIdx, question, answer, contextText) => {
    if (!question || !answer) return;
    setEvaluatingIdx(msgIdx);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 90000);
      const res = await fetch(`${API_BASE}/evaluate/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer, context_text: contextText || '' }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      const data = await res.json();
      const scores = data.scores || data;
      setEvalScores(prev => ({ ...prev, [msgIdx]: scores }));
      setEvalTimes(prev => ({ ...prev, [msgIdx]: data.elapsed_seconds }));
      setEvalErrors(prev => ({ ...prev, [msgIdx]: data.error || null }));
      fetch(`${API_BASE}/evaluations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: selectedId, question, answer, scores }),
      }).catch(() => {});
    } catch (error) {
      console.error('评估失败', error);
    } finally {
      setEvaluatingIdx(null);
    }
  };

  const sessionTitle = sessions.find(s => s.session_id === selectedId)?.title || '';

  return (
    <div className="flex-1 flex flex-col bg-white">
      <div className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="flex items-center gap-4">
          <h2 className="font-semibold text-gray-700">RAG 评估面板</h2>
          <div className="relative">
            <select
              value={selectedId || ''}
              onChange={(e) => setSelectedId(e.target.value || null)}
              className="appearance-none bg-gray-100 border border-gray-300 rounded-lg px-4 py-2 pr-10 text-sm text-gray-700 cursor-pointer hover:bg-gray-200 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">选择要评估的会话...</option>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>{s.title}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          </div>
          {sessionTitle && (
            <span className="text-xs text-gray-400 ml-2">{sessionTitle}</span>
          )}
        </div>
        {messages.length > 0 && (
          <span className="text-xs text-gray-400">{messages.length} 条消息</span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-6 no-scrollbar">
        {!selectedId ? (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 space-y-4">
            <BarChart3 className="w-16 h-16 text-gray-300" />
            <p className="text-lg font-medium">选择会话开始评估</p>
            <p className="text-sm">从上方下拉框选择一个已聊过的会话，对AI回答进行忠实度评估</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 space-y-4">
            <MessageSquare className="w-16 h-16 text-gray-300" />
            <p>该会话暂无消息</p>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((msg, idx) => {
              if (msg.role !== 'assistant' || !msg.content) return null;
              if (msg.content.startsWith('✅') || msg.content.startsWith('📎') || msg.content.startsWith('❌')) return null;
              const q = messages.slice(0, idx).reverse().find(m => m.role === 'user');
              const question = q?.content || '';
              const scoreObj = evalScores[idx];

              return (
                <div key={idx} className="bg-gray-50 border border-gray-200 rounded-xl p-5 hover:border-gray-300 transition-colors">
                  <div className="flex items-start gap-3 mb-4">
                    <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <User className="w-4 h-4 text-blue-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-gray-400 mb-1">问题</div>
                      <p className="text-sm text-gray-700 leading-relaxed">{question}</p>
                    </div>
                  </div>

                  <div className="flex items-start gap-3 mb-4">
                    <div className="w-7 h-7 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Bot className="w-4 h-4 text-gray-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-gray-400 mb-1">AI 回答</div>
                      <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                      {msg.context && (
                        <div className="mt-2 p-2.5 bg-amber-50 border border-amber-200 rounded-lg text-xs text-gray-500">
                          <span className="font-medium text-amber-700">📎 参考上下文：</span>
                          <span className="whitespace-pre-wrap">{msg.context}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 pl-10">
                    {scoreObj ? (
                      typeof scoreObj.faithfulness === 'number' ? (
                        <div className="flex items-center gap-2">
                          <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                            scoreObj.faithfulness >= 0.8 ? 'bg-green-50 text-green-700 border border-green-200' :
                            scoreObj.faithfulness >= 0.5 ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' :
                            'bg-red-50 text-red-600 border border-red-200'
                          }`}>
                            忠实度 {(scoreObj.faithfulness * 100).toFixed(0)}%
                          </span>
                          {evalTimes[idx] && (
                            <span className="text-xs text-gray-400">耗时 {evalTimes[idx]} 秒</span>
                          )}
                          <button
                            onClick={() => evaluateFaithfulness(idx, question, msg.content, msg.context || '')}
                            disabled={evaluatingIdx === idx}
                            className="text-xs text-gray-400 hover:text-blue-500 transition-colors"
                          >
                            {evaluatingIdx === idx ? '评估中...' : '重新评估'}
                          </button>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2">
                          <span className="px-3 py-1 rounded-full bg-red-50 text-red-600 border border-red-200 text-xs font-medium">
                            忠实度 计算失败
                          </span>
                          {evalErrors[idx] && (
                            <span className="text-xs text-red-400 max-w-md truncate" title={evalErrors[idx]}>
                              {evalErrors[idx]}
                            </span>
                          )}
                          {evalTimes[idx] && (
                            <span className="text-xs text-gray-400">耗时 {evalTimes[idx]} 秒</span>
                          )}
                          <button
                            onClick={() => evaluateFaithfulness(idx, question, msg.content, msg.context || '')}
                            disabled={evaluatingIdx === idx}
                            className="text-xs text-gray-400 hover:text-blue-500 transition-colors"
                          >
                            重试
                          </button>
                        </div>
                      )
                    ) : (
                      <button
                        onClick={() => evaluateFaithfulness(idx, question, msg.content, msg.context || '')}
                        disabled={evaluatingIdx === idx}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                          evaluatingIdx === idx
                            ? 'bg-gray-100 text-gray-400 cursor-wait'
                            : 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm'
                        }`}
                      >
                        <BarChart3 className="w-4 h-4" />
                        {evaluatingIdx === idx ? '评估中...' : '评估忠实度'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default EvalPage;
