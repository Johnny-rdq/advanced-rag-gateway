import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Plus, Trash2, Send, Paperclip, Bot, User, Database, FileText, BarChart3 } from 'lucide-react';
import { marked } from 'marked';
import EvalPage from './EvalPage.jsx';

const API_BASE = '/api';

function App() {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [page, setPage] = useState('chat');
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

  useEffect(() => {
    fetchSessions();
    fetchFiles();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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

  const loadSession = async (sessionId) => {
    setCurrentSessionId(sessionId);
    setMessages([]);
    try {
      const msgRes = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
      const msgData = await msgRes.json();
      setMessages(msgData.messages || []);
    } catch (error) {
      console.error('加载记录失败', error);
    }
  };

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

  const fetchFiles = async () => {
    try {
      const res = await fetch(`${API_BASE}/files`);
      const data = await res.json();
      setUploadedFiles(data);
    } catch (error) {
      console.error('获取文件列表失败', error);
    }
  };

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

  const sendMessage = async () => {
    if (!input.trim() || !currentSessionId || isLoading) return;

    const userQuery = input.trim();
    setInput('');
    setIsLoading(true);

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
              if (aiText.startsWith('⏳') || aiText.startsWith('🔧')) {
                aiText = chunk;
              } else {
                aiText += chunk;
              }
            }
          }

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

      fetchSessions();
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

  if (page === 'eval') {
    return (
      <div className="flex h-screen bg-gray-50 font-sans text-gray-800">
        <div className="w-64 bg-gray-900 text-gray-300 flex flex-col shadow-xl z-20">
          <div className="p-4 flex items-center gap-2 text-white font-bold text-lg border-b border-gray-800">
            <Database className="w-5 h-5 text-blue-400" />
            <span>AI 知识库系统</span>
          </div>
          <div className="p-3 space-y-1">
            <button
              onClick={() => setPage('chat')}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800/50 hover:text-gray-200 transition-colors text-sm"
            >
              <MessageSquare className="w-4 h-4" />
              对话
            </button>
            <button
              onClick={() => setPage('eval')}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-gray-800 text-white transition-colors text-sm"
            >
              <BarChart3 className="w-4 h-4" />
              RAG 评估
            </button>
          </div>
        </div>
        <EvalPage sessions={sessions} API_BASE={API_BASE} />
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50 font-sans text-gray-800">
      {/* ================= 左侧侧边栏 ================= */}
      <div className="w-64 bg-gray-900 text-gray-300 flex flex-col shadow-xl z-20">
        <div className="p-4 flex items-center gap-2 text-white font-bold text-lg border-b border-gray-800">
          <Database className="w-5 h-5 text-blue-400" />
          <span>AI 知识库系统</span>
        </div>

        <div className="p-3 space-y-1">
          <button
            onClick={() => setPage('chat')}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-gray-800 text-white transition-colors text-sm"
          >
            <MessageSquare className="w-4 h-4" />
            对话
          </button>
          <button
            onClick={() => setPage('eval')}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-gray-400 hover:bg-gray-800/50 hover:text-gray-200 transition-colors text-sm"
          >
            <BarChart3 className="w-4 h-4" />
            RAG 评估
          </button>
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

        <div className="flex-1 overflow-y-auto p-6 space-y-6 no-scrollbar pb-32">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-400 space-y-4">
              <Bot className="w-16 h-16 text-gray-300" />
              <p>你好！我是企业专属 AI。请上传文档或直接向我提问。</p>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
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

                  {msg.role === 'assistant' && msg.context && (
                    <div className="mt-2 ml-2 p-2.5 bg-amber-50 border border-amber-200 rounded-xl text-xs text-gray-600 leading-relaxed">
                      <div className="font-medium text-amber-700 mb-1">📎 参考来源</div>
                      <div className="whitespace-pre-wrap break-words">{msg.context}</div>
                    </div>
                  )}
                </div>

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
