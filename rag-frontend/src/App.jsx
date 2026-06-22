import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Plus, Trash2, Send, Paperclip, Bot, User, Database, FileText, BarChart3 } from 'lucide-react';
import { marked } from 'marked';

const API_BASE = '/api';

function App() {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [evaluatingIdx, setEvaluatingIdx] = useState(null);
  const [evalScores, setEvalScores] = useState({});
  const chatEndRef = useRef(null);

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
    return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
  };

  const formatTimeAgo = (dateStr) => {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr + 'Z').getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return '刚刚';
    if (mins < 60) return mins + '分钟前';
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + '小时前';
    return Math.floor(hours / 24) + '天前';
  };

  // 1. 初始化：获取会话列表和文件列表
  useEffect(() => {
    fetchSessions();
    fetchFiles();
  }, []);

  // 2. 自动滚动到底部
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 拉取所有会话
  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_BASE}/sessions`);
      const data = await res.json();
      setSessions(data);
      if (data.length > 0 && !currentSessionId) {
        loadSession(data[0].session_id);
      } else if (data.length === 0) {
        createNewSession();
      }
    } catch (error) {
      console.error('无法连接到后端服务器', error);
    }
  };

  // 创建新会话
  const createNewSession = async () => {
    try {
      const res = await fetch(`${API_BASE}/sessions`, { method: 'POST' });
      const data = await res.json();
      setSessions((prev) => [data, ...prev]);
      loadSession(data.session_id);
    } catch (error) {
      alert('创建会话失败，请确保 Python 后端已启动！');
    }
  };

  // 加载某个特定会话的聊天记录
  const loadSession = async (sessionId) => {
    setCurrentSessionId(sessionId);
    setEvalScores({});
    setMessages([]);
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
      console.error('加载记录失败', error);
    }
  };

  // 删除会话
  const deleteSession = async (e, sessionId) => {
    e.stopPropagation();
    try {
      await fetch(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
      const newSessions = sessions.filter((s) => s.session_id !== sessionId);
      setSessions(newSessions);
      if (currentSessionId === sessionId) {
        if (newSessions.length > 0) {
          loadSession(newSessions[0].session_id);
        } else {
          createNewSession();
        }
      }
    } catch (error) {
      console.error('删除失败', error);
    }
  };

  // 获取已上传文件列表
  const fetchFiles = async () => {
    try {
      const res = await fetch(`${API_BASE}/files`);
      const data = await res.json();
      setUploadedFiles(data);
    } catch (error) {
      console.error('获取文件列表失败', error);
    }
  };

  // 删除已上传文件
  const deleteFile = async (e, fileId) => {
    e.stopPropagation();
    if (!window.confirm('确定要删除该文件吗？这将同时删除向量库中的知识片段！')) return;
    try {
      await fetch(`${API_BASE}/files/${fileId}`, { method: 'DELETE' });
      fetchFiles();
    } catch (error) {
      console.error('删除文件失败', error);
    }
  };

  // 评估某条 AI 回答（传入原始上下文，避免评估时重新检索拿到不同内容）
  const evaluateAnswer = async (msgIdx, question, answer, contextText) => {
    if (!question || !answer) return;

    setEvaluatingIdx(msgIdx);
    try {
      const res = await fetch(`${API_BASE}/evaluate/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, answer, context_text: contextText || '' }),
      });
      const data = await res.json();
      const scores = data.scores || data;
      setEvalScores(prev => ({ ...prev, [msgIdx]: scores }));
      // 持久化到后端，刷新/重启不丢失
      fetch(`${API_BASE}/evaluations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentSessionId, question, answer, scores }),
      }).catch(() => {});
    } catch (error) {
      console.error('评估失败', error);
    } finally {
      setEvaluatingIdx(null);
    }
  };

  // 上传文件
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', currentSessionId);

    try {
      const res = await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
      const data = await res.json();
      loadSession(currentSessionId);
      fetchFiles();
    } catch (error) {
      alert('上传失败，请检查网络或后端状态。');
    }
    e.target.value = '';
  };

  // 发送消息并处理流式输出
  const sendMessage = async () => {
    if (!input.trim() || !currentSessionId || isLoading) return;

    const userQuery = input.trim();
    setInput('');
    setIsLoading(true);

    // 显示用户消息和 AI 占位
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: userQuery },
      { role: 'assistant', content: '', context: '' },
    ]);

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: currentSessionId, query: userQuery }),
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let aiText = '';
      let sourceText = '';
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.trim()) continue;

          if (line.startsWith('data: [SOURCE]: ')) {
            sourceText = line.substring(16);
          } else if (line.startsWith('data: [THINKING]: ')) {
            aiText = '⏳ ' + line.substring(19);
          } else if (line.startsWith('data: [TOOL]: ')) {
            aiText = '🔧 正在调用 ' + line.substring(14) + ' ...';
          } else if (line.startsWith('data: ')) {
            const chunk = line.substring(6);
            if (!chunk.startsWith('LLM') && !chunk.startsWith('服务')) {
              // 首次收到真实内容时清掉占位文字
              if (aiText.startsWith('⏳') || aiText.startsWith('🔧')) {
                aiText = chunk;
              } else {
                aiText += chunk;
              }
            }
          }

          // 实时更新最后一个气泡
          setMessages((prev) => {
            const newMsgs = [...prev];
            newMsgs[newMsgs.length - 1] = {
              role: 'assistant',
              content: aiText,
              context: sourceText,
            };
            return newMsgs;
          });
        }
      }

      // 回答结束后，刷新会话列表
      fetchSessions();

      // 自动评估：传入 AI 生成时用的原始上下文，避免评估重新检索拿到不同内容
      if (aiText && !aiText.startsWith('✅') && !aiText.startsWith('📎')) {
        const capturedQuestion = userQuery;
        const capturedAnswer = aiText;
        const capturedContext = sourceText;
        const aiMsgIdx = messages.length + 1;
        evaluateAnswer(aiMsgIdx, capturedQuestion, capturedAnswer, capturedContext);
      }
    } catch (error) {
      setMessages((prev) => {
        const newMsgs = [...prev];
        newMsgs[newMsgs.length - 1].content = '⚠️ 抱歉，连接服务器失败。';
        return newMsgs;
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 font-sans text-gray-800">
      {/* ================= 左侧侧边栏 ================= */}
      <div className="w-64 bg-gray-900 text-gray-300 flex flex-col shadow-xl z-20">
        <div className="p-4 flex items-center gap-2 text-white font-bold text-lg border-b border-gray-800">
          <Database className="w-5 h-5 text-blue-400" />
          <span>AI 知识库系统</span>
        </div>

        <div className="p-3">
          <button
            onClick={createNewSession}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white py-2 px-4 rounded-lg transition-colors font-medium shadow-sm"
          >
            <Plus className="w-4 h-4" />
            新建对话
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1 no-scrollbar">
          {sessions.map((session) => (
            <div
              key={session.session_id}
              onClick={() => loadSession(session.session_id)}
              className={`group flex items-center justify-between p-3 rounded-lg cursor-pointer transition-all ${
                currentSessionId === session.session_id
                  ? 'bg-gray-800 text-white shadow-inner'
                  : 'hover:bg-gray-800/50 text-gray-400 hover:text-gray-200'
              }`}
            >
              <div className="flex items-center gap-3 overflow-hidden">
                <MessageSquare className="w-4 h-4 flex-shrink-0" />
                <span className="truncate text-sm font-medium">{session.title}</span>
              </div>
              <button
                onClick={(e) => deleteSession(e, session.session_id)}
                className="opacity-0 group-hover:opacity-100 hover:text-red-400 transition-opacity p-1"
                title="删除会话"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}

          {uploadedFiles.length > 0 && (
            <>
              <div className="pt-3 pb-1 px-2 text-xs font-semibold text-gray-500 uppercase tracking-wider border-t border-gray-700 mt-2">
                已上传文件
              </div>
              {uploadedFiles.map((file) => (
                <div
                  key={file.id}
                  className="group flex items-center justify-between p-2 rounded-lg text-gray-500 hover:bg-gray-800/30 transition-colors"
                  title={file.original_filename}
                >
                  <div className="flex items-center gap-2 overflow-hidden min-w-0">
                    <FileText className="w-3.5 h-3.5 flex-shrink-0 text-gray-500" />
                    <div className="truncate text-xs leading-tight">
                      <div className="truncate">{file.original_filename}</div>
                      <div className="text-gray-600 text-[10px]">{formatFileSize(file.file_size)} · {file.chunk_count}片段 · {formatTimeAgo(file.uploaded_at)}</div>
                    </div>
                  </div>
                  <button
                    onClick={(e) => deleteFile(e, file.id)}
                    className="opacity-0 group-hover:opacity-100 hover:text-red-400 transition-opacity p-0.5 flex-shrink-0"
                    title="删除文件"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ================= 右侧主聊天区 ================= */}
      <div className="flex-1 flex flex-col relative bg-white">
        {/* 顶部工具栏 */}
        <div className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-white/80 backdrop-blur-sm sticky top-0 z-10">
          <h2 className="font-semibold text-gray-700">
            {sessions.find((s) => s.session_id === currentSessionId)?.title || '加载中...'}
          </h2>
          <div>
            <label className="cursor-pointer flex items-center gap-2 bg-gray-100 hover:bg-gray-200 text-gray-600 px-4 py-2 rounded-full text-sm font-medium transition-colors border border-gray-200 shadow-sm">
              <Paperclip className="w-4 h-4" />
              <span>喂给AI新知识</span>
              <input type="file" className="hidden" accept=".txt,.pdf,.md,.csv,.docx,.doc,.pptx,.ppt,.png,.jpg,.jpeg,.tiff,.bmp,.gif,.xlsx,.xls,.html,.htm" onChange={handleFileUpload} />
            </label>
          </div>
        </div>

        {/* 聊天消息滚动区 */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 no-scrollbar pb-32">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-400 space-y-4">
              <Bot className="w-16 h-16 text-gray-300" />
              <p>你好！我是企业专属 AI。请上传文档或直接向我提问。</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {/* AI 的头像 */}
                {msg.role === 'assistant' && (
                  <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center mr-3 mt-1 flex-shrink-0 border border-blue-200">
                    <Bot className="w-5 h-5 text-blue-600" />
                  </div>
                )}

                <div className="max-w-[80%] flex flex-col">
                  <div
                    className={`px-5 py-3.5 rounded-2xl shadow-sm ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white rounded-tr-none'
                        : 'bg-white border border-gray-200 text-gray-800 rounded-tl-none md-content'
                    }`}
                  >
                    {/* 解析 Markdown 文本内容 */}
                    <div
                      dangerouslySetInnerHTML={{
                        __html: marked.parse(
                          msg.content ||
                            (isLoading && idx === messages.length - 1
                              ? '正在思考中...'
                              : '')
                        ),
                      }}
                      className={
                        isLoading && msg.role === 'assistant' && idx === messages.length - 1 && !msg.content
                          ? 'typing-cursor'
                          : ''
                      }
                    />
                  </div>

                  {/* 参考来源 */}
                  {msg.role === 'assistant' && msg.context && (
                    <div className="mt-2 ml-2 p-2.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-gray-600 leading-relaxed">
                      <div className="font-medium text-amber-700 mb-1">📎 参考来源</div>
                      <div className="whitespace-pre-wrap break-words">{msg.context}</div>
                    </div>
                  )}

                  {/* RAG 评估按钮 + 分数 */}
                  {msg.role === 'assistant' && msg.content && !msg.content.startsWith('✅') && !msg.content.startsWith('📎') && !msg.content.startsWith('❌') && (
                    <div className="mt-1 ml-2">
                      {evalScores[idx] ? (
                        <div className="flex flex-wrap gap-2 text-[11px]">
                          {evalScores[idx].faithfulness !== undefined && (
                            typeof evalScores[idx].faithfulness === 'number' ? (
                              <span className="px-2 py-0.5 rounded-full bg-green-50 text-green-700 border border-green-200" title="忠实度：回答是否完全基于提供的上下文">
                                忠实度 {(evalScores[idx].faithfulness * 100).toFixed(0)}%
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200" title={String(evalScores[idx].faithfulness)}>
                                忠实度 计算失败
                              </span>
                            )
                          )}
                          {evalScores[idx].answer_relevancy !== undefined && (
                            typeof evalScores[idx].answer_relevancy === 'number' ? (
                              <span className="px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200" title="答案相关性：回答与问题的相关程度">
                                相关性 {(evalScores[idx].answer_relevancy * 100).toFixed(0)}%
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200" title={String(evalScores[idx].answer_relevancy)}>
                                相关性 计算失败
                              </span>
                            )
                          )}
                          {evalScores[idx].context_precision !== undefined && (
                            typeof evalScores[idx].context_precision === 'number' ? (
                              <span className="px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200" title="上下文精确度：检索到的上下文中有多少真正有用">
                                精确度 {(evalScores[idx].context_precision * 100).toFixed(0)}%
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded-full bg-red-50 text-red-600 border border-red-200" title={String(evalScores[idx].context_precision)}>
                                精确度 计算失败
                              </span>
                            )
                          )}
                        </div>
                      ) : (
                        <button
                          onClick={() => {
                            const q = messages.slice(0, idx).reverse().find(m => m.role === 'user');
                            evaluateAnswer(idx, q?.content || '', msg.content, msg.context || '');
                          }}
                          disabled={evaluatingIdx === idx || isLoading}
                          className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-full transition-colors ${
                            evaluatingIdx === idx
                              ? 'bg-gray-100 text-gray-400 cursor-wait'
                              : 'bg-gray-50 text-gray-500 hover:bg-blue-50 hover:text-blue-600 border border-gray-200'
                          }`}
                          title="基于当前上下文评估此回答的质量"
                        >
                          <BarChart3 className="w-3 h-3" />
                          {evaluatingIdx === idx ? '评估中...' : 'RAG评估'}
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* 用户的头像 */}
                {msg.role === 'user' && (
                  <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center ml-3 mt-1 flex-shrink-0 border border-gray-300">
                    <User className="w-5 h-5 text-gray-500" />
                  </div>
                )}
              </div>
            ))
          )}
          <div ref={chatEndRef} />
        </div>

        {/* 底部输入框 */}
        <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-white via-white to-transparent pt-10">
          <div className="max-w-4xl mx-auto flex items-end gap-3 bg-white p-2 rounded-2xl border border-gray-300 shadow-lg focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition-all">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="输入您的问题 (Enter 发送，Shift+Enter 换行)..."
              className="flex-1 max-h-32 min-h-[44px] bg-transparent border-none focus:ring-0 resize-none py-2.5 px-4 outline-none no-scrollbar"
              rows={1}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || isLoading}
              className={`p-3 rounded-xl flex items-center justify-center transition-colors ${
                !input.trim() || isLoading
                  ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                  : 'bg-blue-600 text-white hover:bg-blue-700 shadow-md'
              }`}
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
          <div className="text-center text-xs text-gray-400 mt-3">
            AI 可能会犯错，重要决断请核对原文档。
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
